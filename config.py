import os
from dotenv import load_dotenv

load_dotenv()

TG_TOKEN = os.getenv("TG_TOKEN")
NEURO_KEY = os.getenv("NEURO_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

if not TG_TOKEN:
    raise ValueError("Критическая ошибка: TG_TOKEN не найден!")
if not NEURO_KEY:
    raise ValueError("Критическая ошибка: NEURO_KEY не найден!")

BOT_NAME = "Bible Bot v2.0"
SYSTEM_PROMPT = """Ты — христианский библейский бот-помощник. Отвечай тепло, библейски точно и структурированно."""
COOLDOWN_SECONDS = 5
