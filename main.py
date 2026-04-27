import logging
import asyncio
import signal
import sys
import time
from collections import OrderedDict
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from config import TG_TOKEN, NEURO_KEY, WEBHOOK_URL, SYSTEM_PROMPT, COOLDOWN_SECONDS, MAX_MESSAGE_LENGTH
from bible_data import BIBLE_VERSES, get_verse_by_ref, get_verses_by_topic
from storage import add_favorite, get_favorites, remove_favorite

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ---
bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# Простой LRU-кэш для ответов API (экономия токенов)
# Формат: { "запрос": {"ответ": "...", "время": timestamp} }
CACHE = OrderedDict()
CACHE_MAX_SIZE = 100
CACHE_TTL = 3600 * 24  # 24 часа

# Отслеживание кулдауна пользователей
user_cooldowns = {}

# Флаг для корректной остановки
shutdown_event = asyncio.Event()

# --- УТИЛИТЫ ---

def clean_cache():
    """Очистка старого кэша"""
    now = time.time()
    keys_to_delete = []
    for key, val in CACHE.items():
        if now - val['time'] > CACHE_TTL:
            keys_to_delete.append(key)
    
    for key in keys_to_delete:
        del CACHE[key]

def get_cached_response(prompt: str) -> str | None:
    clean_cache()
    if prompt in CACHE:
        logger.info(f"Найден ответ в кэше для: {prompt[:20]}...")
        return CACHE[prompt]['response']
    return None

def save_to_cache(prompt: str, response: str):
    clean_cache()
    if len(CACHE) >= CACHE_MAX_SIZE:
        CACHE.popitem(last=False) # Удаляем самый старый
    CACHE[prompt] = {'response': response, 'time': time.time()}

async def send_long_message(message: types.Message, text: str):
    """Разбивка длинного сообщения на части, если оно превышает лимит Telegram"""
    if len(text) <= MAX_MESSAGE_LENGTH:
        await message.answer(text, parse_mode="Markdown")
        return
    
    parts = []
    current_part = ""
    lines = text.split('\n')
    
    for line in lines:
        if len(current_part) + len(line) + 1 > MAX_MESSAGE_LENGTH:
            parts.append(current_part)
            current_part = line
        else:
            current_part += ("\n" if current_part else "") + line
    
    if current_part:
        parts.append(current_part)
    
    for i, part in enumerate(parts):
        await message.answer(part, parse_mode="Markdown")
        if i < len(parts) - 1:
            await asyncio.sleep(0.5) # Небольшая пауза между частями

async def call_neuro_api(prompt: str) -> str:
    """Вызов внешнего AI API (заглушка для примера структуры)"""
    # В реальном проекте здесь будет запрос к вашему AI сервису
    # Используем фиктивную задержку для имитации работы
    await asyncio.sleep(1.5) 
    
    # Для демонстрации возвращаем эхо-ответ, если нет реального эндпоинта
    # ЗАМЕНИТЕ ЭТОТ БЛОК НА РЕАЛЬНЫЙ REQUESTS/AIOHTTP ЗАПРОС
    response_text = f"🤖 *AI Разбор (Демо)*\n\nВы спросили: \"{prompt}\"\n\nЗдесь должен быть ответ от нейросети с ключом {NEURO_KEY[:4]}...\n\n*(В реальной версии здесь будет интеграция с вашим API)*"
    return response_text

# --- ОБРАБОТЧИКИ КОМАНД ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📖 Случайный стих"), KeyboardButton(text="❤️ Избранное")],
        [KeyboardButton(text="🔍 Поиск по теме")]
    ], resize_keyboard=True)
    await message.answer(
        f"👋 Привет! Я {BOT_NAME}.\n\n"
        "Я помогу тебе найти утешение и мудрость в Библии.\n\n"
        "Что я умею:\n"
        "/random — случайный стих\n"
        "/topic <тема> — стихи по теме (страх, радость, любовь...)\n"
        "/ask <вопрос> — глубокий разбор вопроса через AI\n"
        "/fav — мое избранное",
        reply_markup=kb
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "📚 *Команды бота:*\n\n"
        "/start - Главное меню\n"
        "/random - Случайный стих утешения\n"
        "/ask <текст> - Задать вопрос и получить развернутый библейский ответ от AI\n"
        "/topic <тема> - Найти стихи по теме (например: страх, надежда)\n"
        "/fav - Посмотреть сохраненные стихи\n"
        "/del <ссылка> - Удалить стих из избранного"
    )

@dp.message(Command("random"))
async def cmd_random(message: types.Message):
    import random
    verse = random.choice(BIBLE_VERSES)
    text = f"📖 *{verse['ref']}*\n_{verse['text']}_"
    
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="💾 Сохранить в избранное")]
    ], resize_keyboard=True)
    # Сохраняем контекст для кнопки (в реальном боте лучше использовать callback_data)
    # Здесь упрощенно: пользователь должен написать /save <ссылка> или использовать инлайн
    await message.answer(text, parse_mode="Markdown", reply_markup=kb)

