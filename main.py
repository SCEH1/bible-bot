"""
Telegram-бот для глубокого библейского разбора
Версия 2.0 - модульная архитектура
"""
import telebot
from telebot import types
import requests
import time
import random
import logging
import os
from collections import deque
from flask import Flask, request
import re

# ✅ ИМПОРТЫ ИЗ НАШИХ МОДУЛЕЙ
from config import TG_TOKEN, NEURO_KEY, MODEL_NAME, SYSTEM_PROMPT, BIBLE_BOOKS
from bible_data import POPULAR_VERSES

# ================= НАСТРОЙКА ЛОГИРОВАНИЯ =================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ================= ИНИЦИАЛИЗАЦИЯ =================
bot = telebot.TeleBot(TG_TOKEN)
processed_updates = deque(maxlen=1000)
pending_messages = {}
last_verse = {}

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================

def get_random_verse():
    """🎲 Случайный стих из базы"""
    key = random.choice(list(POPULAR_VERSES.keys()))
    text = POPULAR_VERSES[key]
    logger.info(f"📖 Стих: {key}")
    return f"{key}\n\n{text}"

def send_smart_split(chat_id, text):
    """Умная разбивка длинных сообщений"""
    max_length = 4000
    
    if len(text) <= max_length:
        bot.send_message(chat_id, text, parse_mode='HTML')
        return
    
    lines = text.split('\n')
    current_part = ""
    parts = []
    
    for line in lines:
        test_part = current_part + line + '\n'
        if len(test_part) > max_length:
            if current_part.strip():
                parts.append(current_part.strip())
            current_part = line + '\n'
        else:
            current_part = test_part
    
    if current_part.strip():
        parts.append(current_part.strip())
    
    for i, part in enumerate(parts, 1):
        bot.send_message(chat_id, part, parse_mode='HTML')
        logger.info(f"Часть {i}/{len(parts)}")
        time.sleep(0.3)

def get_main_keyboard():
    """Главная клавиатура"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("📖 Стих дня"))
    return markup

def is_bible_reference(text):
    """Проверка библейской ссылки"""
    text_lower = text.lower()
    bible_pattern = r'\b(' + '|'.join(BIBLE_BOOKS) + r')\b.*?\s*(\d+)[.:](\d+)'
    has_reference = bool(re.search(bible_pattern, text_lower))
    is_long = len(text) >= 50
    return has_reference or is_long

def do_parse(chat_id, verse_text):
    """✅ Универсальная функция разбора"""
    msg = bot.send_message(chat_id, "🔍 <b>Делаю разбор...</b>", parse_mode='HTML')
    pending_messages[chat_id] = msg.message_id
    bot.send_chat_action(chat_id, 'typing')
    
    for attempt in range(3):
        try:
            response = requests.post(
                "https://neuroapi.host/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {NEURO_KEY.strip()}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": MODEL_NAME,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": verse_text}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 4000,
                    "safety_settings": [
                        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
                    ]
                },
                timeout=50
            )
            
            if response.status_code == 200:
                ans = response.json()['choices'][0]['message']['content'].strip()
                
                if chat_id in pending_messages:
                    try:
                        bot.delete_message(chat_id, pending_messages[chat_id])
                    except:
                        pass
                    del pending_messages[chat_id]
                
                send_smart_split(chat_id, ans)
                logger.info("✅ Разбор готов")
                return True
            else:
                error_msg = f"❌ Ошибка API: Status {response.status_code}\n{response.text}"
                logger.warning(error_msg)
                # Если это последняя попытка, отправим ошибку пользователю
                if attempt == 2:
                    if chat_id in pending_messages:
                        try:
                            bot.delete_message(chat_id, pending_messages[chat_id])
                        except:
                            pass
                        del pending_messages[chat_id]
                    bot.send_message(chat_id, error_msg, reply_markup=get_main_keyboard())
                    return False
                
        except Exception as e:
            logger.error(f"Попытка {attempt + 1}: {e}")
        
        if attempt < 2:
            time.sleep(2 ** attempt)
    
    if chat_id in pending_messages:
        try:
            bot.delete_message(chat_id, pending_messages[chat_id])
        except:
            pass
        del pending_messages[chat_id]
    
    bot.send_message(chat_id, "❌ Ошибка разбора. Попробуй позже!", reply_markup=get_main_keyboard())
    return False

# ================= ОБРАБОТЧИКИ =================

@bot.message_handler(commands=['start'])
def welcome(message):
    markup = get_main_keyboard()
    bot.send_message(
        message.chat.id,
        "🕊 <b>Бот для глубокого библейского разбора готов!</b>\n\n"
        "<i>Что можно:</i>\n"
        "• <b>Римлянам 5:1</b> - ссылка на стих\n"
        "• <b>📖 Стих дня</b> - случайный стих из 220+\n"
        "• Полный текст стиха для разбора",
        parse_mode='HTML',
        reply_markup=markup
    )
    logger.info(f"Новый пользователь: {message.chat.id}")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    text = message.text.strip()
    
    logger.info(f"Сообщение: '{text[:50]}'")
    
    if text == "📖 Стих дня":
        verse = get_random_verse()
        last_verse[chat_id] = verse
        
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🔍 Разобрать", callback_data="parse"))
        markup.row(types.InlineKeyboardButton("🎲 Другой стих", callback_data="new"))
        
        bot.send_message(
            chat_id,
            f"📖 <b>Стих дня:</b>\n\n{verse}",
            parse_mode='HTML',
            reply_markup=markup
        )
        return
    
    if not is_bible_reference(text):
        markup = get_main_keyboard()
        bot.send_message(
            chat_id,
            "📖 Пришли <b>библейскую ссылку</b> или текст:\n\n"
            "• Римлянам 5:1\n"
            "• Иоанна 3:16\n"
            "• Или <b>📖 Стих дня</b>",
            parse_mode='HTML',
            reply_markup=markup
        )
        return
    
    do_parse(chat_id, text)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    
    if call.data == "new":
        verse = get_random_verse()
        last_verse[chat_id] = verse
        
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🔍 Разобрать", callback_data="parse"))
        markup.row(types.InlineKeyboardButton("🎲 Другой стих", callback_data="new"))
        
        try:
            bot.edit_message_text(
                f"📖 <b>Стих дня:</b>\n\n{verse}",
                chat_id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=markup
            )
        except Exception as e:
            logger.error(f"Ошибка edit: {e}")
    
    elif call.data == "parse":
        if chat_id in last_verse:
            do_parse(chat_id, last_verse[chat_id])
        else:
            bot.send_message(chat_id, "❌ Стих не найден. Нажми <b>📖 Стих дня</b>", parse_mode='HTML')

# ================= FLASK WEBHOOK =================

if __name__ == "__main__":
    app = Flask(__name__)
    
    @app.route("/" + TG_TOKEN, methods=["POST"])
    def webhook():
        try:
            json_str = request.get_data().decode("UTF-8")
            update = telebot.types.Update.de_json(json_str)
            
            if update.update_id in processed_updates:
                return "", 200
            
            processed_updates.append(update.update_id)
            bot.process_new_updates([update])
            return "", 200
            
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return "", 500
    
    @app.route("/")
    def index():
        return "🕊 Bible Bot v2.0 - Ready!", 200
    
    bot.remove_webhook()
    WEBHOOK_URL = f"https://bible-bot-ssx4.onrender.com/{TG_TOKEN}"
    bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"🚀 Webhook: {WEBHOOK_URL}")
    logger.info(f"📚 База: {len(POPULAR_VERSES)} стихов")
    
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
