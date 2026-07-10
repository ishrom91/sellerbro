import asyncio
import logging
import tempfile
import os
from typing import Dict, Any, Optional
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, PreCheckoutQuery
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from config import BOT_TOKEN
from database import get_user, create_user, get_usage_stats, increment_single_usage, increment_batch_usage, check_limits, update_check_limits, after_generation, get_user_status_message
from ai_service import generate_description, generate_description_from_photo, analyze_product_photo
from batch_processor import process_excel_file
from payment_service import (
    send_subscription_invoice_stars,
    send_package_invoice_stars,
    send_subscription_payment_yookassa,
    send_package_payment_yookassa,
    process_successful_stars_payment,
    process_yookassa_webhook,
)

# Verify that BOT_TOKEN is not None to satisfy type checker
assert BOT_TOKEN is not None, "BOT_TOKEN must be set in environment"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)

dp = Dispatcher()

# Dictionary to store user states for photo processing
user_states = {}

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
        
        # Send welcome message
        welcome_msg = (
            f"🤖 Привет! Я бот для генерации SEO-оптимизированных описаний товаров для маркетплейсов.\n\n"
            f"📊 Ваш статус:\n"
            f"   • Одиночные генерации: {remaining_single}/3 осталось\n"
            f"   • Батч-обработка файлов: {remaining_batch}/1 осталось\n\n"
            f"📸 Отправь фото товара — я проанализирую его и создам описание только по реальным характеристикам! Никаких выдумок.\n\n"
            f"Как это работает:\n"
            f"• Пришли фото товара\n"
            f"• Я проанализирую его и опишу только то, что вижу\n"
            f"• Если хочешь — добавь размер, бренд, цену (то, что не видно на фото)\n"
            f"• Получишь реалистичное SEO-описание!\n\n"
            f"💡 Как пользоваться:\n"
            f"   • Отправьте название товара - я создам SEO-описание\n"
            f"   • Пришлите фото товара - я проанализирую его и создам описание на основе увиденного\n"
            f"   • Загрузите Excel/CSV файл с колонкой 'Название' или 'Товар' - я обработаю все позиции\n\n"
            f"⚠️ Бесплатный лимит: 3 описания и 1 файл в месяц."
        )
        
        await message.answer(welcome_msg)
        await message.answer("Для просмотра тарифов используйте команду /pricing")
        logger.info(f"Start command handled for user: {user_id}")
        
    except Exception as e:
        logger.error(f"Error in /start command: {str(e)}")
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")


@dp.message(Command("pricing"))
async def cmd_pricing(message: Message):
    """Show pricing and tariff plans"""
    text = (
        " **ТАРИФЫ AI SellerBro**\n\n"
        "🆓 **Бесплатный тариф:**\n"
        "• 3 генерации описаний в день\n"
        "• 1 анализ фото в день\n"
        "• 1 пакетная обработка Excel в месяц\n\n"
        "👑 **Подписка Pro — 299₽/мес:**\n"
        "• Безлимитные генерации\n"
        "• Безлимитные анализы фото\n"
        "• Безлимитные пакеты Excel\n"
        "• Приоритетная скорость\n\n"
        "📦 **Разовые пакеты:**\n"
        "• 100₽ — 20 генераций, 30 дней\n"
        "• 250₽ — 60 генераций, 30 дней\n"
        "• 500₽ — 150 генераций, 60 дней\n\n"
        " Выберите товар и способ оплаты:"
    )
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 Подписка Pro", callback_data="select_subscription")],
        [InlineKeyboardButton(text="📦 Малый пакет (20 ген)", callback_data="select_package_small")],
        [InlineKeyboardButton(text="📦 Средний пакет (60 ген)", callback_data="select_package_medium")],
        [InlineKeyboardButton(text="📦 Большой пакет (150 ген)", callback_data="select_package_large")],
        [InlineKeyboardButton(text="📊 Мой статус", callback_data="my_status")],
    ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@dp.callback_query(lambda c: c.data and c.data.startswith("select_"))
async def callback_select_product(callback: CallbackQuery):
    """Show payment method selection"""
    await callback.answer()
    
    product = callback.data.replace("select_", "")
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=f"pay_stars_{product}")],
        [InlineKeyboardButton(text="💳 Карта (ЮKassa)", callback_data=f"pay_yookassa_{product}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_pricing")],
    ])
    
    if product == "subscription":
        text = "👑 **Подписка Pro — 299₽**\n\nВыберите способ оплаты:"
    elif product.startswith("package_"):
        pkg_type = product.replace("package_", "")
        from payment_service import PACKAGES
        pkg = PACKAGES.get(pkg_type, {})
        text = f"📦 **{pkg.get('name', 'Пакет')} — {pkg.get('rub', 0)}₽**\n\nВыберите способ оплаты:"
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@dp.callback_query(lambda c: c.data == "back_to_pricing")
async def callback_back_to_pricing(callback: CallbackQuery):
    await callback.answer()
    await cmd_pricing(callback.message)


