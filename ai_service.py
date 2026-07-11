import asyncio
import logging
import tempfile
import os
import json
import base64
from pathlib import Path
from openai import OpenAI
from config import OPENROUTER_API_KEY, AI_MODEL, VISION_MODEL, SYSTEM_PROMPT, FALLBACK_MODELS

# Initialize OpenRouter client
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

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
    
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_data_url}},
                {"type": "text", "text": vision_prompt}
            ]
        }
    ]
    
    try:
        # Try the larger vision model first, fall back to smaller one if unavailable
        try:
            response = client.chat_completion(
                messages=messages,
                model="Qwen/Qwen2.5-VL-72B-Instruct",
                max_tokens=1000,
                temperature=0.3  # Low temperature for accurate analysis
            )
        except Exception as e:
            logger.warning(f"Larger vision model not available: {str(e)}. Trying smaller model.")
            # Fallback to a smaller vision model
            response = client.chat_completion(
                messages=messages,
                model="Qwen/Qwen2-VL-7B-Instruct",
                max_tokens=1000,
                temperature=0.3  # Low temperature for accurate analysis
            )
        
        if response and response.choices:
            raw_text = response.choices[0].message.content.strip()
            # Try to parse JSON
            try:
                # Try to extract JSON if wrapped in code
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
        
        return {}
        
    except Exception as e:
        logger.error(f"Error in vision analysis: {str(e)}")
        return {}


async def generate_description(product_name: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Создай SEO-описание для товара: {product_name}"}
    ]
    
    # Try main model first, then fallbacks
    models_to_try = [AI_MODEL] + FALLBACK_MODELS
    
    for model_name in models_to_try:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=1000,
                temperature=0.7,
            )
            
            if response and response.choices and len(response.choices) > 0:
                description = response.choices[0].message.content.strip()
                logger.info(f"Successfully generated with model: {model_name}")
                return description
        except Exception as e:
            logger.warning(f"Model {model_name} failed: {str(e)[:100]}, trying next...")
            await asyncio.sleep(2)
            continue
    
    raise Exception("All models failed. Please try again later.")


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
    client = InferenceClient(token=HF_TOKEN)
    
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
    
    messages = [
        {"role": "system", "content": seo_system_prompt},
        {"role": "user", "content": "Создай SEO-описание для этого товара на основе анализа фото"}
    ]
    
    # Try main model first, then fallbacks
    models_to_try = ["Qwen/Qwen2.5-7B-Instruct", "Qwen/Qwen2-VL-7B-Instruct", "microsoft/DialoGPT-medium"]
    
    for model_name in models_to_try:
        try:
            response = client.chat_completion(
                messages=messages,
                model=model_name,
                max_tokens=800,
                temperature=0.7
            )
            
            if response and response.choices:
                description = response.choices[0].message.content.strip()
                logger.info(f"Successfully generated photo description with model: {model_name}")
                return description
        except Exception as e:
            logger.warning(f"Photo model {model_name} failed: {str(e)[:100]}, trying next...")
            await asyncio.sleep(2)
            continue
    
    raise Exception("All photo models failed. Please try again later.")


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