import asyncio
import logging
import tempfile
import os
from typing import Dict, Any
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest

from config import BOT_TOKEN
from database import get_user, create_user, get_usage_stats, increment_single_usage, increment_batch_usage, check_limits, increment_image_generation_usage
from ai_service import generate_description, generate_product_image
from batch_processor import process_excel_file

# Verify that BOT_TOKEN is not None to satisfy type checker
assert BOT_TOKEN is not None, "BOT_TOKEN must be set in environment"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)

dp = Dispatcher()


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command"""
    try:
        user_id = message.from_user.id
        username = message.from_user.username or str(user_id)
        
        # Check if user exists, create if not
        user = get_user(user_id)
        if not user:
            create_user(user_id, username)
            logger.info(f"New user registered: {user_id} (@{username})")
        
        # Get usage stats
        stats = get_usage_stats(user_id)
        remaining_single = max(0, 3 - stats['single_count'])
        remaining_batch = 1 if stats['batch_count'] < 1 else 0
        remaining_images = max(0, 5 - stats['image_generation_count'])  # 5 images per month
        
        # Send welcome message
        welcome_msg = (
            f"🤖 Привет! Я бот для генерации SEO-оптимизированных описаний товаров и профессиональных фото-карт для маркетплейсов.\n\n"
            f"📊 Ваш статус:\n"
            f"   • Одиночные генерации: {remaining_single}/3 осталось\n"
            f"   • Батч-обработка файлов: {remaining_batch}/1 осталось\n"
            f"   • Генерация фото-карт: {remaining_images}/5 осталось\n\n"
            f"💡 Как пользоваться:\n"
            f"   • Отправьте название товара - я создам описание\n"
            f"   • Пришлите фото товара - я создам профессиональную фото-карточку\n"
            f"   • Загрузите Excel/CSV файл с колонкой 'Название' или 'Товар' - я обработаю все позиции\n\n"
            f"⚠️ Бесплатный лимит: 3 описания, 1 файл и 5 фото-карт в месяц."
        )
        
        await message.answer(welcome_msg)
        logger.info(f"Start command handled for user: {user_id}")
        
    except Exception as e:
        logger.error(f"Error in /start command: {str(e)}")
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")


@dp.message(F.photo)
async def handle_photo(message: Message):
    """Handle photo messages (generate product image card)"""
    try:
        user_id = message.from_user.id
        username = message.from_user.username or str(user_id)
        
        # Check if user exists, create if not
        user = get_user(user_id)
        if not user:
            create_user(user_id, username)
        
        # Check image generation limits
        stats = get_usage_stats(user_id)
        if stats['image_generation_count'] >= 5:  # 5 images per month limit
            await message.answer(
                "❌ Вы исчерпали лимит бесплатной генерации фото-карт.\n"
                "Доступно: 5 фото-карт в месяц.\n"
                "Для продолжения работы необходимо обновить статус."
            )
            return
        
        # Download the photo
        file_info = await bot.get_file(message.photo[-1].file_id)  # Get the highest resolution photo
        file_extension = file_extension = file_info.file_path.split('.')[-1] if '.' in file_info.file_path else 'jpg'
        base_image_path = f"temp_base_image_{user_id}_{message.message_id}.{file_extension}"
        
        try:
            await bot.download_file(file_info.file_path, base_image_path)
            logger.info(f"Downloaded base image for user {user_id}: {base_image_path}")
            
            # Send "generating" message
            generating_msg = await message.answer("🎨 Генерирую профессиональную фото-карточку...")
            
            try:
                # Generate product image using the uploaded photo as base
                product_name = f"product from photo by user {username}"  # Placeholder name
                generated_image_path = await generate_product_image(product_name, base_image_path)
                
                # Increment image generation usage counter
                increment_image_generation_usage(user_id)
                
                # Send the generated image
                result_image = FSInputFile(generated_image_path)
                await message.answer_photo(
                    photo=result_image,
                    caption="Ваша профессиональная фото-карточка готова! 🖼️"
                )
                
                # Edit the generating message
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=generating_msg.message_id,
                    text="✅ Фото-карточка успешно создана!"
                )
                
                # Get updated stats
                new_stats = get_usage_stats(user_id)
                remaining_images = max(0, 5 - new_stats['image_generation_count'])
                if remaining_images > 0:
                    await message.answer(f"📊 Осталось фото-карт: {remaining_images}/5")
                else:
                    await message.answer("📊 Вы исчерпали лимит фото-карт на этот месяц.")
                    
                logger.info(f"Generated product image for user {user_id}")
                
            except Exception as gen_error:
                logger.error(f"Error generating product image for user {user_id}: {str(gen_error)}")
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=generating_msg.message_id,
                    text="❌ Ошибка при генерации фото-карточки. Пожалуйста, попробуйте снова."
                )
                
        finally:
            # Clean up temporary files
            if os.path.exists(base_image_path):
                try:
                    os.remove(base_image_path)
                    logger.debug(f"Removed temp base image: {base_image_path}")
                except Exception as cleanup_error:
                    logger.warning(f"Could not remove temp base image {base_image_path}: {str(cleanup_error)}")
                    
    except Exception as e:
        logger.error(f"Error handling photo from user {message.from_user.id}: {str(e)}")
        await message.answer("Произошла ошибка при обработке фото. Пожалуйста, попробуйте снова.")


@dp.message(Command("card"))
async def cmd_card(message: Message):
    """Handle /card command - guide user to send a photo for image generation"""
    try:
        user_id = message.from_user.id
        username = message.from_user.username or str(user_id)
        
        # Check if user exists, create if not
        user = get_user(user_id)
        if not user:
            create_user(user_id, username)
        
        # Check image generation limits
        stats = get_usage_stats(user_id)
        if stats['image_generation_count'] >= 5:  # 5 images per month limit
            await message.answer(
                "❌ Вы исчерпали лимит бесплатной генерации фото-карт.\n"
                "Доступно: 5 фото-карт в месяц.\n"
                "Для продолжения работы необходимо обновить статус."
            )
            return
        
        await message.answer(
            "📸 Чтобы создать профессиональную фото-карточку товара, просто пришлите мне фото.\n"
            "Я улучшу его и сделаю как для коммерческой продажи."
        )
        logger.info(f"Card command handled for user: {user_id}")
        
    except Exception as e:
        logger.error(f"Error in /card command: {str(e)}")
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")


@dp.message(F.text & ~F.document)
async def handle_text_message(message: Message):
    """Handle text messages (single product description)"""
    try:
        user_id = message.from_user.id
        username = message.from_user.username or str(user_id)
        
        # Check if user exists, create if not
        user = get_user(user_id)
        if not user:
            create_user(user_id, username)
        
        # Check usage limits
        if not check_limits(user_id):
            await message.answer(
                "❌ Вы исчерпали лимит бесплатных генераций.\n"
                "Доступно: 3 одиночные генерации и 1 батч-обработка файла в месяц.\n"
                "Для продолжения работы необходимо обновить статус."
            )
            return
        
        # Send "thinking" message
        thinking_msg = await message.answer("⏳ Генерирую описание...")
        
        try:
            # Generate description
            product_name = message.text.strip()
            description = await generate_description(product_name)
            
            # Increment usage counter
            increment_single_usage(user_id)
            
            # Update thinking message with result
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=thinking_msg.message_id,
                text=f"✅ Готово!\n\n<b>{product_name}</b>\n\n{description}"
            )
            
            # Get updated stats
            stats = get_usage_stats(user_id)
            remaining = max(0, 3 - stats['single_count'])
            if remaining > 0:
                await message.answer(f"📊 Осталось одиночных генераций: {remaining}/3")
            else:
                await message.answer("📊 Вы исчерпали лимит одиночных генераций на этот месяц.")
                
            logger.info(f"Generated description for user {user_id}: {product_name[:50]}...")
            
        except Exception as gen_error:
            logger.error(f"Error generating description for user {user_id}: {str(gen_error)}")
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=thinking_msg.message_id,
                text="❌ Ошибка при генерации описания. Пожалуйста, попробуйте снова."
            )
            
    except Exception as e:
        logger.error(f"Error handling text message from user {message.from_user.id}: {str(e)}")
        await message.answer("Произошла ошибка при обработке сообщения. Пожалуйста, попробуйте снова.")


@dp.message(F.document)
async def handle_document(message: Message):
    """Handle document uploads (Excel/CSV files for batch processing)"""
    try:
        user_id = message.from_user.id
        username = message.from_user.username or str(user_id)
        
        # Check if user exists, create if not
        user = get_user(user_id)
        if not user:
            create_user(user_id, username)
        
        # Check batch usage limits
        stats = get_usage_stats(user_id)
        if stats['batch_count'] >= 1:
            await message.answer(
                "❌ Вы исчерпали лимит бесплатной батч-обработки файлов.\n"
                "Доступно: 3 одиночные генерации и 1 батч-обработка файла в месяц.\n"
                "Для продолжения работы необходимо обновить статус."
            )
            return
        
        # Check file type
        file_extension = message.document.file_name.split('.')[-1].lower()
        if file_extension not in ['xlsx', 'xls', 'csv']:
            await message.answer(
                "❌ Неподдерживаемый формат файла.\n"
                "Поддерживаются только файлы Excel (.xlsx, .xls) и CSV (.csv)."
            )
            return
        
        # Download file
        file_info = await bot.get_file(message.document.file_id)
        file_path = f"temp_{user_id}_{message.document.file_unique_id}.{file_extension}"
        
        try:
            await bot.download_file(file_info.file_path, file_path)
            logger.info(f"Downloaded file for user {user_id}: {file_path}")
            
            # Send processing message
            processing_msg = await message.answer("⏳ Начинаю обработку файла...")
            
            # Process the file (this will send progress updates)
            try:
                output_path, progress_messages = await process_excel_file(file_path, user_id)
                
                # Send progress updates (every 5 items as specified)
                sent_updates = set()  # Track which messages we've sent to avoid duplicates
                for prog_msg in progress_messages:
                    if prog_msg not in sent_updates:
                        try:
                            await message.answer(prog_msg)
                            sent_updates.add(prog_msg)
                        except Exception as e:
                            logger.warning(f"Could not send progress update: {str(e)}")
                
                # Send completion message
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=processing_msg.message_id,
                    text="✅ Файл успешно обработан! Отправляю результат..."
                )
                
                # Send the result file
                try:
                    result_file = FSInputFile(output_path)
                    await message.answer_document(
                        document=result_file,
                        caption="Ваш файл с добавленными описаниями и ссылками на фото-карты 📊"
                    )
                    
                    # Increment batch usage counter
                    increment_batch_usage(user_id)
                    
                    # Get updated stats
                    new_stats = get_usage_stats(user_id)
                    remaining_batch = 1 if new_stats['batch_count'] < 1 else 0
                    if remaining_batch > 0:
                        await message.answer(f"📊 Осталось батч-генераций: {remaining_batch}/1")
                    else:
                        await message.answer("📊 Вы исчерпали лимит батч-генераций на этот месяц.")
                        
                    logger.info(f"Batch processing completed for user {user_id}, file sent: {output_path}")
                    
                except TelegramBadRequest as e:
                    logger.error(f"TelegramBadRequest when sending file: {str(e)}")
                    await message.answer("❌ Ошибка при отправке файла. Файл слишком большой или поврежден.")
                    
            except ValueError as ve:
                logger.error(f"ValueError in file processing for user {user_id}: {str(ve)}")
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=processing_msg.message_id,
                    text=f"❌ Ошибка обработки файла: {str(ve)}"
                )
            except Exception as e:
                logger.error(f"Error in file processing for user {user_id}: {str(e)}")
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=processing_msg.message_id,
                    text="❌ Ошибка при обработке файла. Проверьте формат и содержимое."
                )
                
        except Exception as download_error:
            logger.error(f"Error downloading file for user {user_id}: {str(download_error)}")
            await message.answer("❌ Ошибка загрузки файла. Пожалуйста, попробуйте снова.")
            
        finally:
            # Clean up temporary files
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.debug(f"Removed temp file: {file_path}")
                except Exception as cleanup_error:
                    logger.warning(f"Could not remove temp file {file_path}: {str(cleanup_error)}")
                    
            # Remove output file if it was created
            output_pattern = f"output_{user_id}_"
            for file in os.listdir('.'):
                if file.startswith(output_pattern) and file.endswith('.xlsx'):
                    try:
                        os.remove(file)
                        logger.debug(f"Removed output file: {file}")
                    except Exception as cleanup_error:
                        logger.warning(f"Could not remove output file {file}: {str(cleanup_error)}")
                        
    except Exception as e:
        logger.error(f"Error handling document from user {message.from_user.id}: {str(e)}")
        await message.answer("Произошла ошибка при обработке файла. Пожалуйста, попробуйте снова.")


async def main():
    """Main function to run the bot"""
    logger.info("Starting bot...")
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Error running bot: {str(e)}")
    finally:
        await bot.session.close()
        logger.info("Bot session closed")


if __name__ == "__main__":
    asyncio.run(main())