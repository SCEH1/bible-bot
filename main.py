import telebot
from telebot import types
import requests
import os
import time
from flask import Flask, request

# ================= НАСТРОЙКИ =================
TG_TOKEN = os.environ.get("TG_TOKEN")
NEURO_KEY = os.environ.get("NEURO_KEY")
MODEL_NAME = "gemini-2.5-flash-lite"
# =============================================

bot = telebot.TeleBot(TG_TOKEN)

SYSTEM_PROMPT = """Ты — библейский исследователь и пастор. 
Сделай глубокий разбор текста по 8 пунктам. Используй только эмодзи для выделения пунктов, но НЕ используй звездочки, подчеркивания или любую другую markdown-разметку в тексте."""

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🧹 Очистить контекст"))
    return markup

def send_smart_split(chat_id, text):
    if len(text) <= 4000:
        bot.send_message(chat_id, text, reply_markup=get_main_keyboard())
    else:
        for i in range(0, len(text), 4000):
            bot.send_message(chat_id, text[i:i+4000], reply_markup=get_main_keyboard())
            time.sleep(0.5)

@bot.message_handler(commands=['start'])
def welcome(message):
    bot.send_message(message.chat.id, "🕊 Бот перезагружен и готов к работе на Render!", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    if message.text == "🧹 Очистить контекст":
        bot.send_message(chat_id, "Контекст очищен! ✨")
        return

    bot.send_chat_action(chat_id, 'typing')

    try:
        response = requests.post(
            "https://neuroapi.host/v1/chat/completions",
            headers={"Authorization": f"Bearer {NEURO_KEY}"},
            json={
                "model": MODEL_NAME, 
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": message.text}
                ], 
                "temperature": 0.7
            },
            timeout=120
        )
        if response.status_code == 200:
            ans = response.json()['choices'][0]['message']['content'].strip()
            send_smart_split(chat_id, ans)
        else:
            bot.send_message(chat_id, f"Ошибка API: {response.status_code}")
    except Exception as e:
        bot.send_message(chat_id, f"Произошла ошибка: {str(e)}")

if __name__ == "__main__":
    app = Flask(__name__)
    
    @app.route("/" + TG_TOKEN, methods=["POST"])
    def webhook():
        json_str = request.get_data().decode("UTF-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "", 200
    
    @app.route("/")
    def index():
        return "Bot is running!", 200
    
    # Устанавливаем webhook
    bot.remove_webhook()
    WEBHOOK_URL = f"https://bible-bot-ssx4.onrender.com/{TG_TOKEN}"
    bot.set_webhook(url=WEBHOOK_URL)
    print(f"Webhook установлен: {WEBHOOK_URL}")
    
    # Запускаем Flask
    app.run(host="0.0.0.0", port=8080)