@dp.message(Command("ask"))
async def cmd_ask(message: types.Message):
    user_id = message.from_user.id
    now = time.time()
    
    # Проверка кулдауна
    if user_id in user_cooldowns:
        last_time = user_cooldowns[user_id]
        if now - last_time < COOLDOWN_SECONDS:
            wait_time = int(COOLDOWN_SECONDS - (now - last_time))
            await message.answer(f"⏳ Пожалуйста, подождите {wait_time} сек. перед следующим вопросом.")
            return
    
    user_cooldowns[user_id] = now
    
    # Получаем текст вопроса (после команды /ask)
    question = message.text.split(maxsplit=1)
    if len(question) < 2:
        await message.answer("❌ Пожалуйста, напишите вопрос после команды.\nПример: `/ask Почему Бог допускает страдания?`")
        return
    
    query_text = " ".join(question[1:])
    prompt = f"{SYSTEM_PROMPT}\n\nВопрос пользователя: {query_text}"
    
    # Проверка кэша
    cached = get_cached_response(prompt)
    if cached:
        await send_long_message(message, cached)
        return

    # Индикатор загрузки
    status_msg = await message.answer("🤖 Думаю и ищу в Писании...")
    
    try:
        # Вызов AI (асинхронно)
        answer = await call_neuro_api(query_text)
        
        # Сохранение в кэш
        save_to_cache(prompt, answer)
        
        await status_msg.delete()
        await send_long_message(message, answer)
        
    except Exception as e:
        logger.error(f"Ошибка AI API: {e}")
        await status_msg.edit_text("❌ Произошла ошибка при получении ответа. Попробуйте позже.")

@dp.message(Command("fav"))
async def cmd_fav(message: types.Message):
    user_id = message.from_user.id
    favs = get_favorites(user_id)
    
    if not favs:
        await message.answer("📭 Ваше избранное пока пусто.")
        return
    
    response = "❤️ *Ваше избранное:*\n\n"
    for i, item in enumerate(favs, 1):
        response += f"{i}. *{item['reference']}*\n_{item['text']}_\n\n"
        if len(response) > MAX_MESSAGE_LENGTH - 100:
            response += "... (сообщение обрезано)"
            break
            
    await send_long_message(message, response)

@dp.message(Command("save"))
async def cmd_save(message: types.Message):
    # Упрощенная логика сохранения: /save Ин 3:16
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: `/save <Ссылка>` (например: `/save Ин 3:16`)")
        return
    
    ref = args[1]
    verse = get_verse_by_ref(ref)
    
    if not verse:
        await message.answer(f"❌ Стих `{ref}` не найден в базе. Попробуйте другой формат.")
        return
    
    user_id = message.from_user.id
    if add_favorite(user_id, verse['text'], verse['ref']):
        await message.answer(f"✅ Стих *{verse['ref']}* сохранен в избранное!", parse_mode="Markdown")
    else:
        await message.answer("ℹ️ Этот стих уже есть в вашем избранном.")

@dp.message(Command("del"))
async def cmd_del(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: `/del <Ссылка>`")
        return
    
    ref = args[1]
    user_id = message.from_user.id
    
    if remove_favorite(user_id, ref):
        await message.answer(f"🗑 Стих *{ref}* удален из избранного.", parse_mode="Markdown")
    else:
        await message.answer("❌ Стих не найден в вашем избранном.")

# --- ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ (КНОПКИ) ---

@dp.message()
async def handle_text(message: types.Message):
    text = message.text.strip()
    
    if text == "📖 Случайный стих":
        await cmd_random(message)
    elif text == "❤️ Избранное":
        await cmd_fav(message)
    elif text == "💾 Сохранить в избранное":
        # В реальном боте нужно передавать контекст предыдущего сообщения
        # Здесь заглушка
        await message.answer("ℹ️ Чтобы сохранить стих, используйте команду `/save <Ссылка>`")
    elif text == "🔍 Поиск по теме":
        await message.answer("Напишите тему (например: *страх*, *радость*, *любовь*), и я найду подходящие стихи.", parse_mode="Markdown")
    else:
        # Если пользователь просто пишет текст, предлагаем задать вопрос через /ask
        await message.answer(
            f"Я вижу ваше сообщение: \"{text[:50]}...\"\n\n"
            "Хотите получить библейский разбор этой темы? Используйте команду:\n"
            f"`/ask {text}`",
            parse_mode="Markdown"
        )

# --- ЗАПУСК И ОСТАНОВКА ---

async def on_startup():
    logger.info("Бот запускается...")
    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook установлен на: {WEBHOOK_URL}")
    else:
        logger.info("Webhook URL не задан. Запуск в режиме Polling.")

async def on_shutdown():
    logger.info("Бот останавливается...")
    await bot.delete_webhook()
    await bot.session.close()

def register_signals():
    """Регистрация обработчиков сигналов для корректного завершения"""
    loop = asyncio.get_running_loop()
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda: asyncio.create_task(shutdown_procedure())
        )

async def shutdown_procedure():
    logger.info("Получен сигнал завершения. Остановка...")
    shutdown_event.set()
    await on_shutdown()
    # Завершаем все задачи
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("Все задачи завершены. Выход.")
    sys.exit(0)

async def main():
    await on_startup()
    register_signals()
    
    try:
        if WEBHOOK_URL:
            # Режим Webhook (для Render/Heroku)
            await dp.start_webhook_listen(
                host="0.0.0.0",
                port=int(os.getenv("PORT", 8000)),
                path="/webhook",
                bot=bot,
                allowed_updates=dp.resolve_used_update_types(),
            )
        else:
            # Режим Polling (для локальной разработки)
            logger.info("Запуск в режиме Polling...")
            await dp.start_polling(bot)
    except asyncio.CancelledError:
        pass # Ожидаемое поведение при остановке
    finally:
        await on_shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
