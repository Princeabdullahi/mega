import os
import time
import random
import logging
import json
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Set, Optional, Union, Literal
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    ContextTypes,
    filters
)
from telegram.error import TelegramError

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
MINING_REWARD = float(os.getenv('MINING_REWARD', 100))
REFERRAL_REWARD = float(os.getenv('REFERRAL_REWARD', 50))
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '').split(',')]
SUSPICIOUS_THRESHOLD = int(os.getenv('SUSPICIOUS_THRESHOLD', 5))

# Constants for features
STREAK_BONUS = 2  # $MEGA per day of streak
MAX_STREAK_BONUS = 100  # Maximum streak bonus
LEVEL_THRESHOLD = 1000  # Amount needed to level up
LEVEL_BONUS_PERCENT = 0.1  # 10% bonus per level

# Achievement definitions
ACHIEVEMENTS = {
    'first_mine': {'name': '🎯 First Mine', 'description': 'Complete your first mining operation'},
    'mining_streak_7': {'name': '🔥 Week Warrior', 'description': 'Maintain a 7-day mining streak'},
    'referral_master': {'name': '🤝 Referral Master', 'description': 'Refer 5 active users'},
    'mega_miner': {'name': '⛏️ Mega Miner', 'description': 'Mine 1000 $MEGA tokens'},
    'early_bird': {'name': '🌅 Early Bird', 'description': 'Mine within the first hour of daily reset'}
}

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Add energy system constants
ENERGY_PLANS = {
    'max': {
        'price': 50,  # 50 Stars (XTR)
        'daily_limit': 50,  # 50 $MEGA per day
        'name': 'Max Energy',
        'description': '50 $MEGA mining limit per day'
    },
    'unlimited': {
        'price': 250,  # 250 Stars (XTR)
        'daily_limit': 150,  # 150 $MEGA per day
        'name': 'Unlimited Energy',
        'description': '150 $MEGA mining limit per day'
    }
}

class UserProfile:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.balance = 0
        self.total_mined = 0
        self.mining_count = 0
        self.referral_count = 0
        self.achievements: Set[str] = set()
        self.last_mine_time = None
        self.current_streak = 0
        self.highest_streak = 0
        self.last_daily_bonus = None
        self.referred_by = None
        self.energy_plan = None
        self.energy_expires = None

    def has_active_plan(self) -> bool:
        """Check if user has an active energy plan."""
        if not self.energy_plan or not self.energy_expires:
            return False
        return datetime.now() < self.energy_expires

    def get_daily_limit(self) -> float:
        """Get user's daily mining limit based on their energy plan."""
        if not self.has_active_plan():
            return 0
        return ENERGY_PLANS[self.energy_plan]['daily_limit']

    def get_plan_name(self) -> str:
        """Get user's current plan name."""
        if not self.has_active_plan():
            return "No Active Plan"
        return ENERGY_PLANS[self.energy_plan]['name']

    def get_remaining_time(self) -> str:
        """Get remaining time on current plan."""
        if not self.has_active_plan():
            return "No active plan"
        remaining = self.energy_expires - datetime.now()
        days = remaining.days
        hours = remaining.seconds // 3600
        minutes = (remaining.seconds % 3600) // 60
        return f"{days}d {hours}h {minutes}m"

# Store user data
user_profiles: Dict[int, UserProfile] = {}
user_actions = defaultdict(list)
suspended_users = set()

def format_time_remaining(seconds: int) -> str:
    """Format the remaining time in a human-readable format."""
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"

def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    return user_id in ADMIN_IDS

def check_bot_behavior(user_id: int) -> tuple[bool, float]:
    """Check if user behavior is suspicious (potential bot)."""
    current_time = time.time()
    user_actions[user_id] = [t for t in user_actions[user_id] if current_time - t < 60]
    actions_per_minute = len(user_actions[user_id])
    is_suspicious = actions_per_minute >= SUSPICIOUS_THRESHOLD
    return is_suspicious, actions_per_minute

def record_user_action(user_id: int):
    """Record a user action for bot detection."""
    user_actions[user_id].append(time.time())

def calculate_level(total_mined: float) -> int:
    """Calculate user's mining level based on total mined amount."""
    return int(total_mined / LEVEL_THRESHOLD)