@dp.callback_query(lambda c: c.data and c.data.startswith("pay_stars_"))
async def callback_pay_stars(callback: CallbackQuery):
    """Process Telegram Stars payment"""
    await callback.answer()
    
    product = callback.data.replace("pay_stars_", "")
    user_id = callback.from_user.id
    
    if product == "subscription":
        await send_subscription_invoice_stars(callback.bot, callback.message.chat.id)
    elif product.startswith("package_"):
        package_type = product.replace("package_", "")
        await send_package_invoice_stars(callback.bot, callback.message.chat.id, package_type)


@dp.callback_query(lambda c: c.data and c.data.startswith("pay_yookassa_"))
async def callback_pay_yookassa(callback: CallbackQuery):
    """Process YooKassa payment"""
    await callback.answer()
    
    product = callback.data.replace("pay_yookassa_", "")
    user_id = callback.from_user.id
    
    if product == "subscription":
        await send_subscription_payment_yookassa(callback.bot, callback.message.chat.id, user_id)
    elif product.startswith("package_"):
        package_type = product.replace("package_", "")
        await send_package_payment_yookassa(callback.bot, callback.message.chat.id, user_id, package_type)


@dp.callback_query(lambda c: c.data == "my_status")
async def callback_my_status(callback: CallbackQuery):
    user_id = callback.from_user.id
    status_msg = get_user_status_message(user_id)
    await callback.answer()
    await callback.message.answer(status_msg, parse_mode="Markdown")


@dp.message(Command("skip"))
async def cmd_skip(message: Message):
    """Handle /skip command when user doesn't want to add additional information"""
    user_id = message.from_user.id
    
    # Check if user is in photo processing state
    if user_id in user_states and user_states[user_id]['state'] == 'awaiting_additional_info':
        # Retrieve stored photo path
        photo_path = user_states[user_id]['photo_path']
        
        try:
            # Check if user can generate
            if not update_check_limits(user_id, 'photo'):
                await message.answer(
                    "❌ Лимит исчерпан!\n\n"
                    "У вас использованы все бесплатные анализы фото на сегодня.\n\n"
                    "Хотите больше? Используйте /pricing для покупки подписки или пакета!"
                )
                return

            # Generate description based on photo only (no additional info)
            generating_msg = await message.answer("⏳ Генерирую SEO-описание на основе фото...")
            
            # Generate description from photo without additional notes
            description = await generate_description_from_photo(photo_path, "")
            
            # Send the generated description
            await message.answer(f"✅ SEO-описание готово!\n\n{description}")
            
            # Clean up user state and temporary file
            del user_states[user_id]
            if os.path.exists(photo_path):
                try:
                    os.remove(photo_path)
                except Exception as e:
                    logger.warning(f"Could not remove temp file {photo_path}: {str(e)}")
            
            # Update usage after successful generation
            after_generation(user_id, 'photo')
            
            # Get updated stats
            new_stats = get_usage_stats(user_id)
            remaining = max(0, 3 - new_stats['single_count'])
            if remaining > 0:
                await message.answer(f"📊 Осталось одиночных генераций: {remaining}/3")
            else:
                await message.answer("📊 Вы исчерпали лимит одиночных генераций на этот месяц.")
                
            logger.info(f"Generated photo-based description for user {user_id}")
            
        except Exception as gen_error:
            logger.error(f"Error generating photo-based description for user {user_id}: {str(gen_error)}")
            await message.answer("❌ Ошибка при генерации описания. Пожалуйста, попробуйте снова.")
            
            # Clean up in case of error
            if user_id in user_states:
                del user_states[user_id]
            if os.path.exists(photo_path):
                try:
                    os.remove(photo_path)
                except Exception as e:
                    logger.warning(f"Could not remove temp file {photo_path}: {str(e)}")
    else:
        await message.answer("Команда /skip доступна только при обработке фото. Отправьте фото товара для начала.")


@dp.message(F.photo)
async def handle_photo(message: Message):
    """Handle photo messages (analyze photo and generate SEO description)"""
    try:
        user_id = message.from_user.id
        username = message.from_user.username or str(user_id)
        
        # Check if user exists, create if not
        user = get_user(user_id)
        if not user:
            create_user(user_id, username)
        
        # Check usage limits
        if not update_check_limits(user_id, 'photo'):
            await message.answer(
                "❌ Лимит исчерпан!\n\n"
                "У вас использованы все бесплатные анализы фото на сегодня.\n\n"
                "Хотите больше? Используйте /pricing для покупки подписки или пакета!"
            )
            return
        
        # Download the photo
        file_info = await bot.get_file(message.photo[-1].file_id)  # Get the highest resolution photo
        file_extension = file_info.file_path.split('.')[-1] if '.' in file_info.file_path else 'jpg'
        photo_path = f"temp_photo_{user_id}_{message.message_id}.{file_extension}"
        
        try:
            await bot.download_file(file_info.file_path, photo_path)
            logger.info(f"Downloaded photo for user {user_id}: {photo_path}")
            
            # Store user state to wait for additional information
            user_states[user_id] = {
                'state': 'awaiting_additional_info',
                'photo_path': photo_path
            }
            
            # Ask user if they want to add additional information
            await message.answer(
                "Добавить информацию, которой нет на фото? (размер, бренд, цена) "
                "Отправь текстом или нажми /skip"
            )
            
        except Exception as download_error:
            logger.error(f"Error downloading photo for user {user_id}: {str(download_error)}")
            await message.answer("❌ Ошибка загрузки фото. Пожалуйста, попробуйте снова.")
            
    except Exception as e:
        logger.error(f"Error handling photo from user {message.from_user.id}: {str(e)}")
        await message.answer("Произошла ошибка при обработке фото. Пожалуйста, попробуйте снова.")


