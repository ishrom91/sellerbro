import asyncio
import logging
import tempfile
import os
import time
from typing import Dict, Any, Optional, cast
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, PreCheckoutQuery, Update, CallbackQuery, User
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.chat_action import ChatActionSender

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

# Simple rate limiter
user_last_message: Dict[int, float] = {}

async def check_rate_limit(user_id: int, min_interval: int = 2) -> bool:
    """Check if user is sending messages too frequently"""
    now = time.time()
    if user_id in user_last_message:
        if now - user_last_message[user_id] < min_interval:
            return False
    user_last_message[user_id] = now
    return True

# Dictionary to store user states for photo processing
user_states: Dict[int, Dict[str, Any]] = {}

@dp.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Handle /start command"""
    try:
        # Get user object with proper type casting
        user = message.from_user
        if not user:
            return
        
        # Rate limiting check
        if not await check_rate_limit(user.id):
            return

        user_id = user.id
        username = user.username or str(user_id)
        
        # Check if user exists, create if not
        try:
            user = get_user(user_id)
            if not user:
                create_user(user_id, username)
                logger.info(f"New user registered: {user_id} (@{username})")
        except Exception as db_error:
            logger.error(f"Database error when checking/creating user {user_id}: {db_error}")
            await message.answer("⚠️ Произошла ошибка базы данных. Пожалуйста, попробуйте позже.")
            return
        
        # Get usage stats
        try:
            stats = get_usage_stats(user_id)
            remaining_single = max(0, 3 - stats['single_count'])
            remaining_batch = 1 if stats['batch_count'] < 1 else 0
        except Exception as db_error:
            logger.error(f"Database error when getting usage stats for user {user_id}: {db_error}")
            await message.answer("⚠️ Произошла ошибка получения статистики. Пожалуйста, попробуйте позже.")
            return
        
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
            f"⚠️ Бесплатный лимит: 3 описания и 1 файл в месяц.\n\n"
            f"Используя бота, вы соглашаетесь с /terms и /privacy"
        )
        
        await message.answer(welcome_msg)
        await message.answer("Для просмотра тарифов используйте команду /pricing")
        logger.info(f"Start command handled for user: {user_id}")
        
    except Exception as e:
        logger.error(f"Error in /start command: {str(e)}", exc_info=True)
        await message.answer("⚠️ Произошла техническая ошибка. Пожалуйста, попробуйте позже или обратитесь в поддержку.")


@dp.message(Command("terms"))
async def cmd_terms(message: Message) -> None:
    """Handle /terms command"""
    try:
        # Get user object with proper type casting
        user = message.from_user
        if not user:
            return
            
        # Rate limiting check
        if not await check_rate_limit(user.id):
            return

        terms_text = """
📄 ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ

1. Общие положения
Настоящее соглашение регулирует использование Telegram-бота AI SellerBro.

2. Предмет соглашения
Бот предоставляет услуги по генерации SEO-описаний товаров для маркетплейсов с использованием искусственного интеллекта.

3. Условия использования
- Пользователь обязуется использовать бота в законных целях
- Запрещается использование бота для генерации контента, нарушающего законодательство РФ
- Администрация не несёт ответственности за содержание сгенерированных текстов

4. Оплата и возвраты
- Оплата производится через Telegram Stars или ЮKassa
- Возврат средств возможен в течение 14 дней при технических проблемах
- После успешной генерации возврат не производится

5. Ограничения ответственности
- Бот использует AI-модели, которые могут генерировать неточную информацию
- Пользователь обязан проверять сгенерированные описания перед публикацией
- Администрация не гарантирует коммерческий успех карточек товаров

6. Изменение условий
Администрация оставляет за собой право изменять условия соглашения с уведомлением пользователей.

Используя бота, вы соглашаетесь с данными условиями.
    """
        await message.answer(terms_text.strip())
    except Exception as e:
        logger.error(f"Error in /terms command: {str(e)}", exc_info=True)
        await message.answer("⚠️ Произошла техническая ошибка. Пожалуйста, попробуйте позже или обратитесь в поддержку.")


@dp.message(Command("privacy"))
async def cmd_privacy(message: Message) -> None:
    """Handle /privacy command"""
    try:
        # Get user object with proper type casting
        user = message.from_user
        if not user:
            return
            
        # Rate limiting check
        if not await check_rate_limit(user.id):
            return

        privacy_text = """
🔒 ПОЛИТИКА КОНФИДЕНЦИАЛЬНОСТИ

