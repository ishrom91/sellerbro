import asyncio
import logging
import pandas as pd
import os
import zipfile
import tempfile
from typing import Tuple, List
from datetime import datetime
from ai_service import generate_batch_descriptions, process_product_image, generate_description

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
        
        # Generate product images for each product
        image_paths = []
        for i, product in enumerate(products):
            try:
                logger.info(f"Generating image for product {i+1}/{len(products)}: {product[:30]}...")
                image_path = await generate_product_image(product)
                image_paths.append(image_path)
                
                # Add delay between image generations to avoid rate limits
                if i < len(products) - 1:  # Don't sleep after the last item
                    logger.debug("Waiting 2 seconds between image generations to respect rate limits...")
                    await asyncio.sleep(2)
                    
            except Exception as e:
                logger.error(f"Error generating image for product '{product}': {str(e)}")
                # Add an error message placeholder for failed images
                image_paths.append(f"Ошибка генерации изображения: {str(e)}")
        
        # Add descriptions and image paths to the dataframe
        df_with_results = df.copy()
        df_with_results['Описание'] = descriptions
        df_with_results['generated_image'] = image_paths
        
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


async def process_excel_with_photos(zip_file_path: str, user_id: int) -> str:
    """
    Process a ZIP file containing an Excel file with product names and photo filenames,
    and a folder with product photos.
    
    Args:
        zip_file_path: Path to the input ZIP file
        user_id: User ID for tracking and naming
    
    Returns:
        Path to the output ZIP file containing processed Excel and photos
    """
    logger.info(f"Starting to process ZIP file with photos: {zip_file_path} for user: {user_id}")
    
    # Create a temporary directory for extraction
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            # Extract the ZIP file
            with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            
            logger.info(f"ZIP file extracted to: {temp_dir}")
            
            # Find the Excel file in the extracted files
            excel_file = None
            excel_path = None
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    if file.lower().endswith(('.xlsx', '.xls', '.csv')):
                        excel_file = file
                        excel_path = os.path.join(root, file)
                        break
                if excel_path:
                    break
            
            if not excel_path:
                raise ValueError("Не найден Excel файл (.xlsx, .xls) или CSV файл в ZIP архиве")
            
            logger.info(f"Found Excel file: {excel_path}")
            
            # Read the Excel file
            _, file_extension = os.path.splitext(excel_path.lower())
            if file_extension == '.csv':
                df = pd.read_csv(excel_path)
            elif file_extension in ['.xlsx', '.xls']:
                df = pd.read_excel(excel_path)
            else:
                raise ValueError(f"Unsupported file format: {file_extension}")
            
            logger.info(f"Excel file loaded successfully. Shape: {df.shape}")
            
            # Check for required columns
            required_columns = ['Название', 'Фото']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                # Try case-insensitive search
                available_columns = [col.lower() for col in df.columns]
                for req_col in required_columns:
                    if req_col.lower() not in available_columns:
                        raise ValueError(f"Не найдена колонка '{req_col}' в Excel файле. Требуются колонки: 'Название' и 'Фото'")
            
            # Map columns in case they have different cases
            name_col = next(col for col in df.columns if col.lower() == 'название')
            photo_col = next(col for col in df.columns if col.lower() == 'фото')
            
            # Limit to 20 rows as per free tier limit
            if len(df) > 20:
                logger.warning(f"Truncating from {len(df)} to 20 rows due to free tier limit")
                df = df.iloc[:20]
            
            # Prepare output structures
            descriptions = []
            processed_photo_paths = []
            
            # Create directory for processed photos
            processed_photos_dir = os.path.join(temp_dir, "processed_photos")
            os.makedirs(processed_photos_dir, exist_ok=True)
            
            # Process each product
            for i, (idx, row) in enumerate(df.iterrows()):
                try:
                    product_name = str(row[name_col])
                    photo_filename = str(row[photo_col])
                    
                    logger.info(f"Processing item {i+1}/{len(df)}: {product_name[:30]} with photo {photo_filename}")
                    
                    # Find the photo file in the extracted directory
                    photo_path = None
                    for root, dirs, files in os.walk(temp_dir):
                        for file in files:
                            if file == photo_filename:
                                photo_path = os.path.join(root, file)
                                break
                        if photo_path:
                            break
                    
                    if not photo_path:
                        logger.warning(f"Photo file not found: {photo_filename}")
                        # Still generate description but mark photo as not found
                        description = await generate_description(product_name)
                        descriptions.append(description)
                        processed_photo_paths.append(f"Фото не найдено: {photo_filename}")
                    else:
                        # Generate description
                        description = await generate_description(product_name)
                        descriptions.append(description)
                        
                        # Process the photo
                        processed_photo_path = process_product_image(photo_path, product_name)
                        
                        # Copy the processed photo to the processed_photos directory
                        photo_basename = os.path.basename(processed_photo_path)
                        target_path = os.path.join(processed_photos_dir, f"processed_{i+1}_{photo_basename}")
                        import shutil
                        shutil.copy2(processed_photo_path, target_path)
                        
                        processed_photo_paths.append(target_path)
                        
                        # Clean up temporary processed photo file
                        if os.path.dirname(processed_photo_path) == temp_dir:
                            try:
                                os.remove(processed_photo_path)
                            except:
                                pass  # Ignore errors when cleaning up temp files
                
                except Exception as e:
                    logger.error(f"Error processing product '{row[name_col]}': {str(e)}")
                    descriptions.append(f"Ошибка генерации описания: {str(e)}")
                    processed_photo_paths.append(f"Ошибка обработки фото: {str(e)}")
                
                # Progress update every 5 items
                if (i + 1) % 5 == 0:
                    logger.info(f"Progress: {i+1} of {len(df)} items processed")
            
            # Add results to the dataframe
            df_with_results = df.copy()
            df_with_results['Описание'] = descriptions
            df_with_results['Обработанное_фото'] = processed_photo_paths
            
            # Save the updated Excel file
            output_excel_path = os.path.join(temp_dir, f"output_with_photos_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
            df_with_results.to_excel(output_excel_path, index=False)
            
            # Create output ZIP file
            output_zip_path = os.path.join(
                os.path.dirname(zip_file_path), 
                f"catalog_output_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            )
            
            with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED) as output_zip:
                # Add the processed Excel file
                output_zip.write(output_excel_path, os.path.basename(output_excel_path))
                
                # Add all processed photos
                for root, dirs, files in os.walk(processed_photos_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arc_path = os.path.relpath(file_path, temp_dir)
                        output_zip.write(file_path, arc_path)
            
            logger.info(f"Output ZIP file created: {output_zip_path}")
            return output_zip_path
            
        except Exception as e:
            logger.error(f"Error processing ZIP file {zip_file_path}: {str(e)}")
            raise ValueError(f"Ошибка при обработке ZIP файла: {str(e)}")