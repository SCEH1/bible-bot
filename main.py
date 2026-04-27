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
        (r"историко[-\s]?культурн\w*\s+фон", "💖 5. ИСТОРИКО-КУЛЬТУРНЫЙ ФОН"),
        (r"грамматик\w*\s+и\s+синтаксис", "🌟 6. ГРАММАТИКА И СИНТАКСИС"),
        (r"применени\w*\s+и\s+актуальност", "💪 7. ПРИМЕНЕНИЕ И АКТУАЛЬНОСТЬ"),
        (r"духовн\w*\s+размышлен", "📖 8. ДУХОВНОЕ РАЗМЫШЛЕНИЕ"),
    ]

    for variant, canonical in heading_variants:
        pattern = rf"(?im)^\s*(?:<b>)?(?:[^\w\n]*\d+[.)]\s*)?{variant}\s*:?(?:</b>)?\s*$"
        text = re.sub(pattern, f"<b>{canonical}</b>", text)

    # Если ИИ пропустил нумерацию, дожимаем 8-пунктный формат для строк "1. ...", "2. ..."
    numbered_map = {
        "1": "<b>🌟 1. КОНТЕКСТ И АВТОРСТВО</b>",
        "2": "<b>🕊️ 2. ЖАНР И СТИЛЬ</b>",
        "3": "<b>✨ 3. КЛЮЧЕВЫЕ СЛОВА И ФРАЗЫ</b>",
        "4": "<b>🚶‍♀️ 4. ТЕОЛОГИЯ И ОСНОВНЫЕ ТЕМЫ</b>",
        "5": "<b>💖 5. ИСТОРИКО-КУЛЬТУРНЫЙ ФОН</b>",
        "6": "<b>🌟 6. ГРАММАТИКА И СИНТАКСИС</b>",
        "7": "<b>💪 7. ПРИМЕНЕНИЕ И АКТУАЛЬНОСТЬ</b>",
        "8": "<b>📖 8. ДУХОВНОЕ РАЗМЫШЛЕНИЕ</b>",
    }
    for num, replacement in numbered_map.items():
        text = re.sub(rf"(?m)^\s*{num}[.)]\s+.+$", replacement, text)

    # Лишние пустые строки
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text


def do_parse(chat_id, verse_text):
    """✅ Универсальная функция разбора"""
    msg = bot.send_message(chat_id, "🔍 <b>Делаю разбор...</b>", parse_mode='HTML')
    pending_messages[chat_id] = msg.message_id
    bot.send_chat_action(chat_id, 'typing')

    if NEURO_KEY:
        masked_key = f"{NEURO_KEY[:4]}...{NEURO_KEY[-4:]}"
    else:
        masked_key = "None"
    logger.info(f"🔑 Использую ключ: {masked_key}")

    for attempt in range(3):
        try:
            headers = {
                "Authorization": f"Bearer {NEURO_KEY.strip()}",
                "Content-Type": "application/json"
            }

            response = requests.post(
                "https://neuroapi.host/v1/chat/completions",
                headers=headers,
                json={
                    "model": MODEL_NAME,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": verse_text}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 2200
                },
                timeout=50
            )

            if response.status_code == 200:
                ans = response.json()['choices'][0]['message']['content'].strip()
                ans = format_ai_answer(ans)

                if chat_id in pending_messages:
                    try:
                        bot.delete_message(chat_id, pending_messages[chat_id])
                    except Exception:
                        pass
                    del pending_messages[chat_id]

                send_smart_split(chat_id, ans)
                bot.send_message(chat_id, "Что дальше?", reply_markup=get_post_parse_keyboard())
                logger.info("✅ Разбор готов")
                return True
            else:
                error_msg = f"❌ Ошибка API: Status {response.status_code}\n{response.text}"
                logger.warning(error_msg)

                if attempt == 2:
                    if chat_id in pending_messages:
                        try:
                            bot.delete_message(chat_id, pending_messages[chat_id])
                        except Exception:
                            pass
                        del pending_messages[chat_id]
                    bot.send_message(chat_id, error_msg, reply_markup=get_main_keyboard())
                    return False

        except Exception as e:
            logger.error(f"Попытка {attempt + 1}: {e}")
            if attempt == 2:
                if chat_id in pending_messages:
                    try:
                        bot.delete_message(chat_id, pending_messages[chat_id])
                    except Exception:
                        pass
                    del pending_messages[chat_id]
                bot.send_message(
                    chat_id,
                    "❌ Произошла ошибка при обработке ответа. Попробуй другой стих!",
                    reply_markup=get_main_keyboard()
                )

        if attempt < 2:
            time.sleep(2 ** attempt)

    return False


