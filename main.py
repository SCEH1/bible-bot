import logging
import time
import signal
import sys
import os
import telebot
from flask import Flask, request
from threading import Thread, Lock
from collections import OrderedDict

from config import TG_TOKEN, NEURO_KEY, WEBHOOK_URL, SYSTEM_PROMPT, COOLDOWN_SECONDS
from bible_data import BIBLE_VERSES, get_verse_by_ref, get_verses_by_topic
from storage import add_favorite, get_favorites, remove_favorite

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = telebot.TeleBot(TG_TOKEN)
app = Flask(__name__)

# Кэш ответов (LRU)
CACHE = OrderedDict()
CACHE_MAX_SIZE = 100
CACHE_TTL = 3600 * 24
cache_lock = Lock()

# Кулдаун пользователей
user_cooldowns = {}
cooldown_lock = Lock()

# --- УТИЛИТЫ ---

def clean_cache():
    now = time.time()
    keys_to_delete = [k for k, v in CACHE.items() if now - v['time'] > CACHE_TTL]
    with cache_lock:
        for k in keys_to_delete:
            del CACHE[k]

def get_cached_response(prompt: str):
    clean_cache()
    with cache_lock:
        if prompt in CACHE:
            logger.info(f"Кэш: {prompt[:20]}...")
            return CACHE[prompt]['response']
    return None

def save_to_cache(prompt: str, response: str):
    clean_cache()
    with cache_lock:
        if len(CACHE) >= CACHE_MAX_SIZE:
            CACHE.popitem(last=False)
        CACHE[prompt] = {'response': response, 'time': time.time()}

def send_long_message(chat_id, text):
    """Разбивка длинных сообщений для telebot"""
    max_len = 4096
    if len(text) <= max_len:
        bot.send_message(chat_id, text, parse_mode="Markdown")
        return
    
    parts = []
    current = ""
    for line in text.split('\n'):
        if len(current) + len(line) + 1 > max_len:
            parts.append(current)
            current = line
        else:
            current += ("\n" if current else "") + line
    if current:
        parts.append(current)
    
    for part in parts:
        bot.send_message(chat_id, part, parse_mode="Markdown")
        time.sleep(0.5)

def call_neuro_api_sync(question: str) -> str:
    """Синхронный вызов API (так как telebot по умолчанию синхронный)"""
    # ЗАМЕНИТЕ НА РЕАЛЬНЫЙ ЗАПРОС ЧЕРЕЗ requests.post(...)
    # Пример:
    # headers = {"Authorization": f"Bearer {NEURO_KEY}"}
    # resp = requests.post("URL_API", json={"prompt": question}, headers=headers)
    # return resp.json()['answer']
    
    time.sleep(1.5) # Имитация задержки
    return f"🤖 *AI Разбор (Демо)*\n\nВопрос: \"{question}\"\n\n*(Здесь будет ответ от вашего API)*"

# --- ОБРАБОТЧИКИ КОМАНД (TELEBOT) ---

@bot.message_handler(commands=['start'])
def handle_start(message):
    kb = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(telebot.types.KeyboardButton("📖 Случайный стих"))
    kb.add(telebot.types.KeyboardButton("❤️ Избранное"))
    kb.add(telebot.types.KeyboardButton("🔍 Поиск по теме"))
    
    text = (f"👋 Привет! Я {BOT_NAME}.\n\n"
            "Я помогу найти утешение в Библии.\n\n"
            "Команды:\n"
            "/random - случайный стих\n"
            "/ask <вопрос> - разбор вопроса через AI\n"
            "/fav - избранное")
    bot.send_message(message.chat.id, text, reply_markup=kb)

@bot.message_handler(commands=['help'])
def handle_help(message):
    text = ("📚 *Команды:*\n"
            "/start - Меню\n"
            "/random - Случайный стих\n"
            "/ask <текст> - Вопрос к AI\n"
            "/topic <тема> - Стихи по теме\n"
            "/fav - Избранное\n"
            "/save <ссылка> - Сохранить стих\n"
            "/del <ссылка> - Удалить стих")
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['random'])
def handle_random(message):
    import random
    verse = random.choice(BIBLE_VERSES)
    text = f"📖 *{verse['ref']}*\n_{verse['text']}_"
    kb = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(telebot.types.KeyboardButton("💾 Сохранить"))
    bot.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=kb)
    # Сохраняем последний стих в памяти для кнопки (упрощенно)
    # В продакшене лучше использовать user_data или FSM
    if not hasattr(handle_random, 'last_verse'):
        handle_random.last_verse = {}
    handle_random.last_verse[message.chat.id] = verse

