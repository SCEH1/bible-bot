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
import threading
import html

# ✅ ИМПОРТЫ ИЗ НАШИХ МОДУЛЕЙ
from config import TG_TOKEN, NEURO_KEY, MODEL_NAME, SYSTEM_PROMPT, BIBLE_BOOKS, COOLDOWN_SECONDS
try:
    from bible_data import POPULAR_VERSES, VERSE_THEMES
except ImportError:
    from bible_data import POPULAR_VERSES
    VERSE_THEMES = {}
from storage import add_favorite, get_favorites, remove_favorite

# ================= НАСТРОЙКА ЛОГИРОВАНИЯ =================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ================= ИНИЦИАЛИЗАЦИЯ =================
bot = telebot.TeleBot(TG_TOKEN)
processed_updates = deque(maxlen=1000)
pending_messages = {}
last_verse = {}
last_request_time = {}

# Лимит одновременных фоновых разборов
parse_semaphore = threading.Semaphore(3)

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================

def get_random_verse():
    """🎲 Случайный стих из базы"""
    key = random.choice(list(POPULAR_VERSES.keys()))
    text = POPULAR_VERSES[key]
    logger.info(f"📖 Стих: {key}")
    return f"{key}\n\n{text}"


def get_theme_keyboard():
    """Инлайн-клавиатура тем"""
    markup = types.InlineKeyboardMarkup()
    for idx, theme_name in enumerate(VERSE_THEMES.keys(), start=1):
        markup.row(types.InlineKeyboardButton(theme_name, callback_data=f"theme:{idx}"))
    return markup


def get_theme_name_by_idx(idx):
    keys = list(VERSE_THEMES.keys())
    if 0 <= idx < len(keys):
        return keys[idx]
    return None


def get_random_verse_from_theme(theme_name):
    refs = VERSE_THEMES.get(theme_name, [])
    if not refs:
        return None

    ref = random.choice(refs)
    text = POPULAR_VERSES.get(ref)
    if not text:
        return None
    return f"{ref}\n\n{text}"


def format_verse_card(verse_blob, icon="📖"):
    """
    Красивый вывод стиха:
    📖 Ссылка
    «Текст стиха»
    """
    if not verse_blob:
        return f"{icon} <b>Стих не найден</b>"

    if "\n\n" in verse_blob:
        verse_ref, verse_text = verse_blob.split("\n\n", 1)
    else:
        verse_ref, verse_text = verse_blob.strip(), ""

    safe_ref = html.escape(verse_ref.strip())
    safe_text = html.escape(verse_text.strip())

    if not safe_text:
        return f"{icon} <b>{safe_ref}</b>"

    return f"{icon} <b>{safe_ref}</b>\n<i>«{safe_text}»</i>"


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
    markup.add(types.KeyboardButton("📖 Стих дня"), types.KeyboardButton("📚 По теме"))
    markup.add(types.KeyboardButton("⭐ Избранное"))
    return markup


def get_post_parse_keyboard():
    """CTA после разбора"""
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("🎲 Другой стих", callback_data="new"))
    markup.row(types.InlineKeyboardButton("📚 Выбрать тему", callback_data="choose_theme"))
    return markup


def get_verse_actions_keyboard():
    """Кнопки для стиха до разбора"""
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("🔍 Разобрать", callback_data="parse"))
    markup.row(types.InlineKeyboardButton("⭐ Сохранить стих", callback_data="fav_save"))
    markup.row(types.InlineKeyboardButton("🎲 Другой стих", callback_data="new"))
    markup.row(types.InlineKeyboardButton("📚 Выбрать тему", callback_data="choose_theme"))
    return markup


def is_bible_reference(text):
    """Проверка библейской ссылки"""
    text_lower = text.lower()
    bible_pattern = r'\b(' + '|'.join(BIBLE_BOOKS) + r')\b.*?\s*(\d+)[.:](\d+)'
    has_reference = bool(re.search(bible_pattern, text_lower))
    is_long = len(text) >= 50
    return has_reference or is_long


def is_on_cooldown(chat_id):
    """Проверка cooldown для пользователя"""
    now = time.time()
    last_time = last_request_time.get(chat_id, 0)
    elapsed = now - last_time
    remaining = int(max(0, COOLDOWN_SECONDS - elapsed))
    return remaining > 0, remaining


def mark_request(chat_id):
    """Отмечаем время последнего запроса"""
    last_request_time[chat_id] = time.time()


def format_ai_answer(raw_text):
    """
    Приводит ответ ИИ к аккуратному виду для Telegram (HTML):
    - убирает markdown-заголовки вида ###;
    - сохраняет акценты через <b>...</b>;
    - нормализует пустые строки.
    """
    text = raw_text.strip()

    # Markdown bold -> HTML bold
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)

    # Markdown headings (### Заголовок) -> HTML bold
    text = re.sub(r"(?m)^\s*#{1,6}\s*(.+?)\s*$", r"<b>\1</b>", text)

    # Нормализация заголовков в формат из 8 пунктов
    heading_variants = [
        (r"контекст\s+и\s+авторств", "🌟 1. КОНТЕКСТ И АВТОРСТВО"),
        (r"жанр\s+и\s+стил", "🕊️ 2. ЖАНР И СТИЛЬ"),
        (r"ключев\w*\s+слов\w*\s+и\s+фраз", "✨ 3. КЛЮЧЕВЫЕ СЛОВА И ФРАЗЫ"),
        (r"теологи\w*\s+и\s+основн\w*\s+тем", "🚶‍♀️ 4. ТЕОЛОГИЯ И ОСНОВНЫЕ ТЕМЫ"),
