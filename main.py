import telebot
from telebot import types
import requests
import os
import time
from keep_alive import keep_alive

# ================= НАСТРОЙКИ (БЕРЕМ ИЗ ENV) =================
TG_TOKEN = os.environ.get("TG_TOKEN")
NEURO_KEY = os.environ.get("NEURO_KEY")
MODEL_NAME = "gemini-2.0-flash-lite"
# ============================================================

bot = telebot.TeleBot(TG_TOKEN)

SYSTEM_PROMPT = """Ты — библейский исследователь и пастор (Sola Scriptura). 
Сделай глубокий экзегетический разбор текста по 8 пунктам. Используй EMOJI."""

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🧹 Очистить контекст"))
    return markup

# Решение ошибки "Message is too long"
def send_smart_split(chat_id, text):
    if len(text) <= 4000:
        bot.send_message(chat_id, text, reply_markup=get_main_keyboard())
    else:
        for i in range(0, len(text), 4000):
            bot.send_message(chat_id, text[i:i+4000], reply_markup=get_main_keyboard())
            time.sleep(0.5)

@bot.message_handler(commands=['start'])
def welcome(message):
    bot.send_message(message.chat.id, "Привет, Vik! 🕊 Я перезагружен и готов к работе на Render.", reply_markup=get_main_keyboard())

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
            if ans and ans[0].islower(): ans = ans[0].upper() + ans[1:]
            send_smart_split(chat_id, ans)
        else:
            bot.send_message(chat_id, f"Ошибка API: {response.status_code}")
    except Exception as e:
        bot.send_message(chat_id, f"Произошла ошибка: {str(e)}")

if __name__ == "__main__":
    # 1. Запускаем Flask-сервер для UptimeRobot
    keep_alive()
    
    # 2. Жёстко сбрасываем все старые сессии (Лечит ошибку 409)
    print("--- ОЧИСТКА ОЧЕРЕДИ И ЗАПУСК ---")
    bot.remove_webhook()
    time.sleep(1) 
    
    # 3. Запуск с параметром drop_pending_updates
    # Это удалит все сообщения, присланные боту, пока он был выключен, 
    # чтобы не вызвать новый конфликт.
    bot.infinity_polling(drop_pending_updates=True, timeout=60, long_polling_timeout=30)
