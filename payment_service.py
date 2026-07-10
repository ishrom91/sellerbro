import logging
import uuid
from aiogram import Bot
from aiogram.types import LabeledPrice
from yookassa import Configuration as YooConfiguration, Payment as YooPayment
from database import (
    activate_subscription, activate_package, 
    get_active_subscription, get_user_packages, 
    get_total_package_generations
)
from config import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, BOT_WEBHOOK_URL

logger = logging.getLogger(__name__)

# Configure YooKassa
if YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY:
    YooConfiguration.account_id = YOOKASSA_SHOP_ID
    YooConfiguration.secret_key = YOOKASSA_SECRET_KEY

# Prices
SUBSCRIPTION_PRO_RUB = 299
SUBSCRIPTION_PRO_STARS = 200

PACKAGES = {
    'small': {'stars': 67, 'rub': 100, 'generations': 20, 'days': 30, 'name': 'Малый пакет'},
    'medium': {'stars': 167, 'rub': 250, 'generations': 60, 'days': 30, 'name': 'Средний пакет'},
    'large': {'stars': 333, 'rub': 500, 'generations': 150, 'days': 60, 'name': 'Большой пакет'},
}


async def send_subscription_invoice_stars(bot: Bot, chat_id: int) -> None:
    """Send Telegram Stars invoice for Pro subscription"""
    prices = [LabeledPrice(label="Подписка Pro на 1 месяц", amount=SUBSCRIPTION_PRO_STARS)]
    
    await bot.send_invoice(
        chat_id=chat_id,
        title="👑 Подписка Pro на 1 месяц",
        description=(
            "✅ Безлимитные генерации описаний\n"
            "✅ Безлимитные анализы фото\n"
            "✅ Безлимитные пакеты Excel\n"
            "⚡ Приоритетная скорость"
        ),
        payload="stars_subscription_pro_1month",
        currency="XTR",
        prices=prices,
    )


async def send_package_invoice_stars(bot: Bot, chat_id: int, package_type: str) -> None:
    """Send Telegram Stars invoice for one-time package"""
    if package_type not in PACKAGES:
        logger.error(f"Unknown package type: {package_type}")
        return
    
    pkg = PACKAGES[package_type]
    prices = [LabeledPrice(label=pkg['name'], amount=pkg['stars'])]
    
    await bot.send_invoice(
        chat_id=chat_id,
        title=f"📦 {pkg['name']}",
        description=(
            f"✅ {pkg['generations']} генераций описаний\n"
            f"📅 Срок действия: {pkg['days']} дней\n"
            f"💰 Цена: {pkg['rub']}₽"
        ),
        payload=f"stars_package_{package_type}",
        currency="XTR",
        prices=prices,
    )


def create_yookassa_payment(user_id: int, amount: int, description: str, payload: str) -> str:
    """Create YooKassa payment and return payment URL"""
    try:
        idempotence_key = str(uuid.uuid4())
        
        payment = YooPayment.create({
            "amount": {
                "value": str(amount),
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": f"https://t.me/Ai_sellerbro_bot?start=payment_success"
            },
            "capture": True,
            "description": description,
            "metadata": {
                "user_id": str(user_id),
                "payload": payload
            },
            "receipt": {
                "customer": {"email": f"user_{user_id}@sellerbro.bot"},
                "items": [{
                    "description": description,
                    "quantity": "1.0",
                    "amount": {"value": str(amount), "currency": "RUB"},
                    "vat_code": 1,
                    "payment_mode": "full_payment",
                    "payment_subject": "service"
                }]
            }
        }, idempotence_key)
        
        return payment.confirmation.confirmation_url
    except Exception as e:
        logger.error(f"Error creating YooKassa payment: {str(e)}")
        raise


async def send_subscription_payment_yookassa(bot: Bot, chat_id: int, user_id: int) -> None:
    """Send YooKassa payment link for Pro subscription"""
    try:
        url = create_yookassa_payment(
            user_id=user_id,
            amount=SUBSCRIPTION_PRO_RUB,
            description="Подписка Pro AI SellerBro на 1 месяц",
            payload="yookassa_subscription_pro_1month"
        )
        
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить картой", url=url)]
        ])
        
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "👑 **Подписка Pro — 299₽**\n\n"
                "✅ Безлимитные генерации\n"
                "✅ Безлимитные анализы фото\n"
                "✅ Безлимитные пакеты Excel\n"
                "⚡ Приоритетная скорость\n\n"
                "Нажмите кнопку ниже для оплаты:"
            ),
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error sending YooKassa payment: {str(e)}")
        await bot.send_message(chat_id=chat_id, text="❌ Ошибка при создании платежа. Попробуйте позже.")


