import asyncio
import logging
import httpx
from config import HF_TOKEN, SYSTEM_PROMPT

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def generate_description(product_name: str) -> str:
    """Generate a product description using HF Inference API with Qwen2.5-7B-Instruct"""
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "inputs": f"<s>[INST] <<SYS>>\n{SYSTEM_PROMPT}\n<</SYS>>\n\n{product_name} [/INST]",
        "parameters": {
            "max_new_tokens": 500,
            "temperature": 0.7,
            "top_p": 0.9,
            "repetition_penalty": 1.1,
            "return_full_text": False
        }
    }
    
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api-inference.huggingface.co/models/Qwen/Qwen2.5-7B-Instruct",
                    headers=headers,
                    json=payload
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if isinstance(result, list) and len(result) > 0 and 'generated_text' in result[0]:
                        description = result[0]['generated_text']
                        # Clean up the response to remove any instruction artifacts
                        if '[/INST]' in description:
                            description = description.split('[/INST]')[-1].strip()
                        logger.info(f"Successfully generated description for: {product_name[:50]}...")
                        return description
                    else:
                        logger.warning(f"Unexpected response format: {result}")
                        raise Exception(f"Unexpected response format from API: {result}")
                
                elif response.status_code == 503:
                    # Model is loading, wait and retry
                    wait_time = 20  # Recommended wait time for model loading
                    logger.info(f"Model is loading, waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)
                    continue
                
                elif response.status_code == 429:
                    # Rate limit reached, wait before retrying
                    wait_time = 10
                    logger.warning(f"Rate limited, waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)
                    continue
                
                else:
                    error_detail = response.text
                    logger.error(f"HF API error (attempt {attempt + 1}): {response.status_code} - {error_detail}")
                    if attempt == max_retries:
                        raise Exception(f"Failed to get response from HF API: {response.status_code} - {error_detail}")
        
        except httpx.TimeoutException:
            logger.error(f"Request timeout (attempt {attempt + 1})")
            if attempt == max_retries:
                raise Exception("Request timed out after multiple attempts")
        except Exception as e:
            logger.error(f"Error during HF API call (attempt {attempt + 1}): {str(e)}")
            if attempt == max_retries:
                raise
    
    # This should not be reached due to the loop logic, but added for safety
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