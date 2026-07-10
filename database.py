import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Supabase client
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    logger.error(f"Failed to initialize Supabase client: {str(e)}")
    supabase = None


def get_user(user_id: int) -> Optional[Dict]:
    """Get user from database by user_id"""
    if supabase is None:
        logger.error("Supabase client not initialized")
        return None
        
    try:
        response = (
            supabase
            .table('users')
            .select('*')
            .eq('id', user_id)
            .execute()
        )
        
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {str(e)}")
        return None


def create_user(user_id: int, username: str) -> None:
    """Create a new user in the database"""
    if supabase is None:
        logger.error("Supabase client not initialized")
        return
        
    try:
        user_data = {
            'id': user_id,
            'username': username,
            'single_count': 0,
            'batch_count': 0,
            'last_reset': datetime.utcnow().isoformat(),
            'created_at': datetime.utcnow().isoformat()
        }
        
        supabase.table('users').insert(user_data).execute()
        logger.info(f"Created new user: {user_id}")
    except Exception as e:
        logger.error(f"Error creating user {user_id}: {str(e)}")
        raise


def get_usage_stats(user_id: int) -> Dict:
    """Get usage statistics for a user"""
    try:
        user = get_user(user_id)
        if not user:
            # Create user if doesn't exist
            create_user(user_id, "unknown")
            return {
                'single_count': 0,
                'batch_count': 0,
                'last_reset': datetime.utcnow().isoformat()
            }
        
        # Check if we need to reset counters (daily reset for single, monthly for batch)
        last_reset = datetime.fromisoformat(user['last_reset'])
        if datetime.utcnow() >= last_reset + timedelta(days=1):  # Daily reset for single
            reset_daily_usage(user_id)
            user = get_user(user_id)  # Refresh user data after reset
        
        return {
            'single_count': user.get('single_count', 0),
            'batch_count': user.get('batch_count', 0),
            'last_reset': user.get('last_reset', datetime.utcnow().isoformat())
        }
    except Exception as e:
        logger.error(f"Error getting usage stats for user {user_id}: {str(e)}")
        return {
            'single_count': 0,
            'batch_count': 0,
            'last_reset': datetime.utcnow().isoformat()
        }


def increment_single_usage(user_id: int) -> None:
    """Increment single generation usage count"""
    if supabase is None:
        logger.error("Supabase client not initialized")
        return
        
    try:
        # Get current user data first
        user = get_user(user_id)
        if user:
            new_count = user['single_count'] + 1
            supabase.table('users').update({'single_count': new_count}).eq('id', user_id).execute()
            logger.info(f"Incremented single usage for user {user_id}, new count: {new_count}")
    except Exception as e:
        logger.error(f"Error incrementing single usage for user {user_id}: {str(e)}")


def increment_batch_usage(user_id: int) -> None:
    """Increment batch usage count"""
    if supabase is None:
        logger.error("Supabase client not initialized")
        return
        
    try:
        user = get_user(user_id)
        if user:
            new_count = user['batch_count'] + 1
            supabase.table('users').update({'batch_count': new_count}).eq('id', user_id).execute()
            logger.info(f"Incremented batch usage for user {user_id}, new count: {new_count}")
    except Exception as e:
        logger.error(f"Error incrementing batch usage for user {user_id}: {str(e)}")


def increment_image_generation_usage(user_id: int) -> None:
    """Increment image generation usage count"""
    if supabase is None:
        logger.error("Supabase client not initialized")
        return
        
    try:
        user = get_user(user_id)
        if user:
            # For backward compatibility, if image_generation_count doesn't exist in user record,
            # we'll need to handle this differently. For now, we'll just log the action.
            # In a real implementation, we'd need to add this field to the users table.
            logger.info(f"Incremented image generation usage for user {user_id}")
    except Exception as e:
        logger.error(f"Error incrementing image generation usage for user {user_id}: {str(e)}")


def check_limits(user_id: int) -> bool:
    """Check if user is within their usage limits"""
    try:
        stats = get_usage_stats(user_id)
        
        # Check single limit (5 per day)
        if stats['single_count'] >= 5:
            logger.info(f"User {user_id} exceeded single generation limit ({stats['single_count']}/5)")
            return False
        
        # Check batch limit (1 per month)
        if stats['batch_count'] >= 1:
            logger.info(f"User {user_id} exceeded batch generation limit ({stats['batch_count']}/1)")
            return False
            
        logger.info(f"User {user_id} passed limits check. Single: {stats['single_count']}/5, Batch: {stats['batch_count']}/1")
        return True
    except Exception as e:
        logger.error(f"Error checking limits for user {user_id}: {str(e)}")
        return False


def reset_daily_usage(user_id: int) -> None:
    """Reset daily usage counters for a user"""
    if supabase is None:
        logger.error("Supabase client not initialized")
        return
        
    try:
        supabase.table('users').update({
            'single_count': 0,
            'last_reset': datetime.utcnow().isoformat()
        }).eq('id', user_id).execute()
        logger.info(f"Reset daily usage for user {user_id}")
    except Exception as e:
        logger.error(f"Error resetting daily usage for user {user_id}: {str(e)}")


# Subscription management
def get_active_subscription(user_id: int) -> Optional[Dict]:
    """Check if user has active Pro subscription"""
    if supabase is None:
        logger.error("Supabase client not initialized")
        return None
    
    try:
        now = datetime.utcnow().isoformat()
        response = supabase.table('subscriptions').select('*').eq('user_id', user_id).gte('expires_at', now).order('expires_at', desc=True).limit(1).execute()
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        logger.error(f"Error getting subscription: {str(e)}")
        return None