def calculate_level_bonus(level: int) -> float:
    """Calculate mining bonus based on user level."""
    return level * LEVEL_BONUS_PERCENT

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to view statistics and admin commands."""
    user_id = update.effective_user.id
    admin_level = get_admin_level(user_id)
    
    if not admin_level:
        await update.message.reply_text("❌ This command is only available to administrators.")
        return

    # Regular stats
    total_users = len(user_profiles)
    current_time = datetime.now()
    active_users_24h = sum(1 for profile in user_profiles.values() 
                          if profile.last_mine_time and 
                          (current_time - profile.last_mine_time) < timedelta(hours=24))
    
    total_mined = sum(profile.total_mined for profile in user_profiles.values())
    total_referrals = sum(profile.referral_count for profile in user_profiles.values())
    suspicious_users = sum(1 for uid in user_profiles if check_bot_behavior(uid)[0])

    stats_message = (
        "📊 Admin Statistics 📊\n\n"
        f"👥 Total Users: {total_users}\n"
        f"✨ Active Users (24h): {active_users_24h}\n"
        f"💎 Total $MEGA Mined: {total_mined:.2f}\n"
        f"🤝 Total Referrals: {total_referrals}\n"
        f"⚠️ Suspicious Users: {suspicious_users}\n"
        f"🚫 Suspended Users: {len(suspended_users)}\n\n"
    )

    # Add admin commands section based on user's admin level
    stats_message += "🛠 Available Admin Commands:\n\n"
    
    for role, details in ADMIN_ROLES.items():
        if admin_level >= details['level']:
            stats_message += f"[{role.upper()}] Commands:\n"
            for cmd in details['commands']:
                stats_message += f"/{cmd}\n"
            stats_message += "\n"

    # Add command descriptions
    stats_message += (
        "📝 Command Usage:\n"
        "/add_admin <user_id> <role> - Add new admin (owner only)\n"
        "/remove_admin <user_id> - Remove admin (owner only)\n"
        "/config_set <param> <value> - Change bot settings\n"
        "/config_get - View current settings\n"
        "/announce <message> - Send message to all users\n"
        "/broadcast <target> <message> - Send targeted message\n"
        "/monitor_user <user_id> - Monitor specific user\n"
        "/suspend_user <user_id> - Suspend user\n"
        "/unsuspend_user <user_id> - Unsuspend user\n"
    )

    await update.message.reply_text(stats_message)

async def monitor_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to monitor specific user activity."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ This command is only available to administrators.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ Please provide a valid user ID to monitor.")
        return

    target_id = int(context.args[0])
    if target_id not in user_profiles:
        await update.message.reply_text("❌ User not found in database.")
        return

    profile = user_profiles[target_id]
    is_suspicious, actions_per_minute = check_bot_behavior(target_id)
    
    user_status = "🚫 Suspended" if target_id in suspended_users else "✅ Active"
    if is_suspicious:
        user_status = "⚠️ Suspicious"

    monitor_message = (
        f"👤 User Monitoring Report (ID: {target_id})\n\n"
        f"Status: {user_status}\n"
        f"Actions/minute: {actions_per_minute}\n"
        f"Total mined: {profile.total_mined:.2f} $MEGA\n"
        f"Mining count: {profile.mining_count}\n"
        f"Referrals: {profile.referral_count}\n"
        f"Balance: {profile.balance} $MEGA"
    )
    await update.message.reply_text(monitor_message)

async def suspend_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to suspend a user."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ This command is only available to administrators.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ Please provide a valid user ID to suspend.")
        return

    target_id = int(context.args[0])
    if target_id not in user_profiles:
        await update.message.reply_text("❌ User not found in database.")
        return

    suspended_users.add(target_id)
    await update.message.reply_text(f"✅ User {target_id} has been suspended.")
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text="⚠️ Your account has been suspended due to suspicious activity. Please contact support if you think this is a mistake."
        )
    except Exception as e:
        logger.error(f"Failed to notify suspended user: {e}")

async def unsuspend_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to unsuspend a user."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ This command is only available to administrators.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ Please provide a valid user ID to unsuspend.")
        return

    target_id = int(context.args[0])
    if target_id not in suspended_users:
        await update.message.reply_text("❌ User is not suspended.")
        return

    suspended_users.remove(target_id)
    await update.message.reply_text(f"✅ User {target_id} has been unsuspended.")
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text="✅ Your account has been unsuspended. You can now continue mining."
        )
    except Exception as e:
        logger.error(f"Failed to notify unsuspended user: {e}")

async def check_achievements(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check and award achievements for a user."""
    profile = user_profiles[user_id]
    new_achievements = []

    # Check achievements
    if profile.mining_count == 1 and 'first_mine' not in profile.achievements:
        profile.achievements.add('first_mine')
        new_achievements.append('first_mine')

    if profile.current_streak >= 7 and 'mining_streak_7' not in profile.achievements:
        profile.achievements.add('mining_streak_7')
        new_achievements.append('mining_streak_7')

    if profile.referral_count >= 5 and 'referral_master' not in profile.achievements:
        profile.achievements.add('referral_master')
        new_achievements.append('referral_master')

    if profile.total_mined >= 1000 and 'mega_miner' not in profile.achievements:
        profile.achievements.add('mega_miner')
        new_achievements.append('mega_miner')

    now = datetime.now()
    daily_reset = datetime(now.year, now.month, now.day).replace(hour=0, minute=0, second=0)
    if (now - daily_reset).total_seconds() <= 3600 and 'early_bird' not in profile.achievements:
        profile.achievements.add('early_bird')
        new_achievements.append('early_bird')

    # Notify user of new achievements
    for achievement_id in new_achievements:
        achievement = ACHIEVEMENTS[achievement_id]
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🏆 Achievement Unlocked!\n\n{achievement['name']}\n{achievement['description']}"
            )
        except Exception as e:
            logger.error(f"Failed to send achievement notification: {e}")