1. Какие данные мы собираем
- Telegram ID пользователя
- История использования бота
- Информация о платежах (через платёжные системы)

2. Как мы используем данные
- Для предоставления услуг (генерация описаний)
- Для обработки платежей
- Для улучшения качества сервиса

3. Хранение и защита данных
- Данные хранятся в защищённой базе данных
- Мы не передаём данные третьим лицам
- Платёжная информация обрабатывается через сертифицированные платёжные системы

4. Ваши права
- Вы можете запросить удаление своих данных
- Вы можете отозвать согласие на обработку данных

5. Контакты
По вопросам конфиденциальности: @your_support_username

Используя бота, вы соглашаетесь с политикой конфиденциальности.
    """
        await message.answer(privacy_text.strip())
    except Exception as e:
        logger.error(f"Error in /privacy command: {str(e)}", exc_info=True)
        await message.answer("⚠️ Произошла техническая ошибка. Пожалуйста, попробуйте позже или обратитесь в поддержку.")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = """
📖 СПРАВКА ПО БОТУ AI SellerBro

🎯 Основные команды:
/start - Начать работу с ботом
/pricing - Посмотреть тарифы и цены
/help - Показать эту справку
/support - Связаться с поддержкой
/terms - Пользовательское соглашение
/privacy - Политика конфиденциальности

💡 Как пользоваться:

1️⃣ Генерация описания:
Просто отправьте название товара боту.
Пример: "Платье женское летнее хлопок"

2️⃣ Анализ фото:
Отправьте фото товара боту.
Бот проанализирует фото и создаст описание на основе реальных характеристик.

3️⃣ Пакетная обработка:
Отправьте Excel файл с колонкой "Название".
Бот создаст описания для всех товаров.

📊 Лимиты бесплатного тарифа:
• 3 генерации в день
• 1 анализ фото в день
• 1 пакетная обработка в месяц

💎 Хотите больше? Используйте /pricing для покупки подписки или пакетов.

❓ Остались вопросы? Используйте /support
    """
    await message.answer(help_text.strip())


@dp.message(Command("support"))
async def cmd_support(message: Message):
    support_text = """
🆘 ПОДДЕРЖКА

Если у вас возникли вопросы или проблемы:

📧 Напишите в поддержку: @is_roman

📖 Полезные ссылки:
• Справка: /help
• Тарифы: /pricing
• Соглашение: /terms
• Конфиденциальность: /privacy

Мы стараемся отвечать в течение 24 часов.
    """
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать в поддержку", url="https://t.me/is_roman")]
    ])
    await message.answer(support_text.strip(), reply_markup=keyboard)


@dp.message(Command("pricing"))
async def cmd_pricing(message: Message) -> None:
    """Show pricing and tariff plans"""
    try:
        # Get user object with proper type casting
        user = message.from_user
        if not user:
            return
            
        # Rate limiting check
        if not await check_rate_limit(user.id):
            return

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
    except Exception as e:
        logger.error(f"Error in /pricing command: {str(e)}", exc_info=True)
        await message.answer("⚠️ Произошла техническая ошибка. Пожалуйста, попробуйте позже или обратитесь в поддержку.")


@dp.callback_query(lambda c: c.data and c.data.startswith("select_"))
async def callback_select_product(callback: CallbackQuery):
    """Show payment method selection"""
    try:
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
    except Exception as e:
        logger.error(f"Error in callback_select_product: {str(e)}", exc_info=True)
        await callback.answer("⚠️ Произошла техническая ошибка. Пожалуйста, попробуйте позже или обратитесь в поддержку.")


@dp.callback_query(lambda c: c.data == "back_to_pricing")
async def callback_back_to_pricing(callback: CallbackQuery):
    try:
        await callback.answer()
        await cmd_pricing(callback.message)
    except Exception as e:
        logger.error(f"Error in callback_back_to_pricing: {str(e)}", exc_info=True)
        await callback.answer("⚠️ Произошла техническая ошибка. Пожалуйста, попробуйте позже или обратитесь в поддержку.")


@dp.callback_query(lambda c: c.data and c.data.startswith("pay_stars_"))
async def callback_pay_stars(callback: CallbackQuery):
    """Process Telegram Stars payment"""
    try:
        await callback.answer()
        
        product = callback.data.replace("pay_stars_", "")
        user_id = callback.from_user.id
        
        if product == "subscription":
            await send_subscription_invoice_stars(callback.bot, callback.message.chat.id)
        elif product.startswith("package_"):
            package_type = product.replace("package_", "")
            await send_package_invoice_stars(callback.bot, callback.message.chat.id, package_type)
    except Exception as e:
        logger.error(f"Error in callback_pay_stars: {str(e)}", exc_info=True)
        await callback.answer("⚠️ Произошла техническая ошибка. Пожалуйста, попробуйте позже или обратитесь в поддержку.")


@dp.callback_query(lambda c: c.data and c.data.startswith("pay_yookassa_"))
async def callback_pay_yookassa(callback: CallbackQuery):
    """Process YooKassa payment"""
    try:
        await callback.answer()
        
        product = callback.data.replace("pay_yookassa_", "")
        user_id = callback.from_user.id
        
        if product == "subscription":
            await send_subscription_payment_yookassa(callback.bot, callback.message.chat.id, user_id)
        elif product.startswith("package_"):
            package_type = product.replace("package_", "")
            await send_package_payment_yookassa(callback.bot, callback.message.chat.id, user_id, package_type)
    except Exception as e:
        logger.error(f"Error in callback_pay_yookassa: {str(e)}", exc_info=True)
        await callback.answer("⚠️ Произошла техническая ошибка. Пожалуйста, попробуйте позже или обратитесь в поддержку.")


@dp.callback_query(lambda c: c.data == "my_status")
async def callback_my_status(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id
        status_msg = get_user_status_message(user_id)
        await callback.answer()
        await callback.message.answer(status_msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in callback_my_status: {str(e)}", exc_info=True)
        await callback.answer("⚠️ Произошла техническая ошибка. Пожалуйста, попробуйте позже или обратитесь в поддержку.")


@dp.message(Command("skip"))
async def cmd_skip(message: Message):
    """Handle /skip command when user doesn't want to add additional information"""
    try:
        # Rate limiting check
        if not await check_rate_limit(message.from_user.id):
            return

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
                logger.error(f"Error generating photo-based description for user {user_id}: {str(gen_error)}", exc_info=True)
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
    except Exception as e:
        logger.error(f"Error in /skip command: {str(e)}", exc_info=True)
        await message.answer("⚠️ Произошла техническая ошибка. Пожалуйста, попробуйте позже или обратитесь в поддержку.")


