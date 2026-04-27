import logging
import time
import os
import sys
from collections import OrderedDict
from flask import Flask, request
import telebot
# Добавлен импорт BOT_NAME
from config import TG_TOKEN, NEURO_KEY, WEBHOOK_URL, SYSTEM_PROMPT, BOT_NAME
from bible_data import BIBLE_VERSES, get_verse_by_ref, get_verses_by_topic
from storage import add_favorite, get_favorites, remove_favorite

# --- НАСТРОЙКИ ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# threaded=False важен для Flask, чтобы обрабатывать запросы в основном потоке
bot = telebot.TeleBot(TG_TOKEN, threaded=False)
app = Flask(__name__)

# Кэш ответов (LRU)
CACHE = OrderedDict()
CACHE_TTL = 3600 * 24
CACHE_MAX = 100
user_cooldowns = {}

# --- УТИЛИТЫ ---

def clean_cache():
    now = time.time()
    keys_to_del = [k for k, v in CACHE.items() if now - v['time'] > CACHE_TTL]
    for k in keys_to_del:
        del CACHE[k]

def get_cached(prompt):
    clean_cache()
    return CACHE.get(prompt, {}).get('response')

def save_cache(prompt, response):
    clean_cache()
    if len(CACHE) >= CACHE_MAX:
        CACHE.popitem(last=False)
    CACHE[prompt] = {'response': response, 'time': time.time()}

def send_long_message(chat_id, text):
    """Разбивка длинных сообщений для telebot"""
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
        try:
            bot.send_message(chat_id, part, parse_mode="Markdown")
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения: {e}")

def call_neuro_api(query):
    """Заглушка для AI. Замените на реальный запрос к вашему API"""
    # Пример реального запроса через requests:
    # import requests
    # headers = {"Authorization": f"Bearer {NEURO_KEY}"}
    # data = {"prompt": f"{SYSTEM_PROMPT}\n{query}"}
    # resp = requests.post("https://api.your-ai.com/generate", json=data, headers=headers, timeout=10)
    # return resp.json().get('text', "Ошибка API")
    
    time.sleep(1.5) # Имитация задержки
    return f"🤖 *AI Ответ (Демо)*\n\nВопрос: \"{query}\"\n\n*(Здесь будет ответ от нейросети. Интеграция через requests готова в коде)*"

# --- ОБРАБОТЧИКИ КОМАНД ---

@bot.message_handler(commands=['start'])
def cmd_start(message):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(telebot.types.KeyboardButton("📖 Случайный стих"), telebot.types.KeyboardButton("❤️ Избранное"))
    markup.add(telebot.types.KeyboardButton("🔍 Поиск по теме"))
    
    text = (f"👋 Привет! Я {BOT_NAME}.\n\n"
            "Я помогу найти утешение в Библии.\n\n"
            "Команды:\n"
            "/random - Случайный стих\n"
            "/ask <вопрос> - Разбор вопроса через AI\n"
            "/fav - Избранное\n"
            "/help - Помощь")
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.message_handler(commands=['help'])
def cmd_help(message):
    help_text = ("📚 *Список команд:*\n\n"
                 "/start - Главное меню\n"
                 "/random - Случайный стих\n"
                 "/ask <текст> - Задать вопрос AI\n"
                 "/topic <тема> - Стихи по теме\n"
                 "/fav - Мое избранное\n"
                 "/save <ссылка> - Сохранить стих\n"
                 "/del <ссылка> - Удалить из избранного")
    bot.send_message(message.chat.id, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['random'])
def cmd_random(message):
    import random
    verse = random.choice(BIBLE_VERSES)
    text = f"📖 *{verse['ref']}*\n_{verse['text']}_"
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['ask'])
def cmd_ask(message):
    uid = message.from_user.id
    now = time.time()
    
    if uid in user_cooldowns and now - user_cooldowns[uid] < 5:
        bot.reply_to(message, "⏳ Подождите 5 секунд перед следующим вопросом.")
        return
    
    user_cooldowns[uid] = now
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "❌ Напишите вопрос после команды. Пример: `/ask Почему Бог допускает зло?`", parse_mode="Markdown")
        return
    
    query = args[1]
    prompt_key = f"{SYSTEM_PROMPT}_{query}"
    
    cached = get_cached(prompt_key)
    if cached:
        send_long_message(message.chat.id, cached)
        return
    
    status = bot.reply_to(message, "🤖 Думаю и ищу в Писании...")
    
    try:
        answer = call_neuro_api(query)
        save_cache(prompt_key, answer)
        bot.edit_message_text("✅ Готово!", chat_id=status.chat.id, message_id=status.message_id)
        send_long_message(message.chat.id, answer)
    except Exception as e:
        logger.error(f"AI Error: {e}")
        bot.edit_message_text("❌ Ошибка при получении ответа.", chat_id=status.chat.id, message_id=status.message_id)

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
            txt += "... (список обрезан)"
            break
    send_long_message(message.chat.id, txt)

@bot.message_handler(commands=['save'])
def cmd_save(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "❌ Использование: `/save Ин 3:16`")
        return
    
    ref = args[1]
    verse = get_verse_by_ref(ref)
    if not verse:
        bot.reply_to(message, f"❌ Стих `{ref}` не найден в базе.")
        return
    
    if add_favorite(message.from_user.id, verse['text'], verse['ref']):
        bot.reply_to(message, f"✅ *{verse['ref']}* сохранен!", parse_mode="Markdown")
    else:
        bot.reply_to(message, "ℹ️ Уже сохранено.")

@bot.message_handler(commands=['del'])
def cmd_del(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "❌ Использование: `/del Ин 3:16`")
        return
    
    if remove_favorite(message.from_user.id, args[1]):
        bot.reply_to(message, "🗑 Удалено.")
    else:
        bot.reply_to(message, "❌ Не найдено в избранном.")

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    txt = message.text.strip()
    if txt == "📖 Случайный стих":
        cmd_random(message)
    elif txt == "❤️ Избранное":
        cmd_fav(message)
    elif txt == "🔍 Поиск по теме":
        bot.reply_to(message, "Напишите тему (страх, радость, любовь), или используйте команду `/topic <тема>`")
    else:
        bot.reply_to(message, f"Хотите спросить об этом? Нажмите или напишите:\n`/ask {txt}`", parse_mode="Markdown")

# --- WEBHOOK & FLASK ---

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.stream.read().decode('utf-8')
    bot.process_new_updates([telebot.types.Update.de_json(update)])
    return '', 200

@app.route('/', methods=['GET'])
def health():
    return "Bible Bot is running", 200

def set_webhook():
    if WEBHOOK_URL:
        # Сначала удаляем старый вебхук, чтобы сбросить ошибочные настройки
        bot.remove_webhook()
        # Устанавливаем новый
        bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"Webhook установлен на: {WEBHOOK_URL}")
        
        # Проверка статуса
        info = bot.get_webhook_info()
        if info.url == WEBHOOK_URL:
            logger.info("✅ Webhook успешно проверен!")
        else:
            logger.error(f"❌ Ошибка: Telegram вернул другой URL: {info.url}")
    else:
        logger.warning("WEBHOOK_URL не задан! Бот не будет получать сообщения на Render.")

# --- ЗАПУСК ---

if __name__ == '__main__':
    logger.info("Запуск бота...")
    try:
        set_webhook()
        port = int(os.environ.get('PORT', 8000))
        logger.info(f"Flask запускается на порту {port}...")
        app.run(host='0.0.0.0', port=port)
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        sys.exit(1)