async def check_daily_streak(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check and update user's daily mining streak."""
    profile = user_profiles[user_id]
    now = datetime.now()
    
    if profile.last_mine_time:
        days_difference = (now - profile.last_mine_time).days
        
        if days_difference <= 1:  # Maintained streak
            profile.current_streak += 1
            profile.highest_streak = max(profile.current_streak, profile.highest_streak)
            
            # Bonus rewards for streak milestones
            if profile.current_streak % 7 == 0:  # Weekly milestone
                bonus = 50  # 50 $MEGA bonus every 7 days
                profile.balance += bonus
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🎉 Weekly Streak Bonus!\n"
                         f"You've maintained a {profile.current_streak}-day streak!\n"
                         f"Bonus: +{bonus} $MEGA"
                )
        else:  # Streak broken
            if profile.current_streak > 0:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"⚠️ Your {profile.current_streak}-day streak was broken!\n"
                         f"Keep mining daily to maintain your streak!"
                )
            profile.current_streak = 1

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    user_id = user.id
    
    if user_id in suspended_users:
        await update.message.reply_text("❌ Your account is suspended. Please contact support.")
        return
        
    record_user_action(user_id)
    
    # Handle referral
    referred_by = None
    if context.args and len(context.args) > 0:
        try:
            referred_by = int(context.args[0])
            if referred_by != user_id and referred_by in user_profiles:
                if user_id not in user_profiles:
                    # Give referral bonus to both users
                    referrer_profile = user_profiles[referred_by]
                    referrer_profile.balance += REFERRAL_REWARD
                    referrer_profile.referral_count += 1
                    
                    new_profile = UserProfile(user_id)
                    new_profile.balance = REFERRAL_REWARD
                    new_profile.referred_by = referred_by
                    user_profiles[user_id] = new_profile
                    
                    # Notify referrer
                    try:
                        await context.bot.send_message(
                            chat_id=referred_by,
                            text=f'🎉 New referral bonus! User {user.first_name} joined using your link!\n'
                                 f'You received {REFERRAL_REWARD} $MEGA!'
                        )
                    except Exception as e:
                        logger.error(f"Failed to send referral notification: {e}")
        except ValueError:
            pass

    if user_id not in user_profiles:
        user_profiles[user_id] = UserProfile(user_id)

    referral_link = f'https://t.me/{context.bot.username}?start={user_id}'
    
    await update.message.reply_text(
        f'Welcome {user.first_name} to the $MEGA Mining App! ⛏️\n\n'
        '🔨 Commands:\n'
        '⛏️ /mine - Mine $MEGA tokens (100 per 24h)\n'
        '💰 /balance - Check your balance\n'
        '📊 /stats - View your mining statistics\n'
        '👥 /referral - Get your referral link\n'
        '🏆 /achievements - View your achievements\n'
        '📈 /profile - View your detailed profile\n'
        '🏆 /leaderboard - View top miners\n\n'
        '⏱️ Mining cooldown: 24 hours\n'
        '🎁 Referral Reward: 50 $MEGA for both!\n\n'
        f'🔗 Your referral link:\n{referral_link}'
    )