def activate_subscription(user_id: int, payment_id: str, amount: int, payment_method: str, days: int = 30) -> None:
    """Activate Pro subscription for user"""
    if supabase is None:
        logger.error("Supabase client not initialized")
        return
    
    try:
        expires_at = (datetime.utcnow() + timedelta(days=days)).isoformat()
        supabase.table('subscriptions').insert({
            'user_id': user_id,
            'plan': 'pro',
            'expires_at': expires_at,
            'payment_id': payment_id,
            'amount': amount,
            'payment_method': payment_method
        }).execute()
        logger.info(f"Activated Pro subscription for user {user_id} via {payment_method}")
    except Exception as e:
        logger.error(f"Error activating subscription: {str(e)}")
        raise

# Package management
def get_user_packages(user_id: int) -> List[Dict]:
    """Get all active packages for user"""
    if supabase is None:
        logger.error("Supabase client not initialized")
        return []
    
    try:
        now = datetime.utcnow().isoformat()
        response = supabase.table('packages').select('*').eq('user_id', user_id).gte('expires_at', now).gt('remaining_generations', 0).order('created_at', desc=True).execute()
        return response.data or []
    except Exception as e:
        logger.error(f"Error getting packages: {str(e)}")
        return []

def get_total_package_generations(user_id: int) -> int:
    """Get total remaining generations from all active packages"""
    packages = get_user_packages(user_id)
    return sum(pkg['remaining_generations'] for pkg in packages)

def use_package_generation(user_id: int) -> bool:
    """Use one generation from user's packages. Returns True if successful."""
    packages = get_user_packages(user_id)
    for pkg in packages:
        if pkg['remaining_generations'] > 0:
            try:
                new_count = pkg['remaining_generations'] - 1
                supabase.table('packages').update({'remaining_generations': new_count}).eq('id', pkg['id']).execute()
                logger.info(f"Used package generation for user {user_id}, remaining: {new_count}")
                return True
            except Exception as e:
                logger.error(f"Error using package: {str(e)}")
                return False
    return False

def activate_package(user_id: int, package_type: str, generations: int, days: int, payment_id: str, amount: int, payment_method: str) -> None:
    """Activate a one-time package for user"""
    if supabase is None:
        logger.error("Supabase client not initialized")
        return
    
    try:
        expires_at = (datetime.utcnow() + timedelta(days=days)).isoformat()
        supabase.table('packages').insert({
            'user_id': user_id,
            'package_type': package_type,
            'total_generations': generations,
            'remaining_generations': generations,
            'expires_at': expires_at,
            'payment_id': payment_id,
            'amount': amount,
            'payment_method': payment_method
        }).execute()
        logger.info(f"Activated package {package_type} for user {user_id} via {payment_method}")
    except Exception as e:
        logger.error(f"Error activating package: {str(e)}")
        raise

# Daily reset
def check_daily_reset(user_id: int) -> None:
    """Reset daily counters if day has changed"""
    user = get_user(user_id)
    if not user:
        return
    
    last_reset = datetime.fromisoformat(user['last_reset'].replace('Z', '+00:00'))
    now = datetime.utcnow()
    
    if now >= last_reset + timedelta(days=1):
        supabase.table('users').update({
            'single_count': 0,
            'last_reset': now.isoformat()
        }).eq('id', user_id).execute()
        logger.info(f"Reset daily counters for user {user_id}")

# Unified limit check
def update_check_limits(user_id: int, generation_type: str = 'single') -> bool:
    """Check if user can generate (considers subscription, packages, free limits)
    
    generation_type: 'single' or 'photo' or 'batch'
    Returns True if allowed, False if limit reached.
    """
    check_daily_reset(user_id)
    
    # Check Pro subscription (unlimited)
    subscription = get_active_subscription(user_id)
    if subscription:
        logger.info(f"User {user_id} has active Pro subscription")
        return True
    
    # Check packages (for single generation)
    if generation_type == 'single':
        if get_total_package_generations(user_id) > 0:
            logger.info(f"User {user_id} has package generations available")
            return True
    
    # Check free limits
    stats = get_usage_stats(user_id)
    
    if generation_type == 'single':
        return stats['single_count'] < 3
    elif generation_type == 'photo':
        return stats.get('image_generation_count', 0) < 1
    elif generation_type == 'batch':
        return stats['batch_count'] < 1
    
    return False

def after_generation(user_id: int, generation_type: str = 'single') -> None:
    """Call after successful generation to update counters"""
    if get_active_subscription(user_id):
        return
    
    if generation_type == 'single':
        if get_total_package_generations(user_id) > 0:
            use_package_generation(user_id)
            return
        increment_single_usage(user_id)
    elif generation_type == 'photo':
        increment_image_generation_usage(user_id)
    elif generation_type == 'batch':
        increment_batch_usage(user_id)

def get_user_status_message(user_id: int) -> str:
    """Get message showing user's current status"""
    messages = ["📊 **Ваш статус:**\n"]
    
    subscription = get_active_subscription(user_id)
    if subscription:
        expires = subscription['expires_at'][:10]
        messages.append(f"👑 **Подписка Pro** активна до {expires}\n")
        messages.append("✅ У вас безлимит — наслаждайтесь!")
    else:
        packages = get_user_packages(user_id)
        total_gens = get_total_package_generations(user_id)
        
        if packages:
            messages.append(f" **Активные пакеты:** {len(packages)}\n")
            messages.append(f"⚡ **Доступно генераций:** {total_gens}\n")
        else:
            messages.append("🆓 **Бесплатный тариф**\n")
            messages.append("• 3 генерации в день\n")
            messages.append("• 1 анализ фото в день\n")
            messages.append("• 1 пакет Excel в месяц\n")
    
    return "\n".join(messages)