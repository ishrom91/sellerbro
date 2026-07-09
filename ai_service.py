import asyncio
import logging
import tempfile
import os
from pathlib import Path
from huggingface_hub import InferenceClient
from config import HF_TOKEN, SYSTEM_PROMPT

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def generate_description(product_name: str) -> str:
    """Generate a product description using HF Inference API with Qwen2.5-7B-Instruct"""
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
                # Model is loading, wait and retry
                wait_time = 20  # Recommended wait time for model loading
                logger.info(f"Model is loading, waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)
                continue
            elif "Rate limit" in str(e) or "Too many requests" in str(e) or "429" in str(e):
                # Rate limit reached, wait before retrying
                wait_time = 10
                logger.warning(f"Rate limited, waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)
                continue
            elif attempt == max_retries:
                raise Exception(f"Failed to get response from HF API after {max_retries + 1} attempts: {str(e)}")
    
    # This should not be reached due to the loop logic, but added for safety
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
    from PIL import Image, ImageDraw, ImageFont
    import io
    
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