async def mine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the mining process with energy plan requirement."""
    user_id = update.effective_user.id
    
    # Check if user is suspended
    if user_id in suspended_users:
        await update.message.reply_text("❌ Your account is suspended. Please contact support.")
        return

    # Initialize user profile if needed
    if user_id not in user_profiles:
        user_profiles[user_id] = UserProfile(user_id)

    profile = user_profiles[user_id]
    
    # Check if user has active energy plan
    if not profile.has_active_plan():
        keyboard = [[InlineKeyboardButton("🛍️ Purchase Energy", callback_data="open_shop")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "❌ You need an active energy plan to mine!\n"
            "Visit the shop to purchase one:",
            reply_markup=reply_markup
        )
        return

    # Record action for bot detection
    record_user_action(user_id)
    
    current_time = datetime.now()
    
    # Check mining cooldown
    if profile.last_mine_time and (current_time - profile.last_mine_time) < timedelta(hours=24):
        remaining_seconds = int((timedelta(hours=24) - (current_time - profile.last_mine_time)).total_seconds())
        time_str = format_time_remaining(remaining_seconds)
        progress = '🔴' * (remaining_seconds // 8640) + '⚪' * (10 - (remaining_seconds // 8640))
        
        await update.message.reply_text(
            f'⏳ Cooldown active!\n\n'
            f'Time remaining: {time_str}\n'
            f'Progress: {progress}\n\n'
            f'Current streak: {profile.current_streak} days 🔥'
        )
        return
    
    # Get daily mining limit based on energy plan
    daily_limit = profile.get_daily_limit()
    
    # Mining process
    bonus = daily_limit * 0.1 if random.random() < 0.1 else 0  # 10% chance for bonus
    streak_bonus = min((profile.current_streak * STREAK_BONUS), MAX_STREAK_BONUS) if profile.current_streak > 0 else 0
    level = calculate_level(profile.total_mined)
    level_bonus = calculate_level_bonus(level) * daily_limit
    
    total_reward = daily_limit + bonus + streak_bonus + level_bonus
    
    profile.balance += total_reward
    profile.total_mined += total_reward
    profile.mining_count += 1
    profile.last_mine_time = current_time

    # Check streak and achievements
    await check_daily_streak(user_id, context)
    await check_achievements(user_id, context)
    
    # Prepare bonus messages
    bonus_text = "🌟 BONUS! +10% Reward! 🌟\n" if bonus > 0 else ""
    streak_text = f"🔥 Streak Bonus: +{streak_bonus} $MEGA\n" if streak_bonus > 0 else ""
    level_text = f"⭐ Level {level} Bonus: +{level_bonus:.2f} $MEGA\n" if level_bonus > 0 else ""
    
    await update.message.reply_text(
        f'⛏️ Mining successful!\n{bonus_text}'
        f'💎 Base Reward: +{daily_limit} $MEGA\n'
        f'{streak_text}'
        f'{level_text}'
        f'💰 Total Reward: +{total_reward:.2f} $MEGA\n'
        f'Balance: {profile.balance:.2f} $MEGA\n\n'
        f'🔥 Current Streak: {profile.current_streak} days\n'
        f'⚡️ Energy Plan: {profile.get_plan_name()}\n'
        f'⏳ Come back in 24 hours to mine again!'
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check user's balance."""
    user_id = update.effective_user.id
    if user_id not in user_profiles:
        await update.message.reply_text('💰 You haven\'t mined any $MEGA yet!\nUse /mine to start mining!')
        return
    
    profile = user_profiles[user_id]
    await update.message.reply_text(
        f'💰 Your Wallet:\n'
        f'Balance: {profile.balance:.2f} $MEGA'
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's mining statistics."""
    user_id = update.effective_user.id
    if user_id not in user_profiles:
        await update.message.reply_text('📊 No mining statistics available yet!\nUse /mine to start mining!')
        return
    
    profile = user_profiles[user_id]
    avg_per_mine = profile.total_mined / profile.mining_count if profile.mining_count > 0 else 0
    
    await update.message.reply_text(
        f'📊 Mining Statistics 📊\n\n'
        f'💎 Total mined: {profile.total_mined:.2f} $MEGA\n'
        f'⛏️ Times mined: {profile.mining_count}\n'
        f'📈 Average per mine: {avg_per_mine:.2f} $MEGA\n'
        f'👥 Referrals: {profile.referral_count}\n'
        f'💰 Current balance: {profile.balance:.2f} $MEGA'
    )

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's referral link and info."""
    user_id = update.effective_user.id
    referral_link = f'https://t.me/{context.bot.username}?start={user_id}'
    
    profile = user_profiles.get(user_id, UserProfile(user_id))
    total_earned = profile.referral_count * REFERRAL_REWARD
    
    await update.message.reply_text(
        f'👥 Referral Program\n\n'
        f'🎁 Earn {REFERRAL_REWARD} $MEGA for each friend you invite!\n'
        f'Your friend will also receive {REFERRAL_REWARD} $MEGA!\n\n'
        f'Stats:\n'
        f'👤 Total referrals: {profile.referral_count}\n'
        f'💰 Total earned: {total_earned} $MEGA\n\n'
        f'🔗 Your referral link:\n{referral_link}'
    )

async def get_leaderboard(timeframe: str = 'daily') -> str:
    """Generate leaderboard for specified timeframe."""
    now = datetime.now()
    if timeframe == 'daily':
        start_time = datetime(now.year, now.month, now.day)
    else:  # weekly
        start_time = now - timedelta(days=now.weekday())
        start_time = datetime(start_time.year, start_time.month, start_time.day)

    # Filter and sort users based on mining activity in the timeframe
    leaderboard_data = []
    for user_id, profile in user_profiles.items():
        if profile.last_mine_time and profile.last_mine_time >= start_time:
            leaderboard_data.append((user_id, profile.total_mined))

    leaderboard_data.sort(key=lambda x: x[1], reverse=True)
    leaderboard_data = leaderboard_data[:10]  # Top 10 only

    timeframe_text = "Daily" if timeframe == 'daily' else "Weekly"
    message = f"🏆 {timeframe_text} Leaderboard 🏆\n\n"
    
    for idx, (user_id, mined) in enumerate(leaderboard_data, 1):
        medal = {1: '🥇', 2: '🥈', 3: '🥉'}.get(idx, f'{idx}.')
        message += f"{medal} User{user_id}: {mined:.2f} $MEGA\n"

    return message

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show daily or weekly leaderboard."""
    timeframe = 'daily'
    if context.args and context.args[0].lower() == 'weekly':
        timeframe = 'weekly'
    
    message = await get_leaderboard(timeframe)
    await update.message.reply_text(message)

async def achievements(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's achievements."""
    user_id = update.effective_user.id
    if user_id not in user_profiles:
        await update.message.reply_text("You haven't started mining yet! Use /mine to begin.")
        return

    profile = user_profiles[user_id]
    message = "🏆 Your Achievements 🏆\n\n"
    
    for achievement_id, achievement in ACHIEVEMENTS.items():
        status = "✅" if achievement_id in profile.achievements else "🔒"
        message += f"{status} {achievement['name']}\n{achievement['description']}\n\n"

    await update.message.reply_text(message)

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's detailed profile."""
    user_id = update.effective_user.id
    if user_id not in user_profiles:
        await update.message.reply_text("You haven't started mining yet! Use /mine to begin.")
        return

    profile = user_profiles[user_id]
    message = (
        f"👤 User Profile\n\n"
        f"💰 Balance: {profile.balance} $MEGA\n"
        f"⛏️ Total Mined: {profile.total_mined} $MEGA\n"
        f"🔄 Mining Count: {profile.mining_count}\n"
        f"🤝 Referrals: {profile.referral_count}\n"
        f"🏆 Achievements: {len(profile.achievements)}/{len(ACHIEVEMENTS)}\n"
        f"🔥 Current Streak: {profile.current_streak} days\n"
        f"📈 Highest Streak: {profile.highest_streak} days"
    )
    await update.message.reply_text(message)

# Add config management
BOT_CONFIG = {
    'mining_reward': MINING_REWARD,
    'referral_reward': REFERRAL_REWARD,
    'streak_bonus': STREAK_BONUS,
    'max_streak_bonus': MAX_STREAK_BONUS,
    'level_threshold': LEVEL_THRESHOLD,
    'level_bonus_percent': LEVEL_BONUS_PERCENT,
    'suspicious_threshold': SUSPICIOUS_THRESHOLD
}

async def config_get(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to view current configuration."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ This command is only available to administrators.")
        return
    
    config_message = "⚙️ Current Bot Configuration:\n\n"
    for key, value in BOT_CONFIG.items():
        config_message += f"{key}: {value}\n"
    
    await update.message.reply_text(config_message)

async def config_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to modify configuration."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ This command is only available to administrators.")
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "❌ Invalid format. Use:\n"
            "/config_set <parameter> <value>\n\n"
            "Available parameters:\n" +
            "\n".join(BOT_CONFIG.keys())
        )
        return

    param, value = context.args
    if param not in BOT_CONFIG:
        await update.message.reply_text(f"❌ Unknown parameter: {param}")
        return

    try:
        BOT_CONFIG[param] = float(value)
        # Update global variables
        globals()[param.upper()] = float(value)
        await update.message.reply_text(f"✅ Updated {param} to {value}")
    except ValueError:
        await update.message.reply_text("❌ Value must be a number")

