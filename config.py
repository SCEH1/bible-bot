import os
from dotenv import load_dotenv

load_dotenv()

TG_TOKEN = os.getenv("TG_TOKEN")
NEURO_KEY = os.getenv("NEURO_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

if not TG_TOKEN:
    raise ValueError("❌ Ошибка: TG_TOKEN не найден в переменных окружения!")
if not NEURO_KEY:
    raise ValueError("❌ Ошибка: NEURO_KEY не найден в переменных окружения!")

BOT_NAME = "Bible Bot v2.0"
SYSTEM_PROMPT = """Ты — христианский библейский бот-помощник. Отвечай тепло, библейски точно и структурированно."""
