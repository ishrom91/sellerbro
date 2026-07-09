import asyncio
import logging
from huggingface_hub import InferenceClient
from config import HF_TOKEN, SYSTEM_PROMPT

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def generate_description(product_name: str) -> str:
    """Generate a product description using HF Inference API with Qwen2.5-7B-Instruct"""
    client = InferenceClient(token=HF_TOKEN)
    
    prompt = f"<s>[INST] <<SYS>>\n{SYSTEM_PROMPT}\n<</SYS>>\n\n{product_name} [/INST]"
    
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            # Call the model using the InferenceClient
            response = client.text_generation(
                prompt=prompt,
                model="Qwen/Qwen2.5-7B-Instruct",
                max_new_tokens=500,
                temperature=0.7,
                top_p=0.9,
                repetition_penalty=1.1,
                return_full_text=False
            )
            
            if response:
                description = response
                # Clean up the response to remove any instruction artifacts
                if '[/INST]' in description:
                    description = description.split('[/INST]')[-1].strip()
                logger.info(f"Successfully generated description for: {product_name[:50]}...")
                return description
            else:
                logger.warning(f"Empty response received")
                raise Exception(f"Empty response from API")
        
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