def parse_in_background(chat_id, verse_text):
    """Фоновый запуск разбора с ограничением по количеству задач"""
    try:
        with parse_semaphore:
            do_parse(chat_id, verse_text)
    except Exception as e:
        logger.exception(f"Ошибка фонового разбора для {chat_id}: {e}")
        bot.send_message(
            chat_id,
            "❌ Ошибка при разборе. Попробуй ещё раз.",
            reply_markup=get_main_keyboard()
        )


def extract_verse_ref(verse_text):
    """Из 'Ссылка\\n\\nТекст' возвращает только ссылку."""
    if not verse_text:
        return None
    first_line = verse_text.split("\n", 1)[0].strip()
    return first_line if first_line else None


def send_favorites_list(chat_id):
    favorites = get_favorites(chat_id)
    if not favorites:
        bot.send_message(chat_id, "⭐ У тебя пока нет избранных стихов.")
        return

    markup = types.InlineKeyboardMarkup()
    lines = ["⭐ <b>Твои избранные стихи:</b>"]

    for idx, verse_ref in enumerate(favorites, start=1):
        lines.append(f"{idx}. {verse_ref}")
        markup.row(
            types.InlineKeyboardButton(f"🔍 Разобрать {idx}", callback_data=f"fav_parse:{idx}"),
            types.InlineKeyboardButton(f"🗑 Удалить {idx}", callback_data=f"fav_del:{idx}")
        )

    bot.send_message(chat_id, "\n".join(lines), parse_mode='HTML', reply_markup=markup)


# ================= ОБРАБОТЧИКИ =================

@bot.message_handler(commands=['start', 'help'])
def welcome(message):
    markup = get_main_keyboard()
    bot.send_message(
        message.chat.id,
        "🕊 <b>Бот для глубокого библейского разбора готов!</b>\n\n"
        "<i>Что можно:</i>\n"
        "• <b>Римлянам 5:1</b> - ссылка на стих\n"
        "• <b>📖 Стих дня</b> - случайный стих из 220+\n"
        "• <b>📚 По теме</b> - стихи по темам\n"
        "• <b>/favorite</b> - сохранить текущий стих\n"
        "• <b>/myfavorites</b> - открыть избранное\n"
        "• Полный текст стиха для разбора",
        parse_mode='HTML',
        reply_markup=markup
    )
    logger.info(f"Новый пользователь: {message.chat.id}")


@bot.message_handler(commands=['favorite'])
def favorite_command(message):
    chat_id = message.chat.id
    verse = last_verse.get(chat_id)
    verse_ref = extract_verse_ref(verse)

    if not verse_ref:
        bot.send_message(chat_id, "Сначала выбери стих через 📖 Стих дня или 📚 По теме.")
        return

    if add_favorite(chat_id, verse_ref):
        bot.send_message(chat_id, f"⭐ Добавлено в избранное: <b>{verse_ref}</b>", parse_mode='HTML')
    else:
        bot.send_message(chat_id, f"ℹ️ Уже в избранном: <b>{verse_ref}</b>", parse_mode='HTML')


