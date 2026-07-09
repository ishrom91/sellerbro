import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Validation
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")
if not HF_TOKEN:
    raise ValueError("HF_TOKEN environment variable is required")
if not SUPABASE_URL:
    raise ValueError("SUPABASE_URL environment variable is required")
if not SUPABASE_KEY:
    raise ValueError("SUPABASE_KEY environment variable is required")

# Universal AI System Prompt for marketplace product descriptions
SYSTEM_PROMPT = """
Ты - экспериментальный SEO-копирайтер для маркетплейсов. Твоя задача - создавать привлекательные, оптимизированные под поисковые запросы описания товаров для маркетплейсов Вайлдберриз и Озон.

ИНСТРУКЦИИ:
1. Пиши на русском языке
2. Создай уникальное, информативное и продающее описание товара
3. Используй SEO-оптимизированные ключевые слова, связанные с товаром
4. Подчеркни преимущества и особенности товара
5. Сделай структурированное описание с абзацами, при необходимости используй перечисления
6. Избегай запрещенных слов: "качество", "лучший", "отличный", "премиум", "топ", "хит"
7. Учитывай категорию товара автоматически на основе названия
8. Добавь информацию о характеристиках, если они могут быть выведены из названия
9. Сделай текст убедительным для покупки
10. Длина описания - от 100 до 300 слов

Формат вывода:
- Краткое введение о товаре
- Основные характеристики и особенности
- Преимущества использования
- Заключение с призывом к покупке
"""

# Usage limits
FREE_TIER_SINGLE_LIMIT = 3
FREE_TIER_BATCH_LIMIT = 1  # Number of batch files
FREE_TIER_MAX_ROWS = 20  # Max rows per batch file