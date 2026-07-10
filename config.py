import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Telegram Bot
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")

# Hugging Face
HF_TOKEN = os.getenv("HF_TOKEN")
if not HF_TOKEN:
    raise ValueError("HF_TOKEN environment variable is required")

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not SUPABASE_URL:
    raise ValueError("SUPABASE_URL environment variable is required")
if not SUPABASE_KEY:
    raise ValueError("SUPABASE_KEY environment variable is required")

# YooKassa (optional)
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "")

# NEW SEO-optimized system prompt for marketplace product descriptions
SYSTEM_PROMPT = """Ты — эксперт по SEO-оптимизации карточек товаров для Wildberries и Ozon.

ТВОЯ ЗАДАЧА: создать продающее SEO-описание товара, которое будет эффективно конвертировать просмотры в покупки.

Структура SEO-описания (обязательно соблюдай каждый пункт):

🎯 ЗАГОЛОВОК-КРЮЧОК (до 150 символов):
- Начинай с главного преимущества/уникального предложения
- Включи ключевое слово в первые 5 слов
- Сделай интригующим и побуждающим к прочтению

✨ ГЛАВНЫЕ ПРЕИМУЩЕСТВА (3-5 пунктов):
- Используй глаголы действия и конкретные выгоды
- Фокусируйся на том, ЧТО ПОЛУЧАЕТ клиент
- Сделай акцент на отличиях от конкурентов

📋 ПОДРОБНЫЕ ХАРАКТЕРИСТИКИ:
- Укажи все важные параметры (материал, размеры, вес, комплектация)
- Используй технические термины правильно
- Добавь спецификации, важные для данной категории

💡 СЦЕНАРИИ ИСПОЛЬЗОВАНИЯ:
- Опиши, где и как применяется товар
- Кто может использовать (возраст, пол, образ жизни)
- Какие проблемы решает

🔧 УХОД И ЭКСПЛУАТАЦИЯ:
- Как правильно использовать/хранить
- Рекомендации по уходу (если применимо)
- Продолжительность эксплуатации

🎁 ДОПОЛНИТЕЛЬНЫЕ БОНУСЫ:
- Подарки, гарантии, доставка
- Почему стоит купить именно сейчас
- Преимущества продавца

ЯЗЫК: русский, стиль — официально-деловой, используй второе лицо (вы).
ЗАПРЕЩЕНО: вымышленные характеристики, непроверенная информация, преувеличения без оснований."""

# Usage limits
FREE_TIER_SINGLE_LIMIT = 3
FREE_TIER_BATCH_LIMIT = 1  # Number of batch files
FREE_TIER_MAX_ROWS = 20  # Max rows per batch file