async def announce(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to send announcement to all users."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ This command is only available to administrators.")
        return

    if not context.args:
        await update.message.reply_text(
            "❌ Please provide an announcement message.\n"
            "Usage: /announce <message>"
        )
        return

    announcement = " ".join(context.args)
    failed_users = 0
    success_users = 0

    for user_id in user_profiles:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📢 ANNOUNCEMENT\n\n{announcement}"
            )
            success_users += 1
        except Exception as e:
            failed_users += 1
            logger.error(f"Failed to send announcement to user {user_id}: {e}")

    await update.message.reply_text(
        f"📢 Announcement sent!\n\n"
        f"✅ Successfully sent to: {success_users} users\n"
        f"❌ Failed to send to: {failed_users} users"
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to send targeted announcement based on user criteria."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ This command is only available to administrators.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Invalid format. Use:\n"
            "/broadcast <target> <message>\n\n"
            "Targets:\n"
            "active - Users active in last 24h\n"
            "inactive - Users inactive for 24h+\n"
            "whales - Users with high balance\n"
            "new - Users joined in last 7 days"
        )
        return

    target = context.args[0].lower()
    message = " ".join(context.args[1:])
    current_time = datetime.now()
    
    # Filter users based on target criteria
    target_users = set()
    
    if target == "active":
        target_users = {uid for uid, profile in user_profiles.items()
                       if profile.last_mine_time and (current_time - profile.last_mine_time) < timedelta(hours=24)}
    elif target == "inactive":
        target_users = {uid for uid, profile in user_profiles.items()
                       if not profile.last_mine_time or (current_time - profile.last_mine_time) >= timedelta(hours=24)}
    elif target == "whales":
        avg_balance = sum(p.balance for p in user_profiles.values()) / len(user_profiles) if user_profiles else 0
        target_users = {uid for uid, profile in user_profiles.items()
                       if profile.balance > avg_balance * 2}  # Users with 2x average balance
    elif target == "new":
        target_users = {uid for uid, profile in user_profiles.items()
                       if profile.mining_count <= 7}  # Users with 7 or fewer mining operations
    else:
        await update.message.reply_text("❌ Invalid target group")
        return

    if not target_users:
        await update.message.reply_text("❌ No users match the target criteria")
        return

    failed_users = 0
    success_users = 0

    for user_id in target_users:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📢 TARGETED ANNOUNCEMENT\n\n{message}"
            )
            success_users += 1
        except Exception as e:
            failed_users += 1
            logger.error(f"Failed to send broadcast to user {user_id}: {e}")

    await update.message.reply_text(
        f"📢 Targeted broadcast sent!\n\n"
        f"Target group: {target}\n"
        f"✅ Successfully sent to: {success_users} users\n"
        f"❌ Failed to send to: {failed_users} users"
    )

# Add admin roles
ADMIN_ROLES = {
    'owner': {'level': 3, 'commands': ['add_admin', 'remove_admin', 'config_set']},
    'admin': {'level': 2, 'commands': ['announce', 'broadcast', 'suspend_user', 'unsuspend_user']},
    'moderator': {'level': 1, 'commands': ['monitor_user', 'config_get']}
}

class AdminUser:
    def __init__(self, user_id: int, role: str = 'moderator'):
        self.user_id = user_id
        self.role = role
        self.added_by = None
        self.added_at = datetime.now()

# Store admin users
admin_users: Dict[int, AdminUser] = {}

def get_admin_level(user_id: int) -> int:
    """Get admin level for a user. 0 means not admin."""
    if user_id not in admin_users:
        return 0
    return ADMIN_ROLES[admin_users[user_id].role]['level']

def is_admin(user_id: int, required_level: int = 1) -> bool:
    """Check if user is admin with required level."""
    return get_admin_level(user_id) >= required_level

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a new admin or moderator."""
    user_id = update.effective_user.id
    if not is_admin(user_id, 3):  # Only owner can add admins
        await update.message.reply_text("❌ This command is only available to the owner.")
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "❌ Invalid format. Use:\n"
            "/add_admin <user_id> <role>\n\n"
            "Available roles:\n"
            "- admin\n"
            "- moderator"
        )
        return

    target_id = int(context.args[0])
    role = context.args[1].lower()

    if role not in ADMIN_ROLES or role == 'owner':
        await update.message.reply_text("❌ Invalid role specified.")
        return

    new_admin = AdminUser(target_id, role)
    new_admin.added_by = user_id
    admin_users[target_id] = new_admin

    await update.message.reply_text(
        f"✅ Successfully added new {role}!\n"
        f"User ID: {target_id}"
    )

    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"🎉 Congratulations! You have been promoted to {role}!\n"
                 f"Use /admin_stats to see available commands."
        )
    except Exception as e:
        logger.error(f"Failed to notify new admin: {e}")

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove an admin or moderator."""
    user_id = update.effective_user.id
    if not is_admin(user_id, 3):  # Only owner can remove admins
        await update.message.reply_text("❌ This command is only available to the owner.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "❌ Invalid format. Use:\n"
            "/remove_admin <user_id>"
        )
        return

    target_id = int(context.args[0])
    if target_id not in admin_users:
        await update.message.reply_text("❌ User is not an admin.")
        return

    if admin_users[target_id].role == 'owner':
        await update.message.reply_text("❌ Cannot remove owner.")
        return

    removed_role = admin_users[target_id].role
    del admin_users[target_id]

    await update.message.reply_text(
        f"✅ Successfully removed {removed_role}!\n"
        f"User ID: {target_id}"
    )

    try:
        await context.bot.send_message(
            chat_id=target_id,
            text="You have been removed from the admin team."
        )
    except Exception as e:
        logger.error(f"Failed to notify removed admin: {e}")

# Add task management system
class Task:
    def __init__(self, task_id: int, title: str, description: str, link: str, display_text: str, reward: float = 50.0):
        self.task_id = task_id
        self.title = title
        self.description = description
        self.link = link
        self.display_text = display_text
        self.reward = reward
        self.created_at = datetime.now()
        self.completed_by: Set[int] = set()
        # Extract channel username or ID from the link
        try:
            if 't.me/' in link:
                self.channel_id = link.split('t.me/')[-1].split('/')[-1]
            else:
                self.channel_id = link.split('/')[-1]
            # Remove any parameters
            self.channel_id = self.channel_id.split('?')[0]
        except:
            self.channel_id = None

