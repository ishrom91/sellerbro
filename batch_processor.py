import asyncio
import logging
import pandas as pd
import os
import tempfile
from typing import Tuple, List
from datetime import datetime
from ai_service import generate_batch_descriptions, generate_description

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_progress_messages(total: int, processed: int) -> str:
    """Return formatted progress message like 'Обработано 5 из 50...'"""
    return f"Обработано {processed} из {total}..."


async def process_excel_file(file_path: str, user_id: int) -> Tuple[str, List[str]]:
    """Process Excel/CSV file and return output file path with progress messages"""
    logger.info(f"Starting to process file: {file_path} for user: {user_id}")
    
    try:
        # Determine file extension
        _, file_extension = os.path.splitext(file_path.lower())
        
        # Read the file based on extension
        if file_extension == '.csv':
            df = pd.read_csv(file_path)
        elif file_extension in ['.xlsx', '.xls']:
            df = pd.read_excel(file_path)
        else:
            raise ValueError(f"Unsupported file format: {file_extension}. Only .xlsx, .xls, and .csv files are supported.")
        
        logger.info(f"File loaded successfully. Shape: {df.shape}")
        
        # Look for the product name column (case-insensitive)
        product_column = None
        for col in df.columns:
            if col.lower() in ['название', 'товар', 'name', 'product', 'наименование']:
                product_column = col
                break
        
        if not product_column:
            raise ValueError("Не найдена колонка 'Название' или 'Товар' в файле. Пожалуйста, переименуйте одну из колонок в 'Название' или 'Товар'.")
        
        logger.info(f"Found product column: {product_column}")
        
        # Extract product names, removing any NaN values
        products = df[product_column].dropna().astype(str).tolist()
        
        if not products:
            raise ValueError("Файл не содержит данных в колонке 'Название' или 'Товар'.")
        
        # Limit to 20 rows as per free tier limit
        if len(products) > 20:
            logger.warning(f"Truncating from {len(products)} to 20 rows due to free tier limit")
            products = products[:20]
        
        logger.info(f"Processing {len(products)} products")
        
        # Generate descriptions
        descriptions = await generate_batch_descriptions(products)
        
        # Add descriptions to the dataframe
        df_with_results = df.copy()
        df_with_results['Описание'] = descriptions
        
        # Create output file path
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"output_{user_id}_{timestamp}.xlsx"
        output_path = os.path.join(os.path.dirname(file_path), output_filename)
        
        # Save the new dataframe to Excel
        df_with_results.to_excel(output_path, index=False)
        logger.info(f"Output file saved to: {output_path}")
        
        # Generate progress messages (every 5 items)
        progress_messages = []
        total_items = len(products)
        for i in range(5, total_items + 1, 5):
            if i <= total_items:
                progress_messages.append(get_progress_messages(total_items, i))
        
        # Ensure we have a final progress message
        if total_items % 5 != 0:
            progress_messages.append(get_progress_messages(total_items, total_items))
        
        return output_path, progress_messages
        
    except ValueError as ve:
        logger.error(f"Value error in process_excel_file: {str(ve)}")
        raise
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
        raise ValueError(f"Файл не найден: {file_path}")
    except pd.errors.EmptyDataError:
        logger.error("File is empty")
        raise ValueError("Файл пустой")
    except Exception as e:
        logger.error(f"Error processing file {file_path}: {str(e)}")
        raise ValueError(f"Ошибка при обработке файла: {str(e)}")