@bot.message_handler(commands=['ask'])
def handle_ask(message):
    chat_id = message.chat.id
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        bot.send_message(chat_id, "❌ Пример: `/ask Почему Бог допускает зло?`", parse_mode="Markdown")
        return

    question = " ".join(args[1:])
    now = time.time()
    
    with cooldown_lock:
        last_time = user_cooldowns.get(chat_id, 0)
        if now - last_time < COOLDOWN_SECONDS:
            wait = int(COOLDOWN_SECONDS - (now - last_time))
            bot.send_message(chat_id, f"⏳ Подождите {wait} сек.")
            return
        user_cooldowns[chat_id] = now

    status_msg = bot.send_message(chat_id, "🤖 Думаю...")
    
    try:
        prompt = f"{SYSTEM_PROMPT}\nВопрос: {question}"
        cached = get_cached_response(prompt)
        
        if cached:
            answer = cached
        else:
            answer = call_neuro_api_sync(question)
            save_to_cache(prompt, answer)
        
        bot.delete_message(chat_id, status_msg.message_id)
        send_long_message(chat_id, answer)
    except Exception as e:
        logger.error(e)
        bot.edit_message_text("❌ Ошибка API.", chat_id, status_msg.message_id)

@bot.message_handler(commands=['fav'])
def handle_fav(message):
    favs = get_favorites(message.chat.id)
    if not favs:
        bot.send_message(message.chat.id, "📭 Пусто.")
        return
    
    text = "❤️ *Избранное:*\n\n"
    for i, item in enumerate(favs, 1):
        text += f"{i}. *{item['reference']}*\n_{item['text']}_\n\n"
        if len(text) > 4000:
            text += "... (обрезано)"
            break
    send_long_message(message.chat.id, text)

@bot.message_handler(commands=['save'])
def handle_save(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        # Если нажата кнопка "Сохранить" после /random
        if hasattr(handle_random, 'last_verse') and message.chat.id in handle_random.last_verse:
            verse = handle_random.last_verse[message.chat.id]
            if add_favorite(message.chat.id, verse['text'], verse['ref']):
                bot.send_message(message.chat.id, f"✅ {verse['ref']} сохранен!", parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, "Уже есть.")
            return
        
        bot.send_message(message.chat.id, "❌ Пример: `/save Ин 3:16`")
        return

    ref = args[1]
    verse = get_verse_by_ref(ref)
    if not verse:
        bot.send_message(message.chat.id, f"❌ {ref} не найден.")
        return
    
    if add_favorite(message.chat.id, verse['text'], verse['ref']):
        bot.send_message(message.chat.id, f"✅ {verse['ref']} сохранен!", parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "Уже есть.")

@bot.message_handler(commands=['del'])
def handle_del(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.send_message(message.chat.id, "❌ Пример: `/del Ин 3:16`")
        return
    if remove_favorite(message.chat.id, args[1]):
        bot.send_message(message.chat.id, "🗑 Удалено.", parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "Не найдено.")

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    txt = message.text.strip()
    if txt == "📖 Случайный стих":
        handle_random(message)
    elif txt == "❤️ Избранное":
        handle_fav(message)
    elif txt == "💾 Сохранить":
        # Эмуляция команды save
        msg = type('obj', (object,), {'chat.id': message.chat.id, 'text': '/save'})
        handle_save(msg)
    elif txt == "🔍 Поиск по теме":
        bot.send_message(message.chat.id, "Напишите тему (страх, радость...), я найду стихи.")
    else:
        bot.send_message(message.chat.id, 
                         f"Хотите спросить об этом?\nНапишите: `/ask {txt}`", 
                         parse_mode="Markdown")

# --- FLASK & WEBHOOK ---

@app.route('/', methods=['GET'])
def health():
    return "OK", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if update:
        bot.process_new_updates([telebot.types.Update.de_json(update)])
    return "", 200

def start_webhook():
    bot.remove_webhook()
    bot.set_webhook(WEBHOOK_URL)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

def start_polling():
    logger.info("Запуск polling...")
    bot.infinity_polling()

# --- ГЛАВНЫЙ ЗАПУСК ---

if __name__ == "__main__":
    logger.info("Бот запускается...")
    try:
        if WEBHOOK_URL:
            start_webhook()
        else:
            start_polling()
    except KeyboardInterrupt:
        logger.info("Остановка...")
        bot.stop_polling()
