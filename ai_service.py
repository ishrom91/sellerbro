import asyncio
import logging
import json
from huggingface_hub import InferenceClient
from config import HF_TOKEN, SYSTEM_PROMPT

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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