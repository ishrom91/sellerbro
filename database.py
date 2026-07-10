import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
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