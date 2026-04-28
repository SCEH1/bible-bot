import logging
import time
import os
import sys
import requests
from flask import Flask, request
import telebot
from config import TG_TOKEN, NEURO_KEY, WEBHOOK_URL, SYSTEM_PROMPT
from bible_data import BIBLE_VERSES

# --- НАСТРОЙКИ ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TG_TOKEN, threaded=False)
app = Flask(__name__)

# Простой кэш, чтобы не спамить API одинаковыми вопросами
CACHE = {} 

def call_neuro_api(query):
    """Реальный запрос к нейросети"""
    try:
        # ЗАМЕНИТЕ URL НА ВАШ РЕАЛЬНЫЙ API, ЕСЛИ ОН ОТЛИЧАЕТСЯ
        # Если у вас нет внешнего API, этот блок вернет ошибку, 
        # поэтому я оставил заглушку ниже для теста, но с структурой запроса.
        
        headers = {"Authorization": f"Bearer {NEURO_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-3.5-turbo", # Или ваша модель
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": query}
            ]
        }
        
        # Пример запроса (раскомментируйте, если есть реальный эндпоинт)
        # response = requests.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers)
        # return response.json()['choices'][0]['message']['content']

        # --- ЗАГЛУШКА ДЛЯ ТЕСТА (УДАЛИТЬ ПРИ ПОДКЛЮЧЕНИИ РЕАЛЬНОГО API) ---
        time.sleep(1.5)
        return f"🙏 *Библейский ответ на ваш вопрос:*\n\nВы спросили: \"{query}\"\n\n(Здесь будет глубокий разбор от AI. Сейчас идет режим демонстрации, так как не указан реальный URL API в коде).\n\n*Совет:* Проверьте функцию call_neuro_api в main.py, чтобы подключить ваш провайдер."
        # ------------------------------------------------------------------

    except Exception as e:
        logger.error(f"AI Error: {e}")
        return "❌ Произошла ошибка при связи с мудростью. Попробуйте позже."

# --- ГЛАВНАЯ ЛОГИКА ---

@bot.message_handler(commands=['start', 'day'])
def send_daily_verse(message):
    """Отправляет случайный стих (Стих дня)"""
    import random
    verse = random.choice(BIBLE_VERSES)
    
    text = (
        f"🕊️ *Стих Дня*\n\n"
        f"📖 *{verse['ref']}*\n"
        f"_{verse['text']}_\n\n"
        f"Напишите мне любой вопрос или мысль, и я помогу вам разобраться в этом с библейской точки зрения."
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """Обрабатывает ВСЕ остальные сообщения как запрос на общение/разбор"""
    user_text = message.text
    
    # Игнорируем системные сообщения или пустые
    if not user_text or user_text.startswith('/'):
        return

    # Индикатор набора
    bot.send_chat_action(message.chat.id, 'typing')
    
    # Формируем промпт для общения
    prompt = f"{SYSTEM_PROMPT}\n\nСообщение пользователя: {user_text}"
    
    # Простая проверка кэша (чтобы не тратить лимиты на дубли)
    if prompt in CACHE:
        bot.reply_to(message, CACHE[prompt], parse_mode="Markdown")
        return

    try:
        answer = call_neuro_api(user_text)
        CACHE[prompt] = answer # Сохраняем в кэш
        
        # Отправляем ответ
        bot.reply_to(message, answer, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(e)
        bot.reply_to(message, "❌ Ошибка соединения. Попробуйте позже.")

# --- WEBHOOK & ЗАПУСК ---

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.stream.read().decode('utf-8')
    bot.process_new_updates([telebot.types.Update.de_json(update)])
    return '', 200

@app.route('/', methods=['GET'])
def health():
    return "Bible Bot is running", 200

if __name__ == '__main__':
    logger.info("Запуск минималистичного Bible Bot...")
    if WEBHOOK_URL:
        bot.remove_webhook()
        bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"Webhook установлен: {WEBHOOK_URL}")
    
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