@bot.message_handler(commands=['myfavorites'])
def myfavorites_command(message):
    send_favorites_list(message.chat.id)


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    text = message.text.strip()

    logger.info(f"Сообщение: '{text[:50]}'")

    if text == "📖 Стих дня":
        verse = get_random_verse()
        last_verse[chat_id] = verse

        bot.send_message(
            chat_id,
            f"📖 <b>Стих дня:</b>\n\n{verse}",
            parse_mode='HTML',
            reply_markup=get_verse_actions_keyboard()
        )
        return

    if text == "📚 По теме":
        if not VERSE_THEMES:
            bot.send_message(chat_id, "⚠️ Темы пока не настроены в bible_data.py", reply_markup=get_main_keyboard())
            return

        bot.send_message(
            chat_id,
            "📚 <b>Выбери тему:</b>",
            parse_mode='HTML',
            reply_markup=get_theme_keyboard()
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

    on_cooldown, remaining = is_on_cooldown(chat_id)
    if on_cooldown:
        bot.send_message(
            chat_id,
            f"⏳ Подожди {remaining} сек. перед следующим разбором.",
            reply_markup=get_main_keyboard()
        )
        return

    mark_request(chat_id)
    threading.Thread(target=parse_in_background, args=(chat_id, text), daemon=True).start()


@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)

    if call.data == "new":
        verse = get_random_verse()
        last_verse[chat_id] = verse

        try:
            bot.edit_message_text(
                f"📖 <b>Стих дня:</b>\n\n{verse}",
                chat_id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=get_verse_actions_keyboard()
            )
        except Exception as e:
            logger.error(f"Ошибка edit: {e}")

    elif call.data == "fav_save":
        verse = last_verse.get(chat_id)
        verse_ref = extract_verse_ref(verse)

        if not verse_ref:
            bot.send_message(chat_id, "❌ Не удалось определить стих для сохранения.")
            return

        if add_favorite(chat_id, verse_ref):
            bot.send_message(chat_id, f"⭐ Стих сохранён: <b>{verse_ref}</b>", parse_mode='HTML')
        else:
            bot.send_message(chat_id, f"ℹ️ Уже в избранном: <b>{verse_ref}</b>", parse_mode='HTML')

    elif call.data == "choose_theme":
        if not VERSE_THEMES:
            bot.send_message(chat_id, "⚠️ Темы пока не настроены в bible_data.py", reply_markup=get_main_keyboard())
            return
        bot.send_message(
            chat_id,
            "📚 <b>Выбери тему:</b>",
            parse_mode='HTML',
            reply_markup=get_theme_keyboard()
        )

    elif call.data.startswith("theme:"):
        try:
            idx = int(call.data.split(":", 1)[1]) - 1
        except ValueError:
            bot.send_message(chat_id, "❌ Не удалось определить тему")
            return

        theme_name = get_theme_name_by_idx(idx)
        if not theme_name:
            bot.send_message(chat_id, "❌ Тема не найдена")
            return

        verse = get_random_verse_from_theme(theme_name)
        if not verse:
            bot.send_message(chat_id, f"⚠️ В теме «{theme_name}» нет валидных стихов", reply_markup=get_main_keyboard())
            return

        last_verse[chat_id] = verse
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🔍 Разобрать", callback_data="parse"))
        markup.row(types.InlineKeyboardButton("⭐ Сохранить стих", callback_data="fav_save"))
        markup.row(types.InlineKeyboardButton("🎲 Ещё стих", callback_data=f"theme:{idx + 1}"))
        markup.row(types.InlineKeyboardButton("📚 Выбрать тему", callback_data="choose_theme"))

        bot.send_message(
            chat_id,
            f"📚 <b>{theme_name}</b>\n\n{verse}",
            parse_mode='HTML',
            reply_markup=markup
        )

    elif call.data == "parse":
        if chat_id in last_verse:
            on_cooldown, remaining = is_on_cooldown(chat_id)
            if on_cooldown:
                bot.send_message(
                    chat_id,
                    f"⏳ Подожди {remaining} сек. перед следующим разбором.",
                    reply_markup=get_main_keyboard()
                )
                return

            mark_request(chat_id)
            threading.Thread(target=parse_in_background, args=(chat_id, last_verse[chat_id]), daemon=True).start()
        else:
            bot.send_message(chat_id, "❌ Стих не найден. Нажми <b>📖 Стих дня</b>", parse_mode='HTML')

    elif call.data.startswith("fav_parse:"):
        try:
            idx = int(call.data.split(":", 1)[1]) - 1
        except ValueError:
            bot.send_message(chat_id, "❌ Неверный номер избранного стиха.")
            return

        favorites = get_favorites(chat_id)
        if idx < 0 or idx >= len(favorites):
            bot.send_message(chat_id, "❌ Избранный стих не найден.")
            return

        verse_ref = favorites[idx]
        verse_text = POPULAR_VERSES.get(verse_ref)
        if not verse_text:
            bot.send_message(chat_id, f"⚠️ В базе нет текста для <b>{verse_ref}</b>.", parse_mode='HTML')
            return

        last_verse[chat_id] = f"{verse_ref}\n\n{verse_text}"
        on_cooldown, remaining = is_on_cooldown(chat_id)
        if on_cooldown:
            bot.send_message(chat_id, f"⏳ Подожди {remaining} сек. перед следующим разбором.")
            return

        mark_request(chat_id)
        threading.Thread(target=parse_in_background, args=(chat_id, last_verse[chat_id]), daemon=True).start()

    elif call.data.startswith("fav_del:"):
        try:
            idx = int(call.data.split(":", 1)[1]) - 1
        except ValueError:
            bot.send_message(chat_id, "❌ Неверный номер избранного стиха.")
            return

        favorites = get_favorites(chat_id)
        if idx < 0 or idx >= len(favorites):
            bot.send_message(chat_id, "❌ Избранный стих не найден.")
            return

        verse_ref = favorites[idx]
        removed = remove_favorite(chat_id, verse_ref)
        if removed:
            bot.send_message(chat_id, f"🗑 Удалено из избранного: <b>{verse_ref}</b>", parse_mode='HTML')
        else:
            bot.send_message(chat_id, "ℹ️ Этот стих уже удалён.")

        send_favorites_list(chat_id)


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
    logger.info(f"📚 База: {len(POPULAR_VERSES)} стихов | Тем: {len(VERSE_THEMES)}")

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
