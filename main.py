import telebot
from telebot import types
import requests
import os
import time
from datetime import datetime
from keep_alive import keep_alive

# ================= НАСТРОЙКИ =================
TG_TOKEN = os.environ.get("TG_TOKEN")
NEURO_KEY = os.environ.get("NEURO_KEY")
MODEL_NAME = "gemini-2.0-flash-lite" 
# =============================================

bot = telebot.TeleBot(TG_TOKEN)
user_history = {}

SYSTEM_PROMPT = """Ты — библейский исследователь и пастор (Sola Scriptura). 
Сделай глубокий экзегетический разбор текста по 8 пунктам. Используй EMOJI."""

def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🧹 Очистить контекст"))
    return markup

# Решение проблемы длинных сообщений (Римлянам 5:1)
def send_smart_split(chat_id, text):
    if len(text) <= 4000:
        bot.send_message(chat_id, text, reply_markup=get_main_keyboard())
    else:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for part in parts:
            bot.send_message(chat_id, part, reply_markup=get_main_keyboard())
            time.sleep(1)

@bot.message_handler(commands=['start'])
def welcome(message):
    user_history[message.chat.id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    bot.send_message(message.chat.id, "Привет, Vik! 🕊 Бот на GitHub + Render готов.", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    if message.text == "🧹 Очистить контекст":
        user_history[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
        bot.send_message(chat_id, "Контекст очищен! ✨")
        return

    bot.send_chat_action(chat_id, 'typing')
    if chat_id not in user_history:
        user_history[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    user_history[chat_id].append({"role": "user", "content": message.text})

    try:
        response = requests.post(
            "https://neuroapi.host/v1/chat/completions",
            headers={"Authorization": f"Bearer {NEURO_KEY}"},
            json={"model": MODEL_NAME, "messages": user_history[chat_id], "temperature": 0.7},
            timeout=120
        )
        if response.status_code == 200:
            ans = response.json()['choices'][0]['message']['content']
            for char in ['*', '#', '_', '`']: ans = ans.replace(char, '')
            ans = ans.strip()
            if ans and ans[0].islower(): ans = ans[0].upper() + ans[1:]
            
            user_history[chat_id].append({"role": "assistant", "content": ans})
            send_smart_split(chat_id, ans)
    except Exception as e:
        bot.send_message(chat_id, f"Ошибка: {e}")

if __name__ == "__main__":
    keep_alive()
    bot.infinity_polling()