@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    """Handle photo messages (analyze photo and generate SEO description)"""
    try:
        # Get user object with proper type casting
        user = message.from_user
        if not user:
            return
            
        # Rate limiting check
        if not await check_rate_limit(user.id):
            return

        user_id = user.id
        username = user.username or str(user_id)
        
        # Check if user exists, create if not
        try:
            user = get_user(user_id)
            if not user:
                create_user(user_id, username)
        except Exception as db_error:
            logger.error(f"Database error when checking/creating user {user_id}: {db_error}")
            await message.answer("⚠️ Произошла ошибка базы данных. Пожалуйста, попробуйте позже.")
            return
        
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
            logger.error(f"Error downloading photo for user {user_id}: {str(download_error)}", exc_info=True)
            await message.answer("❌ Ошибка загрузки фото. Пожалуйста, попробуйте снова.")
            
    except Exception as e:
        logger.error(f"Error handling photo from user {message.from_user.id}: {str(e)}", exc_info=True)
        await message.answer("⚠️ Произошла техническая ошибка. Пожалуйста, попробуйте позже или обратитесь в поддержку.")


@dp.message(F.text & F.func(lambda msg: msg.from_user.id in user_states and user_states[msg.from_user.id]['state'] == 'awaiting_additional_info'))
async def handle_additional_info(message: Message):
    """Handle additional information provided by user for photo-based description"""
    try:
        # Rate limiting check
        if not await check_rate_limit(message.from_user.id):
            return

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
            logger.error(f"Error generating photo-based description for user {user_id}: {str(gen_error)}", exc_info=True)
            await message.answer("❌ Ошибка при генерации описания. Пожалуйста, попробуйте снова.")
            
            # Clean up in case of error
            if user_id in user_states:
                del user_states[user_id]
            if os.path.exists(photo_path):
                try:
                    os.remove(photo_path)
                except Exception as e:
                    logger.warning(f"Could not remove temp file {photo_path}: {str(e)}")
    except Exception as e:
        logger.error(f"Error handling additional info from user {message.from_user.id}: {str(e)}", exc_info=True)
        await message.answer("⚠️ Произошла техническая ошибка. Пожалуйста, попробуйте позже или обратитесь в поддержку.")