async def send_package_payment_yookassa(bot: Bot, chat_id: int, user_id: int, package_type: str) -> None:
    """Send YooKassa payment link for one-time package"""
    if package_type not in PACKAGES:
        return
    
    pkg = PACKAGES[package_type]
    
    try:
        url = create_yookassa_payment(
            user_id=user_id,
            amount=pkg['rub'],
            description=f"{pkg['name']} AI SellerBro — {pkg['generations']} генераций",
            payload=f"yookassa_package_{package_type}"
        )
        
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить картой", url=url)]
        ])
        
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"📦 **{pkg['name']} — {pkg['rub']}₽**\n\n"
                f"✅ {pkg['generations']} генераций описаний\n"
                f"📅 Срок действия: {pkg['days']} дней\n\n"
                "Нажмите кнопку ниже для оплаты:"
            ),
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error sending YooKassa payment: {str(e)}")
        await bot.send_message(chat_id=chat_id, text="❌ Ошибка при создании платежа. Попробуйте позже.")


async def process_successful_stars_payment(payload: str, payment_id: str, user_id: int) -> str:
    """Process successful Telegram Stars payment"""
    try:
        if payload == "stars_subscription_pro_1month":
            activate_subscription(
                user_id=user_id,
                payment_id=payment_id,
                amount=SUBSCRIPTION_PRO_STARS,
                payment_method="telegram_stars",
                days=30
            )
            return (
                "🎉 Оплата прошла успешно!\n\n"
                "👑 Ваша подписка Pro активирована на 30 дней!\n\n"
                "Теперь у вас:\n"
                "✅ Безлимитные генерации\n"
                "✅ Безлимитные анализы фото\n"
                "✅ Безлимитные пакеты Excel\n\n"
                "Просто отправляйте товары — лимитов нет! 🚀"
            )
        
        elif payload.startswith("stars_package_"):
            package_type = payload.replace("stars_package_", "")
            if package_type in PACKAGES:
                pkg = PACKAGES[package_type]
                activate_package(
                    user_id=user_id,
                    package_type=package_type,
                    generations=pkg['generations'],
                    days=pkg['days'],
                    payment_id=payment_id,
                    amount=pkg['stars'],
                    payment_method="telegram_stars"
                )
                return (
                    f"🎉 Оплата прошла успешно!\n\n"
                    f"📦 Активирован {pkg['name']}!\n\n"
                    f"Вам доступно {pkg['generations']} генераций в течение {pkg['days']} дней.\n"
                    f"Просто отправляйте товары! 🚀"
                )
        
        return "❌ Неизвестный тип платежа"
    
    except Exception as e:
        logger.error(f"Error processing Stars payment: {str(e)}")
        return f"❌ Ошибка при обработке платежа: {str(e)}"


def process_yookassa_webhook(event_json: dict) -> dict:
    """Process YooKassa webhook notification.
    Returns dict with status and message.
    """
    try:
        event_type = event_json.get('type')
        event_object = event_json.get('object', {})
        
        if event_type == 'payment.succeeded':
            payment_id = event_object.get('id')
            metadata = event_object.get('metadata', {})
            user_id = int(metadata.get('user_id'))
            payload = metadata.get('payload')
            amount = int(float(event_object.get('amount', {}).get('value', 0)))
            
            logger.info(f"YooKassa payment succeeded: user={user_id}, payload={payload}, amount={amount}")
            
            if payload == "yookassa_subscription_pro_1month":
                activate_subscription(
                    user_id=user_id,
                    payment_id=payment_id,
                    amount=amount,
                    payment_method="yookassa",
                    days=30
                )
                return {
                    'status': 'success',
                    'user_id': user_id,
                    'message': " Подписка Pro активирована на 30 дней!"
                }
            
            elif payload.startswith("yookassa_package_"):
                package_type = payload.replace("yookassa_package_", "")
                if package_type in PACKAGES:
                    pkg = PACKAGES[package_type]
                    activate_package(
                        user_id=user_id,
                        package_type=package_type,
                        generations=pkg['generations'],
                        days=pkg['days'],
                        payment_id=payment_id,
                        amount=amount,
                        payment_method="yookassa"
                    )
                    return {
                        'status': 'success',
                        'user_id': user_id,
                        'message': f" {pkg['name']} активирован! Доступно {pkg['generations']} генераций."
                    }
        
        return {'status': 'ignored', 'message': f'Event type: {event_type}'}
    
    except Exception as e:
        logger.error(f"Error processing YooKassa webhook: {str(e)}")
        return {'status': 'error', 'message': str(e)}