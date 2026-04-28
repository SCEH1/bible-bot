import logging
import time
import os
import requests
from flask import Flask, request
import telebot
from config import TG_TOKEN, NEURO_KEY, WEBHOOK_URL, SYSTEM_PROMPT
from bible_data import BIBLE_VERSES, get_verse_by_ref
from storage import add_favorite, get_favorites, remove_favorite

# --- НАСТРОЙКИ ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TG_TOKEN, threaded=False)
app = Flask(__name__)

# Простой кэш и кулдаун
user_cooldowns = {}
CACHE = {} 

# --- ФУНКЦИЯ РАЗБОРА (AI) ---
def get_bible_analysis(text):
    """
    Отправляет текст в AI и получает строгий 8-пунктный разбор.
    """
    # Формируем жесткий промпт для структуры ответа
    prompt = f"""
    {SYSTEM_PROMPT}
    
    ЗАДАЧА: Сделать глубокий богословский разбор следующего текста или вопроса пользователя.
    ТЕКСТ: "{text}"
    
    ТРЕБУЕМЫЙ ФОРМАТ ОТВЕТА (строго по пунктам):
    1. 📜 **Контекст**: Кто написал, кому, когда и при каких обстоятельствах.
    2. 💡 **Основная мысль**: Суть отрывка в одном предложении.
    3. 🔍 **Разбор ключевых слов**: Значение важных оригинальных терминов (греч./евр.).
    4. 🏛 **Богословский смысл**: Что это говорит о Боге, человеке и спасении.
    5. 🕊 **Применение сегодня**: Как жить этим принципом в современном мире.
    6. ⚠️ **Предостережение**: Чего стоит избегать в толковании или применении.
    7. 🔗 **Перекрестные ссылки**: 2-3 связанных стиха из Библии.
    8. 🙏 **Молитва**: Краткая молитва на основе этого текста.
    
    Ответ должен быть теплым, пасторским и глубоким. Используй Markdown.
    """
    
    try:
        # ЗАМЕНИТЕ URL НИЖЕ НА ВАШ РЕАЛЬНЫЙ AI ЭНДПОИНТ
        # Если у вас нет внешнего API, этот блок нужно адаптировать под вашу модель
        api_url = "https://api.your-ai-provider.com/v1/chat/completions" 
        
        headers = {
            "Authorization": f"Bearer {NEURO_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-3.5-turbo", # Или ваша модель
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7
        }
        
        # ВНИМАНИЕ: Если у вас пока нет реального API, раскомментируйте блок ниже для теста:
        # return f"🤖 *Разбор текста: \"{text}\"*\n\n(Здесь будет полный 8-пунктный ответ от AI. Сейчас нужен рабочий URL API в коде main.py)"
        
        response = requests.post(api_url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data['choices'][0]['message']['content']
        
    except Exception as e:
        logger.error(f"AI Error: {e}")
        return f"❌ Ошибка соединения с AI: {str(e)}. Проверьте ключ и URL."

def send_long_message(chat_id, text):
    limit = 4096
    if len(text) <= limit:
        bot.send_message(chat_id, text, parse_mode="Markdown")
        return
    
    parts = []
    current = ""
    for line in text.split('\n'):
        if len(current) + len(line) + 1 > limit:
            parts.append(current)
            current = line
        else:
            current += ("\n" if current else "") + line
    if current:
        parts.append(current)
    
    for part in parts:
        bot.send_message(chat_id, part, parse_mode="Markdown")
        time.sleep(0.5)

# --- ОБРАБОТЧИКИ ---

@bot.message_handler(commands=['start'])
def cmd_start(message):
    text = (
        "👋 Привет! Я **Bible Bot v2.0**.\n\n"
        "Я здесь, чтобы ты мог глубоко понять Слово Божье.\n\n"
        "📖 **Что я делаю:**\n"
        "1. Просто напиши мне **ссылку на стих** (например: *Ин 3:16*) или **тему**.\n"
        "2. Я сделаю полный **8-пунктовый богословский разбор**.\n"
        "3. Ты можешь сохранить понравившийся разбор в избранное.\n\n"
        "✍️ *Напиши мне любой стих прямо сейчас, и я его разберу.*"
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['random'])
def cmd_random(message):
    import random
    verse = random.choice(BIBLE_VERSES)
    # Сразу отправляем на разбор
    handle_text_analysis(message, f"{verse['ref']} {verse['text']}")

@bot.message_handler(commands=['fav'])
def cmd_fav(message):
    favs = get_favorites(message.from_user.id)
    if not favs:
        bot.reply_to(message, "📭 Избранное пусто.")
        return
    
    txt = "❤️ *Ваше избранное:*\n\n"
    for i, item in enumerate(favs, 1):
        txt += f"{i}. *{item['reference']}*\n_{item['text']}_\n\n"
        if len(txt) > 4000:
            txt += "... (обрезано)"
            break
    send_long_message(message.chat.id, txt)

@bot.message_handler(commands=['save'])
def cmd_save(message):
    # Сохраняем последний разобранный стих (упрощенно: по аргументу)
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "Используй: `/save Ин 3:16`")
        return
    
    ref = args[1]
    verse = get_verse_by_ref(ref)
    if not verse:
        # Если стиха нет в базе, сохраняем просто текст ссылки
        verse_text = f"Стих: {ref}"
    else:
        verse_text = verse['text']
        
    if add_favorite(message.from_user.id, verse_text, ref):
        bot.reply_to(message, f"✅ *{ref}* сохранен!", parse_mode="Markdown")
    else:
        bot.reply_to(message, "ℹ️ Уже сохранено.")

@bot.message_handler(func=lambda m: True)
def handle_text_analysis(message):
    """
    Главный обработчик: принимает любой текст и делает разбор.
    """
    user_input = message.text.strip()
    uid = message.from_user.id
    
    # Кулдаун (защита от спама)
    now = time.time()
    if uid in user_cooldowns and now - user_cooldowns[uid] < 5:
        return # Игнорируем частые сообщения
    
    user_cooldowns[uid] = now
    
    # Индикатор процесса
    status_msg = bot.reply_to(message, "🕊️ Готовлю глубокий разбор Писания...")
    
    try:
        # Получаем анализ от AI
        analysis = get_bible_analysis(user_input)
        
        # Удаляем индикатор
        bot.delete_message(status_msg.chat.id, status_msg.message_id)
        
        # Отправляем результат
        send_long_message(message.chat.id, analysis)
        
    except Exception as e:
        bot.edit_message_text("❌ Произошла ошибка при разборе. Попробуйте позже.", 
                              chat_id=status_msg.chat.id, message_id=status_msg.message_id)
        logger.error(e)

# --- WEBHOOK ---

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.stream.read().decode('utf-8')
    bot.process_new_updates([telebot.types.Update.de_json(update)])
    return '', 200

@app.route('/', methods=['GET'])
def health():
    return "Bible Bot is running", 200

if __name__ == '__main__':
    logger.info("Запуск Bible Bot v2.0 (Focus Mode)...")
    if WEBHOOK_URL:
        bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"Webhook установлен: {WEBHOOK_URL}")
    
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