# Store tasks
tasks: Dict[int, Task] = {}
next_task_id = 1

async def verify_channel_membership(bot, user_id: int, channel_id: str) -> bool:
    """Verify if user is a member of the channel."""
    try:
        # Clean up channel_id - remove any @ symbol and handle full URLs
        if 't.me/' in channel_id:
            channel_id = channel_id.split('t.me/')[-1]
        channel_id = channel_id.replace('@', '')
        
        # First try with @ prefix
        try:
            member = await bot.get_chat_member(chat_id=f"@{channel_id}", user_id=user_id)
        except TelegramError:
            # If that fails, try with -100 prefix for channel ID
            try:
                if not channel_id.startswith('-100'):
                    channel_id = f"-100{channel_id}"
                member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            except TelegramError as e:
                logger.error(f"Error checking channel membership with ID: {e}")
                return False

        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error in verify_channel_membership: {e}")
        return False

async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to add a new task."""
    user_id = update.effective_user.id
    if not is_admin(user_id, 2):
        await update.message.reply_text("❌ This command is only available to administrators.")
        return

    try:
        # Join args and split by quotes to handle spaces in text
        full_text = " ".join(context.args)
        parts = full_text.split('"')
        parts = [p.strip() for p in parts if p.strip()]
        
        if len(parts) < 4:
            raise ValueError("Missing required parameters")
        
        title = parts[0]
        description = parts[1]
        link = parts[2]
        display_text = parts[3]
        reward = float(parts[4]) if len(parts) > 4 else 50.0

        # Extract channel ID
        channel_id = None
        if 't.me/' in link:
            channel_id = link.split('t.me/')[-1].split('/')[-1].split('?')[0]
            channel_id = channel_id.replace('@', '')

            # Validate channel
            try:
                # Try with @ prefix first
                try:
                    chat = await context.bot.get_chat(f"@{channel_id}")
                except TelegramError:
                    # If that fails, try with -100 prefix
                    if not channel_id.startswith('-100'):
                        chat = await context.bot.get_chat(f"-100{channel_id}")
                    else:
                        chat = await context.bot.get_chat(channel_id)

                if chat.type not in ['channel', 'supergroup']:
                    await update.message.reply_text("❌ The provided link is not a valid Telegram channel or group.")
                    return

                # Test bot's permissions
                bot_member = await chat.get_member(context.bot.id)
                if not bot_member.can_read_messages:
                    await update.message.reply_text(
                        "❌ Bot doesn't have sufficient permissions in the channel.\n"
                        "Please make sure to add the bot as an admin with at least:\n"
                        "- Read Messages permission"
                    )
                    return

            except TelegramError as e:
                await update.message.reply_text(
                    "❌ Could not verify channel. Make sure:\n"
                    "1. The link is correct\n"
                    "2. The bot is added as admin to the channel\n"
                    "3. The channel exists and is public\n"
                    f"Error: {str(e)}"
                )
                return

        global next_task_id
        task = Task(next_task_id, title, description, link, display_text, reward)
        tasks[next_task_id] = task
        next_task_id += 1

        # Test channel verification
        if channel_id:
            is_bot_member = await verify_channel_membership(context.bot, context.bot.id, channel_id)
            verification_status = "✅ Channel verification working" if is_bot_member else "⚠️ Channel verification might have issues"
        else:
            verification_status = "ℹ️ No channel verification needed"

        await update.message.reply_text(
            f"✅ Task added successfully!\n\n"
            f"ID: {task.task_id}\n"
            f"Title: {task.title}\n"
            f"Reward: {task.reward} $MEGA\n"
            f"Channel ID: {channel_id}\n"
            f"{verification_status}\n\n"
            f"Preview:\n{task.description}\n"
            f"Link will show as: {task.display_text}"
        )
    except Exception as e:
        await update.message.reply_text(
            "❌ Invalid format. Use:\n"
            '/add_task "Task Title" "Task Description" "channel_link" "Display Text" reward\n'
            "Example:\n"
            '/add_task "Join Channel" "Join our news channel" "https://t.me/channel" "Click here to join" 100\n\n'
            "Note: For Telegram channels, make sure to:\n"
            "1. Add the bot as an admin to the channel\n"
            "2. Use a public channel link"
        )
        logger.error(f"Error in add_task: {e}")

async def remove_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to remove a task."""
    user_id = update.effective_user.id
    if not is_admin(user_id, 2):
        await update.message.reply_text("❌ This command is only available to administrators.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ Please provide a valid task ID.")
        return

    task_id = int(context.args[0])
    if task_id not in tasks:
        await update.message.reply_text("❌ Task not found.")
        return

    del tasks[task_id]
    await update.message.reply_text(f"✅ Task {task_id} has been removed.")

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show available tasks to users."""
    user_id = update.effective_user.id
    if not tasks:
        await update.message.reply_text("📝 No tasks available at the moment.")
        return

    profile = user_profiles.get(user_id, UserProfile(user_id))
    message = "📋 Available Tasks\n\n"

    for task_id, task in tasks.items():
        status = "✅ Completed" if user_id in task.completed_by else "⏳ Available"
        message += (
            f"Task #{task_id}: {task.title}\n"
            f"Status: {status}\n"
            f"Reward: {task.reward} $MEGA\n"
            f"Description: {task.description}\n"
            f"{task.display_text} (/task_{task_id})\n\n"
        )

    await update.message.reply_text(message)

async def task_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle task completion."""
    user_id = update.effective_user.id
    command = update.message.text.lower()
    
    if not command.startswith("/task_"):
        return
    
    try:
        task_id = int(command.split("_")[1])
    except (IndexError, ValueError):
        return

    if task_id not in tasks:
        await update.message.reply_text("❌ This task no longer exists.")
        return

    task = tasks[task_id]
    
    if user_id in task.completed_by:
        await update.message.reply_text("❌ You have already completed this task.")
        return

    # Initialize user profile if needed
    if user_id not in user_profiles:
        user_profiles[user_id] = UserProfile(user_id)

    # Send the actual link as a separate message
    await update.message.reply_text(
        f"🔗 Here's your task link:\n{task.link}\n\n"
        "Complete the task and click the button below to claim your reward."
    )

    # Create inline keyboard for verification
    keyboard = [
        [InlineKeyboardButton("✅ I've completed the task", callback_data=f"verify_{task_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Click below once you've completed the task:",
        reply_markup=reply_markup
    )

async def verify_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Verify task completion and award rewards."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    task_id = int(query.data.split("_")[1])
    
    if task_id not in tasks:
        await query.edit_message_text("❌ This task no longer exists.")
        return
    
    task = tasks[task_id]
    
    if user_id in task.completed_by:
        await query.edit_message_text("❌ You have already completed this task.")
        return
    
    # Verify channel membership if it's a channel link
    if task.channel_id:
        is_member = await verify_channel_membership(context.bot, user_id, task.channel_id)
        if not is_member:
            await query.edit_message_text(
                "❌ Verification failed!\n"
                "Please make sure you've joined the channel before claiming the reward.\n"
                f"Channel link: {task.link}\n"
                f"Channel ID: {task.channel_id}\n\n"
                "Click the button again after joining!"
            )
            return
    
    # Award the reward
    profile = user_profiles.get(user_id, UserProfile(user_id))
    profile.balance += task.reward
    task.completed_by.add(user_id)
    
    await query.edit_message_text(
        f"✅ Task completed!\n"
        f"Verification successful!\n"
        f"You earned {task.reward} $MEGA\n"
        f"New balance: {profile.balance} $MEGA"
    )

async def task_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to view task statistics."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ This command is only available to administrators.")
        return

    if not tasks:
        await update.message.reply_text("📝 No tasks have been created yet.")
        return

    message = "📊 Task Statistics\n\n"
    
    for task_id, task in tasks.items():
        completion_rate = len(task.completed_by) / len(user_profiles) * 100 if user_profiles else 0
        total_paid = task.reward * len(task.completed_by)
        
        message += (
            f"Task #{task_id}: {task.title}\n"
            f"Completions: {len(task.completed_by)}\n"
            f"Completion Rate: {completion_rate:.1f}%\n"
            f"Total Paid: {total_paid} $MEGA\n\n"
        )

    await update.message.reply_text(message)

# Update help command to include task commands
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help message."""
    is_admin_user = is_admin(update.effective_user.id)
    
    help_text = (
        "📚 Available Commands:\n\n"
        "User Commands:\n"
        "/start - Start the bot\n"
        "/mine - Mine $MEGA tokens\n"
        "/balance - Check your balance\n"
        "/stats - View your statistics\n"
        "/referral - Get your referral link\n"
        "/achievements - View your achievements\n"
        "/profile - View your detailed profile\n"
        "/leaderboard - View top miners\n"
        "/tasks - View available tasks\n\n"
    )
    
    if is_admin_user:
        help_text += (
            "Admin Commands:\n"
            "/admin_stats - View admin statistics\n"
            "/add_task - Add a new task\n"
            "/remove_task - Remove a task\n"
            "/task_stats - View task statistics\n"
            "... and more admin commands\n"
        )
    
    await update.message.reply_text(help_text)

async def energy_shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show energy shop with available plans."""
    keyboard = []
    for plan_id, plan in ENERGY_PLANS.items():
        keyboard.append([
            InlineKeyboardButton(
                f"{plan['name']} - {plan['price']} ⭐️",
                callback_data=f"buy_energy_{plan_id}"
            )
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = (
        "⚡️ Energy Shop ⚡️\n\n"
        "Purchase energy to mine $MEGA!\n\n"
        "Available Plans:\n"
    )
    
    for plan_id, plan in ENERGY_PLANS.items():
        message += ( 
            f"\n{plan['name']}\n"
            f"💫 Price: {plan['price']} Stars\n"
            f"⛏️ Mining Limit: {plan['daily_limit']} $MEGA/day\n"
            f"📝 {plan['description']}\n"
        )

    message += "\nClick a plan below to purchase:"
    
    await update.message.reply_text(message, reply_markup=reply_markup)

async def handle_energy_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle energy plan purchase with Telegram Stars."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    plan_id = query.data.split('_')[2]
    
    if plan_id not in ENERGY_PLANS:
        await query.edit_message_text("❌ Invalid plan selected.")
        return
    
    plan = ENERGY_PLANS[plan_id]
    
    # Create the invoice
    title = f"Purchase {plan['name']}"
    description = f"{plan['description']}\nPay with Telegram Stars"
    payload = f"energy_plan_{plan_id}_{user_id}"  # Include user_id for referral tracking
    currency = "XTR"  # Telegram Stars currency code
    prices = [LabeledPrice(label=plan['name'], amount=plan['price'] * 100)]  # Amount in cents
    
    try:
        await context.bot.send_invoice(
            chat_id=user_id,
            title=title,
            description=description,
            payload=payload,
            provider_token=os.getenv('PROVIDER_TOKEN'),
            currency=currency,
            prices=prices,
            need_shipping_address=False,
            is_flexible=False,
            start_parameter=f"energy_{plan_id}"
        )
        await query.edit_message_text(
            f"💫 Purchase {plan['name']}\n\n"
            f"Please complete the payment process using Telegram Stars."
        )
    except Exception as e:
        logger.error(f"Failed to send invoice: {e}")
        await query.edit_message_text(
            "❌ Failed to create payment. Please try again later or contact support."
        )

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the pre-checkout callback for Star payments."""
    query = update.pre_checkout_query
    
    try:
        payload_parts = query.invoice_payload.split('_')
        plan_id = payload_parts[2]
        
        if plan_id not in ENERGY_PLANS:
            await query.answer(ok=False, error_message="Invalid plan selected.")
            return
        
        # Everything is fine, proceed with payment
        await query.answer(ok=True)
    except Exception as e:
        logger.error(f"Error in pre-checkout: {e}")
        await query.answer(ok=False, error_message="Something went wrong with the payment.")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle successful Star payments and process referral bonus."""
    payment = update.message.successful_payment
    user_id = update.effective_user.id
    
    try:
        payload_parts = payment.invoice_payload.split('_')
        plan_id = payload_parts[2]
        
        if plan_id not in ENERGY_PLANS:
            logger.error(f"Invalid plan ID in payment: {plan_id}")
            return
        
        # Initialize or get user profile
        if user_id not in user_profiles:
            user_profiles[user_id] = UserProfile(user_id)
        
        profile = user_profiles[user_id]
        
        # Update user's energy plan
        profile.energy_plan = plan_id
        profile.energy_expires = datetime.now() + timedelta(days=30)  # Plan lasts 30 days
        
        # Process referral bonus if user was referred
        if profile.referred_by and profile.referred_by in user_profiles:
            referrer_profile = user_profiles[profile.referred_by]
            bonus_amount = ENERGY_PLANS[plan_id]['price'] * 0.10  # 10% referral bonus
            referrer_profile.balance += bonus_amount
            
            # Notify referrer about the bonus
            try:
                await context.bot.send_message(
                    chat_id=profile.referred_by,
                    text=f"🎉 Referral Bonus!\n\n"
                         f"Your referred user purchased {ENERGY_PLANS[plan_id]['name']}!\n"
                         f"You earned {bonus_amount} $MEGA as referral bonus!"
                )
            except Exception as e:
                logger.error(f"Failed to send referral bonus notification: {e}")
        
        await update.message.reply_text(
            f"✅ Payment successful!\n\n"
            f"Plan: {ENERGY_PLANS[plan_id]['name']}\n"
            f"Daily Mining Limit: {ENERGY_PLANS[plan_id]['daily_limit']} $MEGA\n"
            f"Expires in: 30 days\n\n"
            f"You can now start mining with /mine command!"
        )
    except Exception as e:
        logger.error(f"Error processing successful payment: {e}")
        await update.message.reply_text("❌ Error processing payment. Please contact support.")

async def energy_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's current energy plan status."""
    user_id = update.effective_user.id
    
    if user_id not in user_profiles:
        await update.message.reply_text(
            "❌ You don't have an active energy plan.\n"
            "Use /energy_shop to purchase one!"
        )
        return
    
    profile = user_profiles[user_id]
    
    if not profile.has_active_plan():
        keyboard = [[InlineKeyboardButton("🛍️ Visit Shop", callback_data="open_shop")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "❌ You don't have an active energy plan.\n"
            "Purchase one to start mining!",
            reply_markup=reply_markup
        )
        return
    
    message = (
        "⚡️ Energy Status ⚡️\n\n"
        f"Current Plan: {profile.get_plan_name()}\n"
        f"Daily Mining Limit: {profile.get_daily_limit()} $MEGA\n"
        f"Time Remaining: {profile.get_remaining_time()}\n"
    )
    
    keyboard = [[InlineKeyboardButton("🔄 Renew Plan", callback_data="open_shop")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(message, reply_markup=reply_markup)

def main() -> None:
    """Start the bot with energy system."""
    if not BOT_TOKEN:
        logger.error("No bot token provided! Add your bot token to .env file")
        return

    # Initialize owner as admin
    owner_id = int(os.getenv('ADMIN_IDS', '0'))
    if owner_id:
        owner = AdminUser(owner_id, 'owner')
        admin_users[owner_id] = owner

    application = Application.builder().token(BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("mine", mine))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("referral", referral))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("achievements", achievements))
    application.add_handler(CommandHandler("profile", profile))
    
    # Add admin command handlers
    application.add_handler(CommandHandler("admin_stats", admin_stats))
    application.add_handler(CommandHandler("monitor", monitor_user))
    application.add_handler(CommandHandler("suspend", suspend_user))
    application.add_handler(CommandHandler("unsuspend", unsuspend_user))
    application.add_handler(CommandHandler("config_get", config_get))
    application.add_handler(CommandHandler("config_set", config_set))
    application.add_handler(CommandHandler("announce", announce))
    application.add_handler(CommandHandler("broadcast", broadcast))

    # Add new admin handlers
    application.add_handler(CommandHandler("add_admin", add_admin))
    application.add_handler(CommandHandler("remove_admin", remove_admin))

    # Add task system handlers
    application.add_handler(CommandHandler("add_task", add_task))
    application.add_handler(CommandHandler("remove_task", remove_task))
    application.add_handler(CommandHandler("tasks", list_tasks))
    application.add_handler(CommandHandler("task_stats", task_stats))
    application.add_handler(CommandHandler("help", help_command))
    
    # Add task completion handlers
    application.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r"^/task_\d+$"), task_handler))
    application.add_handler(CallbackQueryHandler(verify_task, pattern=r"^verify_\d+$"))

    # Add energy system handlers
    application.add_handler(CommandHandler("energy_shop", energy_shop))
    application.add_handler(CommandHandler("energy_status", energy_status))
    application.add_handler(CallbackQueryHandler(handle_energy_purchase, pattern=r"^buy_energy_"))
    application.add_handler(CallbackQueryHandler(energy_shop, pattern="open_shop"))
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    logger.info("Bot started successfully! Use Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()