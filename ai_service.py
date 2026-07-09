import asyncio
import logging
import tempfile
import os
import json
import base64
from pathlib import Path
from huggingface_hub import InferenceClient
from config import HF_TOKEN, SYSTEM_PROMPT

# Import image processing libraries
from PIL import Image, ImageDraw, ImageFont
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def analyze_product_photo(image_path: str) -> dict:
    """Analyze product photo using Qwen2.5-VL vision model.
    Returns dict with real characteristics visible in the photo.
    """
    client = InferenceClient(token=HF_TOKEN)
    
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
        
        return {}
        
    except Exception as e:
        logger.error(f"Error in vision analysis: {str(e)}")
        return {}


async def generate_description_from_photo(image_path: str, user_notes: str = "") -> str:
    """Generate SEO description based on actual product photo.
    Only uses real characteristics visible in the photo.
    """
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
    
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            response = client.chat_completion(
                messages=messages,
                model="Qwen/Qwen2.5-7B-Instruct",
                max_tokens=800,
                temperature=0.7
            )
            
            if response and response.choices:
                description = response.choices[0].message.content.strip()
                logger.info(f"Generated photo-based description: {description[:100]}...")
                return description
            
        except Exception as e:
            logger.error(f"Error (attempt {attempt + 1}): {str(e)}")
            if attempt == max_retries:
                raise
    
    raise Exception("Failed to generate description")


async def generate_description(product_name: str) -> str:
    client = InferenceClient(token=HF_TOKEN)
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": product_name}
    ]
    
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            response = client.chat_completion(
                messages=messages,
                model="Qwen/Qwen2.5-7B-Instruct",
                max_tokens=500,
                temperature=0.7,
                top_p=0.9
            )
            
            if response and response.choices and len(response.choices) > 0:
                description = response.choices[0].message.content
                logger.info(f"Successfully generated description for: {product_name[:50]}...")
                return description.strip()
            else:
                raise Exception("Empty response from API")
        
        except Exception as e:
            logger.error(f"Error during HF API call (attempt {attempt + 1}): {str(e)}")
            if "Model is currently loading" in str(e) or "Model is loading" in str(e):
                await asyncio.sleep(20)
                continue
            elif "Rate limit" in str(e) or "Too many requests" in str(e) or "429" in str(e):
                await asyncio.sleep(10)
                continue
            elif attempt == max_retries:
                raise Exception(f"Failed to get response from HF API after {max_retries + 1} attempts: {str(e)}")
    
    raise Exception("Max retries exceeded without successful response")


async def generate_product_image(product_name: str, base_image_path: str = None) -> str:
    """
    Generate a product image using Hugging Face's image models.
    
    Args:
        product_name: Description of the product to generate an image for
        base_image_path: Optional path to a base image for img2img transformation
    
    Returns:
        Path to the generated image file
    """
    client = InferenceClient(token=HF_TOKEN)
    
    # Create a descriptive prompt for image generation
    prompt = f"professional product photography of {product_name}, high quality, studio lighting, white background, e-commerce product shot, detailed"
    
    try:
        # Create a temporary file to save the generated image
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
            temp_filename = temp_file.name
        
        if base_image_path and os.path.exists(base_image_path):
            # Use image-to-image transformation if base image is provided
            # Note: Not all models support img2img, so we'll use text-to-image as fallback
            try:
                # First try image-to-image if the model supports it
                response = client.image_to_image(
                    prompt=prompt,
                    image=open(base_image_path, "rb"),
                    model="stabilityai/stable-diffusion-xl-refiner-1.0",
                    negative_prompt="blurry, low quality, distorted, deformed",
                    num_inference_steps=20
                )
            except Exception as e_img2img:
                logger.warning(f"Image-to-image failed: {str(e_img2img)}, falling back to text-to-image")
                # Fallback to text-to-image generation
                response = client.text_to_image(
                    prompt=prompt,
                    model="stabilityai/stable-diffusion-xl-base-1.0",
                    negative_prompt="blurry, low quality, distorted, deformed",
                    width=512,
                    height=512,
                    num_inference_steps=20
                )
        else:
            # Use text-to-image generation
            response = client.text_to_image(
                prompt=prompt,
                model="stabilityai/stable-diffusion-xl-base-1.0",
                negative_prompt="blurry, low quality, distorted, deformed",
                width=512,
                height=512,
                num_inference_steps=20
            )
        
        # Save the generated image to the temporary file
        response.save(temp_filename)
        
        logger.info(f"Successfully generated product image for: {product_name[:50]}...")
        return temp_filename
        
    except Exception as e:
        logger.error(f"Error generating product image for {product_name}: {str(e)}")
        # Create a placeholder image if generation fails
        return create_placeholder_image(product_name)


def create_placeholder_image(product_name: str) -> str:
    """
    Create a placeholder image when image generation fails.
    
    Args:
        product_name: Name of the product for the placeholder
    
    Returns:
        Path to the placeholder image file
    """
    # Create a simple placeholder image
    width, height = 512, 512
    image = Image.new('RGB', (width, height), color='lightblue')
    draw = ImageDraw.Draw(image)
    
    # Draw some basic elements
    draw.rectangle([50, 50, width-50, height-50], outline='white', width=5)
    
    # Try to use a default font, or fallback to default
    try:
        # Attempt to use a basic font
        font_size = 24
        # Use default font as PIL doesn't require external fonts
        font = ImageFont.load_default()
    except:
        font = ImageFont.load_default()
    
    # Add product name text
    bbox = draw.textbbox((0, 0), product_name[:50], font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    x = (width - text_width) // 2
    y = (height - text_height) // 2
    
    draw.text((x, y), product_name[:50], fill='white', font=font)
    
    # Create a temporary file for the placeholder
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
        image.save(temp_file.name, "PNG")
        return temp_file.name


def process_product_image(photo_path: str, product_name: str) -> str:
    """
    Process a product image: remove background, enhance, add text if needed.
    
    Args:
        photo_path: Path to the input photo
        product_name: Product name to potentially add to the image
    
    Returns:
        Path to the processed image file
    """
    try:
        # Open the image
        image = Image.open(photo_path)
        
        # Convert to RGB if necessary (for PNG with transparency)
        if image.mode in ('RGBA', 'LA', 'P'):
            image = image.convert('RGB')
        
        # Resize image to standard size while maintaining aspect ratio
        max_size = (800, 800)
        image.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Create a temporary file for the processed image
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
            processed_path = temp_file.name
        
        # Save the processed image
        image.save(processed_path, "JPEG", quality=95, optimize=True)
        
        logger.info(f"Successfully processed product image: {photo_path}")
        return processed_path
        
    except Exception as e:
        logger.error(f"Error processing product image {photo_path}: {str(e)}")
        # Return the original image if processing fails
        return photo_path


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
                logger.debug("Waiting 2 seconds between API calls to respect rate limits...")
                await asyncio.sleep(2)
                
        except Exception as e:
            logger.error(f"Error generating description for product '{product}': {str(e)}")
            # Add an error message placeholder for failed items
            descriptions.append(f"Ошибка генерации описания: {str(e)}")
    
    logger.info(f"Completed batch processing. Generated {len(descriptions)} descriptions.")
    return descriptions