@dp.message(F.text & F.func(lambda msg: msg.from_user.id in user_states and user_states[msg.from_user.id]['state'] == 'awaiting_additional_info'))
async def handle_additional_info(message: Message):
    """Handle additional information provided by user for photo-based description"""
    user_id = message.from_user.id
    
    # Retrieve stored photo path
    photo_path = user_states[user_id]['photo_path']
    
    try:
        # Check if user can generate
        if not update_check_limits(user_id, 'photo'):
            await message.answer(
                "❌ Лимит исчерпан!\n\n"
                "У вас использованы все бесплатные анализы фото на сегодня.\n\n"
                "Хотите больше? Используйте /pricing для покупки подписки или пакета!"
            )
            return

        # Get the additional information from user
        additional_info = message.text
        
        # Generate description based on photo and additional info
        generating_msg = await message.answer("⏳ Генерирую SEO-описание на основе фото и дополнительной информации...")
        
        # Generate description from photo with additional notes
        description = await generate_description_from_photo(photo_path, additional_info)
        
        # Send the generated description
        await message.answer(f"✅ SEO-описание готово!\n\n{description}")
        
        # Clean up user state and temporary file
        del user_states[user_id]
        
        if os.path.exists(photo_path):
            try:
                os.remove(photo_path)
            except Exception as e:
                logger.warning(f"Could not remove temp file {photo_path}: {str(e)}")
        
        # Update usage after successful generation
        after_generation(user_id, 'photo')
        
        # Get updated stats
        new_stats = get_usage_stats(user_id)
        remaining = max(0, 3 - new_stats['single_count'])
        if remaining > 0:
            await message.answer(f"📊 Осталось одиночных генераций: {remaining}/3")
        else:
            await message.answer("📊 Вы исчерпали лимит одиночных генераций на этот месяц.")
            
        logger.info(f"Generated photo-based description with additional info for user {user_id}")
        
    except Exception as gen_error:
        logger.error(f"Error generating photo-based description for user {user_id}: {str(gen_error)}")
        await message.answer("❌ Ошибка при генерации описания. Пожалуйста, попробуйте снова.")
        
        # Clean up in case of error
        if user_id in user_states:
            del user_states[user_id]
        if os.path.exists(photo_path):
            try:
                os.remove(photo_path)
            except Exception as e:
                logger.warning(f"Could not remove temp file {photo_path}: {str(e)}")


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
        if not update_check_limits(user_id, 'single'):
            await message.answer(
                "❌ Лимит исчерпан!\n\n"
                "У вас использованы все 3 бесплатные генерации на сегодня.\n\n"
                "Хотите больше? Используйте /pricing для покупки подписки или пакета!"
            )
            return
        
        # Check if user is in photo processing state
        if user_id in user_states:
            # This is handled by the separate handler for additional info
            return
        
        # Send "thinking" message
        thinking_msg = await message.answer("⏳ Генерирую SEO-описание...")
        
        try:
            # Generate description
            product_name = message.text.strip()
            description = await generate_description(product_name)
            
            # Update usage after successful generation
            after_generation(user_id, 'single')
            
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
        if not update_check_limits(user_id, 'batch'):
            await message.answer(
                "❌ Лимит исчерпан!\n\n"
                "У вас использованы все бесплатные батчи на месяц.\n\n"
                "Хотите больше? Используйте /pricing для покупки подписки или пакета!"
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
                        caption="Ваш файл с добавленными SEO-описаниями 📊"
                    )
                    
                    # Update usage after successful generation
                    after_generation(user_id, 'batch')
                    
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


@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    """Answer pre-checkout query (required by Telegram)"""
    await pre_checkout_query.bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.successful_payment)
async def process_successful_stars_payment_handler(message: Message):
    """Handle successful Telegram Stars payment"""
    payment = message.successful_payment
    user_id = message.from_user.id
    payload = payment.invoice_payload
    payment_id = payment.telegram_payment_charge_id
    
    logger.info(f"Successful Stars payment from user {user_id}: payload={payload}, id={payment_id}")
    
    result_message = await process_successful_stars_payment(payload, payment_id, user_id)
    await message.answer(result_message, parse_mode="Markdown")


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