@dp.message(F.text & ~F.document)
async def handle_text_message(message: Message) -> None:
    """Handle text messages (single product description)"""
    try:
        # Get user object with proper type casting
        user = message.from_user
        if not user:
            return
            
        # Rate limiting check
        if not await check_rate_limit(user.id):
            return

        user_id = user.id
        username = user.username or str(user_id)
        
        # Check if user exists, create if not
        try:
            user = get_user(user_id)
            if not user:
                create_user(user_id, username)
        except Exception as db_error:
            logger.error(f"Database error when checking/creating user {user_id}: {db_error}")
            await message.answer("⚠️ Произошла ошибка базы данных. Пожалуйста, попробуйте позже.")
            return
        
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
            logger.error(f"Error generating description for user {user_id}: {str(gen_error)}", exc_info=True)
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=thinking_msg.message_id,
                text="❌ Ошибка при генерации описания. Пожалуйста, попробуйте снова."
            )
            
    except Exception as e:
        logger.error(f"Error handling text message from user {message.from_user.id}: {str(e)}", exc_info=True)
        await message.answer("⚠️ Произошла техническая ошибка. Пожалуйста, попробуйте позже или обратитесь в поддержку.")


@dp.message(F.document)
async def handle_document(message: Message) -> None:
    """Handle document uploads (Excel/CSV files for batch processing)"""
    try:
        # Get user object with proper type casting
        user = message.from_user
        if not user:
            return
            
        # Rate limiting check
        if not await check_rate_limit(user.id):
            return

        user_id = user.id
        username = user.username or str(user_id)
        
        # Check if user exists, create if not
        try:
            user = get_user(user_id)
            if not user:
                create_user(user_id, username)
        except Exception as db_error:
            logger.error(f"Database error when checking/creating user {user_id}: {db_error}")
            await message.answer("⚠️ Произошла ошибка базы данных. Пожалуйста, попробуйте позже.")
            return
        
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
                logger.error(f"ValueError in file processing for user {user_id}: {str(ve)}", exc_info=True)
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=processing_msg.message_id,
                    text=f"❌ Ошибка обработки файла: {str(ve)}"
                )
            except Exception as e:
                logger.error(f"Error in file processing for user {user_id}: {str(e)}", exc_info=True)
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=processing_msg.message_id,
                    text="❌ Ошибка при обработке файла. Проверьте формат и содержимое."
                )
                
        except Exception as download_error:
            logger.error(f"Error downloading file for user {user_id}: {str(download_error)}", exc_info=True)
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
        logger.error(f"Error handling document from user {message.from_user.id}: {str(e)}", exc_info=True)
        await message.answer("⚠️ Произошла техническая ошибка. Пожалуйста, попробуйте позже или обратитесь в поддержку.")


@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    """Answer pre-checkout query (required by Telegram)"""
    try:
        await pre_checkout_query.bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    except Exception as e:
        logger.error(f"Error in pre-checkout query: {str(e)}", exc_info=True)


@dp.message(F.successful_payment)
async def process_successful_stars_payment_handler(message: Message):
    """Handle successful Telegram Stars payment"""
    try:
        payment = message.successful_payment
        user_id = message.from_user.id
        payload = payment.invoice_payload
        payment_id = payment.telegram_payment_charge_id
        
        logger.info(f"Successful Stars payment from user {user_id}: payload={payload}, id={payment_id}")
        
        result_message = await process_successful_stars_payment(payload, payment_id, user_id)
        await message.answer(result_message, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in successful payment handler: {str(e)}", exc_info=True)
        await message.answer("⚠️ Произошла ошибка обработки платежа. Пожалуйста, обратитесь в поддержку.")


@dp.errors()
async def errors_handler(update: Update, exception: Exception) -> bool:
    """Global error handler to prevent bot crashes"""
    logger.error(f"Global error caught: {exception}", exc_info=True)
    
    try:
        if update.message:
            await update.message.answer(
                "⚠️ Произошла техническая ошибка на сервере. Пожалуйста, попробуйте еще раз через минуту.\n"
                "Если ошибка повторяется, напишите в поддержку: @is_roman"
            )
        elif update.callback_query:
            await update.callback_query.answer("⚠️ Техническая ошибка. Попробуйте позже.", show_alert=True)
    except Exception as e:
        logger.error(f"Failed to send error message to user: {e}")
    
    return True


async def main() -> None:
    """Main function to run the bot"""
    logger.info("Starting bot...")
    try:
        # Use async context manager for better resource management
        async with bot:
            await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Error running bot: {str(e)}", exc_info=True)
    finally:
        await bot.session.close()
        logger.info("Bot session closed")


if __name__ == "__main__":
    asyncio.run(main())