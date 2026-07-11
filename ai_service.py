import asyncio
import logging
import tempfile
import os
import json
import base64
import aiohttp
from pathlib import Path
from config import SYSTEM_PROMPT

# Models
MODELS = [
    "openrouter/free",  # Автоматический выбор бесплатной модели от OpenRouter
]

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def analyze_product_photo(image_path: str) -> dict:
    """Analyze product photo using Qwen2.5-VL vision model.
    Returns dict with real characteristics visible in the photo.
    """
    # Read image and encode as base64
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    image_base64 = base64.b64encode(image_bytes).decode('utf-8')
    
    image_data_url = f"data:image/jpeg;base64,{image_base64}"
    
    vision_prompt = """Ты — эксперт по товарам для маркетплейсов. Проанализируй это фото товара и опиши ТОЛЬКО то, что реально видно на изображении.

ВАЖНО:
- Описывай ТОЛЬКО видимые характеристики
- НЕ придумывай то, чего не видно (размеры, бренд, точный состав)
- Будь максимально точным и объективным

Верни ответ в формате JSON с такими полями:
{
  "product_type": "тип товара (например: платье, сумка, кроссовки)",
  "material_visible": "видимый материал (например: хлопок, кожа, полиэстер - только если видно)",
  "colors": ["список видимых цветов"],
  "design_elements": ["видимые элементы дизайна: рукава, карманы, застёжки, принт и т.д."],
  "style": "стиль товара (классический, спортивный, casual и т.д.)",
  "target_audience": "для кого (мужское/женское/детское)",
  "visible_features": ["другие видимые особенности"],
  "condition": "состояние товара на фото (новое, в упаковке и т.д.)"
}

Отвечай ТОЛЬКО JSON, без дополнительного текста."""

    # Using OpenRouter API for vision model
    from config import OPENROUTER_API_KEY
    
    OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://your-bot-url.com",  # Optional
        "X-Title": "AI SellerBro Bot"  # Optional
    }
    
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_data_url}},
                {"type": "text", "text": vision_prompt}
            ]
        }
    ]
    
    payload = {
        "model": "openrouter/free",  # Using automatic router
        "messages": messages,
        "max_tokens": 1000,
        "temperature": 0.3  # Low temperature for accurate analysis
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(OPENROUTER_API_URL, headers=headers, json=payload) as response:
            if response.status == 200:
                data = await response.json()
                raw_text = data["choices"][0]["message"]["content"].strip()
                
                # Try to parse JSON
                try:
                    # Try to extract JSON if wrapped in markdown
                    if "```" in raw_text:
                        raw_text = raw_text.split("```")[1]
                        if raw_text.startswith("json"):
                            raw_text = raw_text[4:]
                    analysis = json.loads(raw_text)
                    logger.info(f"Vision analysis: {analysis}")
                    return analysis
                except json.JSONDecodeError:
                    logger.warning(f"Could not parse JSON, using raw text: {raw_text}")
                    return {"raw_analysis": raw_text}
            else:
                error_text = await response.text()
                logger.error(f"Vision analysis error: {response.status} - {error_text}")
                return {}


async def generate_description_from_photo(image_path: str, user_notes: str = "") -> str:
    """Generate SEO description based on actual product photo analysis.
    Uses vision model to analyze photo, then creates SEO text based on real visible characteristics.
    """
    import json
    
    # Step 1: Analyze the photo with vision model
    photo_analysis = await analyze_product_photo(image_path)
    
    if not photo_analysis:
        raise Exception("Не удалось проанализировать фото")
    
    # Step 2: Create SEO description based on REAL characteristics
    from config import OPENROUTER_API_KEY
    
    analysis_text = json.dumps(photo_analysis, ensure_ascii=False, indent=2) if photo_analysis else "Нет данных"
    
    seo_system_prompt = f"""Ты — эксперт по SEO-оптимизации карточек товаров для Wildberries и Ozon.

ВАЖНО: Тебе дан реальный анализ товара на основе фото. Используй ТОЛЬКО эти характеристики!
НЕ ПРИДУМЫВАЙ ничего, чего нет в анализе (размеры, точные материалы, бренд, цену).

Если характеристики не указаны в анализе — оставь места для заполнения продавцом.

Анализ товара на основе фото:
{analysis_text}

{"Дополнительная информация от продавца: " + user_notes if user_notes else "Дополнительной информации нет."}

ТВОЯ ЗАДАЧА:
1. Создать продающее SEO-описание (800-1500 символов)
2. Использовать ТОЛЬКО характеристики из анализа
3. Добавить места для заполнения: [укажите размер], [укажите бренд], [укажите цену]
4. Использовать структуру с эмодзи как раньше (крючок, преимущества, характеристики, уход, бонусы)
5. Включить SEO-ключевые слова естественно

СТРОГО ЗАПРЕЩЕНО:
- Придумывать размеры, которых нет в анализе
- Придумывать точный состав материала, если он не виден на фото
- Указывать бренд, если он не виден на фото или не указан продавцом
- Придумывать несуществующие функции"""
    
    OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://your-bot-url.com",  # Optional
        "X-Title": "AI SellerBro Bot"  # Optional
    }
    
    messages = [
        {"role": "system", "content": seo_system_prompt},
        {"role": "user", "content": "Создай SEO-описание для этого товара на основе анализа фото"}
    ]
    
    payload = {
        "model": "openrouter/free",  # Using automatic router
        "messages": messages,
        "max_tokens": 800,
        "temperature": 0.7
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(OPENROUTER_API_URL, headers=headers, json=payload) as response:
            if response.status == 200:
                data = await response.json()
                description = data["choices"][0]["message"]["content"].strip()
                logger.info(f"Generated photo-based description: {description[:100]}...")
                return description
            else:
                error_text = await response.text()
                raise Exception(f"Photo description generation error: {response.status} - {error_text}")


async def generate_description(product_name: str) -> str:
    """
    Генерирует описание товара через OpenRouter API
    """
    from config import OPENROUTER_API_KEY
    
    OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://your-bot-url.com",  # Опционально
        "X-Title": "AI SellerBro Bot"  # Опционально
    }
    
    payload = {
        "model": "openrouter/free",  # Используем автоматический роутер
        "messages": [
            {
                "role": "system",
                "content": "Ты - профессиональный копирайтер для маркетплейсов. Создавай привлекательные описания товаров."
            },
            {
                "role": "user",
                "content": f"Создай привлекательное описание для товара: {product_name}"
            }
        ],
        "temperature": 0.7,
        "max_tokens": 500
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(OPENROUTER_API_URL, headers=headers, json=payload) as response:
            if response.status == 200:
                data = await response.json()
                return data["choices"][0]["message"]["content"]
            else:
                error_text = await response.text()
                raise Exception(f"OpenRouter API error: {response.status} - {error_text}")


async def generate_batch_descriptions(products: list[str]) -> list[str]:
    """Generate descriptions for a batch of products"""
    descriptions = []
    
    for i, product in enumerate(products):
        try:
            logger.info(f"Processing item {i+1}/{len(products)}: {product[:30]}...")
            description = await generate_description(product)
            descriptions.append(description)
            
            # Add delay between API calls to avoid rate limits
            if i < len(products) - 1:  # Don't sleep after the last item
                logger.debug("Waiting 5 seconds between API calls to respect rate limits...")
                await asyncio.sleep(5)
                
        except Exception as e:
            logger.error(f"Error generating description for product '{product}': {str(e)}")
            # Add an error message placeholder for failed items
            descriptions.append(f"Ошибка генерации описания: {str(e)}")
    
    logger.info(f"Completed batch processing. Generated {len(descriptions)} descriptions.")
    return descriptions