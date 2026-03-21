import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
import pytz
from dotenv import load_dotenv
import requests

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
    JobQueue,
)

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
REFLECTLY_API_KEY = os.getenv('REFLECTLY_API_KEY')  # Optional - for future integration
USER_TIMEZONE = pytz.timezone('Europe/London')
DAILY_REMINDER_HOUR = 7  # 7 AM
DAILY_REMINDER_MINUTE = 0

# Conversation states
WAITING_FOR_BIBLE_PASSAGE = 1
WAITING_FOR_SOUND_CONCEPT = 2
WAITING_FOR_REFLECTION_TYPE = 3
WAITING_FOR_REFLECTION_CONTENT = 4
WAITING_FOR_LEARNING_LOG = 5

# User data storage (in production, use a database)
user_data: Dict = {}

# ==================== REFLECTLY INTEGRATION ====================

def send_to_reflectly(user_id: int, entry_text: str, tags: list = None) -> bool:
    """
    Send a reflection entry to Reflectly via email integration.
    Note: Direct API integration requires Reflectly API access.
    For now, we'll store locally and provide instructions for manual sync.
    """
    if not tags:
        tags = []
    
    # Store locally with timestamp
    timestamp = datetime.now(USER_TIMEZONE).isoformat()
    entry = {
        "timestamp": timestamp,
        "content": entry_text,
        "tags": tags,
        "type": "bot_logged"
    }
    
    if user_id not in user_data:
        user_data[user_id] = {}
    
    if "reflections" not in user_data[user_id]:
        user_data[user_id]["reflections"] = []
    
    user_data[user_id]["reflections"].append(entry)
    
    # Save to file for persistence
    save_user_data(user_id)
    return True


def save_user_data(user_id: int):
    """Save user data to a local JSON file"""
    filepath = f"/home/claude/{user_id}_learning_data.json"
    try:
        with open(filepath, 'w') as f:
            json.dump(user_data.get(user_id, {}), f, indent=2)
    except Exception as e:
        logger.error(f"Error saving user data for {user_id}: {e}")


def load_user_data(user_id: int):
    """Load user data from local JSON file"""
    filepath = f"/home/claude/{user_id}_learning_data.json"
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                user_data[user_id] = json.load(f)
        else:
            user_data[user_id] = {
                "bible_streak": 0,
                "sound_desk_streak": 0,
                "last_bible_date": None,
                "last_sound_desk_date": None,
                "current_bible_plan": [],
                "current_sound_concepts": [],
                "reflections": [],
            }
        return user_data[user_id]
    except Exception as e:
        logger.error(f"Error loading user data for {user_id}: {e}")
        return {}


# ==================== STREAK TRACKING ====================

def update_streak(user_id: int, learning_type: str):
    """Update streak for Bible or Sound Desk learning"""
    data = load_user_data(user_id)
    today = datetime.now(USER_TIMEZONE).date()
    
    if learning_type == "bible":
        last_date_str = data.get("last_bible_date")
        last_date = datetime.fromisoformat(last_date_str).date() if last_date_str else None
        
        if last_date == today:
            return data["bible_streak"]  # Already logged today
        elif last_date == today - timedelta(days=1):
            data["bible_streak"] += 1  # Continue streak
        else:
            data["bible_streak"] = 1  # Start new streak
        
        data["last_bible_date"] = today.isoformat()
    
    elif learning_type == "sound_desk":
        last_date_str = data.get("last_sound_desk_date")
        last_date = datetime.fromisoformat(last_date_str).date() if last_date_str else None
        
        if last_date == today:
            return data["sound_desk_streak"]  # Already logged today
        elif last_date == today - timedelta(days=1):
            data["sound_desk_streak"] += 1  # Continue streak
        else:
            data["sound_desk_streak"] = 1  # Start new streak
        
        data["last_sound_desk_date"] = today.isoformat()
    
    user_data[user_id] = data
    save_user_data(user_id)
    return data.get(f"{learning_type}_streak", 0)


# ==================== COMMAND HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command - initialize bot"""
    user_id = update.effective_user.id
    load_user_data(user_id)
    
    keyboard = [
        [InlineKeyboardButton("📖 Bible Reading", callback_data='bible_main')],
        [InlineKeyboardButton("🎛️ Sound Desk Learning", callback_data='sound_main')],
        [InlineKeyboardButton("📊 View Progress", callback_data='view_progress')],
        [InlineKeyboardButton("⚙️ Settings", callback_data='settings')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎯 **Learning Streak Tracker**\n\n"
        "Track your Bible reading and sound desk mastery journey.\n\n"
        "What would you like to do?",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def bible_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bible reading main menu"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = load_user_data(user_id)
    
    streak = data.get("bible_streak", 0)
    
    keyboard = [
        [InlineKeyboardButton("✅ Log Bible Reading", callback_data='bible_log')],
        [InlineKeyboardButton("📝 Plan Next Week", callback_data='bible_plan_week')],
        [InlineKeyboardButton("📚 View Current Plan", callback_data='bible_view_plan')],
        [InlineKeyboardButton("🔙 Back", callback_data='main_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"📖 **Bible Reading**\n\n"
        f"Current Streak: 🔥 **{streak} days**\n\n"
        f"What would you like to do?",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def bible_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log Bible reading completion"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    context.user_data['action'] = 'bible_log'
    
    keyboard = [
        [InlineKeyboardButton("Just log completion ✅", callback_data='bible_log_quick')],
        [InlineKeyboardButton("Log + Reflect 💭", callback_data='bible_log_reflect')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📖 **Log Bible Reading**\n\n"
        "How would you like to log your reading?",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def bible_log_quick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick log without reflection"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    streak = update_streak(user_id, "bible")
    data = load_user_data(user_id)
    
    passage = data.get("current_bible_plan", ["No passage set"])[0]
    
    await query.edit_message_text(
        f"✅ **Bible Reading Logged!**\n\n"
        f"🔥 Streak: **{streak} days**\n"
        f"📖 Today's reading: {passage}\n\n"
        f"Great job staying consistent! 🙌",
        parse_mode='Markdown'
    )


async def bible_log_reflect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log with reflection using IBA method"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    context.user_data['learning_type'] = 'bible'
    context.user_data['reflection_method'] = 'iba'
    
    keyboard = [
        [InlineKeyboardButton("Identify (Key Points)", callback_data='reflect_identify')],
        [InlineKeyboardButton("Breakdown (Definitions)", callback_data='reflect_breakdown')],
        [InlineKeyboardButton("Apply (Personal Application)", callback_data='reflect_apply')],
        [InlineKeyboardButton("Free Reflection", callback_data='reflect_free')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "💭 **Reflection Using IBA Method**\n\n"
        "**I**dentify - Key points or words\n"
        "**B**reakdown - Define and understand\n"
        "**A**pply - How does this apply to you today?\n\n"
        "What would you like to reflect on?",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def reflect_identify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt for Identify phase"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['reflection_phase'] = 'identify'
    
    await query.edit_message_text(
        "🎯 **Identify Phase**\n\n"
        "What were the key points or words from your reading?\n"
        "Share them in the next message.\n\n"
        "_Type your response below:_",
        parse_mode='Markdown'
    )
    
    return WAITING_FOR_REFLECTION_CONTENT


async def reflect_breakdown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt for Breakdown phase"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['reflection_phase'] = 'breakdown'
    
    await query.edit_message_text(
        "🔍 **Breakdown Phase**\n\n"
        "What do these key words/points mean?\n"
        "How would you define or explain them?\n\n"
        "_Type your response below:_",
        parse_mode='Markdown'
    )
    
    return WAITING_FOR_REFLECTION_CONTENT


async def reflect_apply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt for Apply phase"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['reflection_phase'] = 'apply'
    
    await query.edit_message_text(
        "💡 **Apply Phase**\n\n"
        "How does this apply to your life today?\n"
        "What will you do differently based on this?\n\n"
        "_Type your response below:_",
        parse_mode='Markdown'
    )
    
    return WAITING_FOR_REFLECTION_CONTENT


async def reflect_free(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Free reflection without structure"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['reflection_phase'] = 'free'
    
    await query.edit_message_text(
        "📝 **Free Reflection**\n\n"
        "Share your thoughts and learnings from your reading.\n"
        "No structure needed—just write what's on your mind.\n\n"
        "_Type your response below:_",
        parse_mode='Markdown'
    )
    
    return WAITING_FOR_REFLECTION_CONTENT


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Route text input to the correct handler based on the user's current mode.

    Checks context.user_data for:
      - 'planning' == 'bible'      -> save as Bible plan
      - 'planning' == 'sound_desk' -> save as Sound Desk plan
      - 'reflection_phase'         -> save as reflection entry
      - otherwise                  -> show a simple prompt to use the menu
    """
    user_id = update.effective_user.id
    planning_mode = context.user_data.get('planning')
    reflection_phase = context.user_data.get('reflection_phase')

    logger.info(
        f"handle_text_input | user={user_id} | "
        f"planning={planning_mode!r} | reflection={reflection_phase!r} | "
        f"text={update.message.text[:60]!r}"
    )

    if planning_mode == 'bible':
        await handle_bible_plan_input(update, context)

    elif planning_mode == 'sound_desk':
        await handle_sound_plan_input(update, context)

    elif reflection_phase:
        await handle_reflection_input(update, context)

    else:
        await update.message.reply_text(
            "👋 Not sure what you meant — use the menu to get started!\n\n"
            "Type /start to see your options."
        )


async def handle_reflection_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle reflection text input"""
    user_id = update.effective_user.id
    reflection_text = update.message.text
    reflection_phase = context.user_data.get('reflection_phase', 'free')
    learning_type = context.user_data.get('learning_type', 'general')

    # Clear reflection state so future messages don't keep routing here
    context.user_data.pop('reflection_phase', None)

    # Format reflection entry
    formatted_reflection = (
        f"**{learning_type.upper()} Learning - {reflection_phase.upper()} Phase**\n\n"
        f"{reflection_text}\n\n"
        f"_Logged at: {datetime.now(USER_TIMEZONE).strftime('%Y-%m-%d %H:%M')} GMT_"
    )
    
    # Send to Reflectly (stored locally for now)
    send_to_reflectly(
        user_id,
        formatted_reflection,
        tags=[learning_type, 'iba', reflection_phase]
    )
    
    # Update streak
    streak = update_streak(user_id, learning_type)
    
    await update.message.reply_text(
        f"✅ **Reflection Logged!**\n\n"
        f"🔥 {learning_type.title()} Streak: **{streak} days**\n\n"
        f"Your reflection has been saved. 📚\n\n"
        f"_Next step: Copy this reflection to Reflectly app manually, or sync later._",
        parse_mode='Markdown'
    )


async def sound_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sound Desk learning main menu"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = load_user_data(user_id)
    
    streak = data.get("sound_desk_streak", 0)
    
    keyboard = [
        [InlineKeyboardButton("✅ Log Learning Session", callback_data='sound_log')],
        [InlineKeyboardButton("🎯 Plan This Week", callback_data='sound_plan_week')],
        [InlineKeyboardButton("📚 View Learning Plan", callback_data='sound_view_plan')],
        [InlineKeyboardButton("🔙 Back", callback_data='main_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"🎛️ **Sound Desk Mastery**\n\n"
        f"Current Streak: 🔥 **{streak} days**\n\n"
        f"Focus Areas:\n"
        f"• Ground loop troubleshooting\n"
        f"• Gain staging fundamentals\n"
        f"• Phantom power (48V)\n"
        f"• XLR vs Jack cables\n"
        f"• Shure wireless systems\n\n"
        f"What would you like to do?",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def sound_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log sound desk learning"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    context.user_data['learning_type'] = 'sound_desk'
    
    keyboard = [
        [InlineKeyboardButton("Just log completion ✅", callback_data='sound_log_quick')],
        [InlineKeyboardButton("Log + Reflect 💭", callback_data='sound_log_reflect')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🎛️ **Log Sound Desk Learning**\n\n"
        "How would you like to log your learning?",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def sound_log_quick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick log without reflection"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    streak = update_streak(user_id, "sound_desk")
    data = load_user_data(user_id)
    
    concept = data.get("current_sound_concepts", ["No concept set"])[0]
    
    await query.edit_message_text(
        f"✅ **Sound Desk Learning Logged!**\n\n"
        f"🔥 Streak: **{streak} days**\n"
        f"🎯 Today's focus: {concept}\n\n"
        f"Excellent progress! Keep building your mastery. 🎛️",
        parse_mode='Markdown'
    )


async def sound_log_reflect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log with reflection using 5W1H method"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['learning_type'] = 'sound_desk'
    context.user_data['reflection_method'] = '5w1h'
    
    keyboard = [
        [InlineKeyboardButton("What? (Topic)", callback_data='reflect_what')],
        [InlineKeyboardButton("Why? (Purpose)", callback_data='reflect_why')],
        [InlineKeyboardButton("How? (Application)", callback_data='reflect_how')],
        [InlineKeyboardButton("Free Reflection", callback_data='reflect_free')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "💭 **Reflection Using 5W1H Method**\n\n"
        "**What** - What did you learn?\n"
        "**Why** - Why is this important for your setup?\n"
        "**How** - How will you apply this?\n\n"
        "What would you like to reflect on?",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def reflect_what(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt for What phase"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['reflection_phase'] = 'what'
    
    await query.edit_message_text(
        "❓ **What?**\n\n"
        "What was the main concept or skill you learned?\n"
        "Describe it in your own words.\n\n"
        "_Type your response below:_",
        parse_mode='Markdown'
    )
    
    return WAITING_FOR_REFLECTION_CONTENT


async def reflect_why(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt for Why phase"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['reflection_phase'] = 'why'
    
    await query.edit_message_text(
        "🤔 **Why?**\n\n"
        "Why is this important for your Church setup?\n"
        "How does it help you create better sound?\n\n"
        "_Type your response below:_",
        parse_mode='Markdown'
    )
    
    return WAITING_FOR_REFLECTION_CONTENT


async def reflect_how(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt for How phase"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['reflection_phase'] = 'how'
    
    await query.edit_message_text(
        "🛠️ **How?**\n\n"
        "How will you apply this the next time you're at the mixer?\n"
        "What specific steps will you take?\n\n"
        "_Type your response below:_",
        parse_mode='Markdown'
    )
    
    return WAITING_FOR_REFLECTION_CONTENT


async def view_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View learning progress"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = load_user_data(user_id)
    
    bible_streak = data.get("bible_streak", 0)
    sound_streak = data.get("sound_desk_streak", 0)
    total_reflections = len(data.get("reflections", []))
    
    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data='main_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"📊 **Your Progress**\n\n"
        f"📖 **Bible Reading**\n"
        f"🔥 Streak: {bible_streak} days\n\n"
        f"🎛️ **Sound Desk Learning**\n"
        f"🔥 Streak: {sound_streak} days\n\n"
        f"💭 **Total Reflections**: {total_reflections}\n\n"
        f"_Keep up the consistent learning!_",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def bible_plan_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Plan Bible readings for the week"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    await query.edit_message_text(
        "📖 **Plan Your Bible Readings**\n\n"
        "Send me the Bible passages you want to read this week.\n"
        "You can send them as:\n"
        "• A list (e.g., John 3:16, Romans 8, Psalms 23)\n"
        "• A Bible plan name (e.g., New Testament, Psalms)\n"
        "• YouTube links to Bible readings\n\n"
        "_Type your plan below:_",
        parse_mode='Markdown'
    )
    
    context.user_data['planning'] = 'bible'
    return WAITING_FOR_BIBLE_PASSAGE


async def handle_bible_plan_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Bible plan input"""
    user_id = update.effective_user.id
    plan_text = update.message.text

    # Clear planning state so future messages don't keep routing here
    context.user_data.pop('planning', None)

    data = load_user_data(user_id)
    data['current_bible_plan'] = plan_text.split('\n')
    user_data[user_id] = data
    save_user_data(user_id)
    
    await update.message.reply_text(
        f"✅ **Bible Plan Updated!**\n\n"
        f"Your readings for this week:\n"
        f"{plan_text}\n\n"
        f"Ready to start? Use /start to return to the menu.",
        parse_mode='Markdown'
    )


async def bible_view_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View current Bible plan"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = load_user_data(user_id)
    
    plan = data.get("current_bible_plan", ["No plan set"])
    plan_text = "\n".join(plan) if isinstance(plan, list) else plan
    
    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data='bible_main')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"📚 **Your Bible Reading Plan**\n\n"
        f"{plan_text}\n\n"
        f"_Use the Bible Reading menu to log completions._",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def sound_plan_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Plan sound desk learning for the week"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🎛️ **Plan Your Sound Desk Learning**\n\n"
        "What concepts do you want to master this week?\n"
        "You can send:\n"
        "• Specific topics (e.g., ground loop troubleshooting, gain staging)\n"
        "• YouTube links\n"
        "• Your own notes on what you want to learn\n\n"
        "_Type your learning plan below:_",
        parse_mode='Markdown'
    )
    
    context.user_data['planning'] = 'sound_desk'
    return WAITING_FOR_SOUND_CONCEPT


async def handle_sound_plan_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle sound desk plan input"""
    user_id = update.effective_user.id
    plan_text = update.message.text

    # Clear planning state so future messages don't keep routing here
    context.user_data.pop('planning', None)

    data = load_user_data(user_id)
    data['current_sound_concepts'] = plan_text.split('\n')
    user_data[user_id] = data
    save_user_data(user_id)
    
    await update.message.reply_text(
        f"✅ **Sound Desk Learning Plan Updated!**\n\n"
        f"Your focus areas for this week:\n"
        f"{plan_text}\n\n"
        f"Ready to start? Use /start to return to the menu.",
        parse_mode='Markdown'
    )


async def sound_view_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View current sound desk learning plan"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = load_user_data(user_id)
    
    plan = data.get("current_sound_concepts", ["No plan set"])
    plan_text = "\n".join(plan) if isinstance(plan, list) else plan
    
    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data='sound_main')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"🎯 **Your Sound Desk Learning Plan**\n\n"
        f"{plan_text}\n\n"
        f"_Use the Sound Desk menu to log learning sessions._",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return to main menu"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📖 Bible Reading", callback_data='bible_main')],
        [InlineKeyboardButton("🎛️ Sound Desk Learning", callback_data='sound_main')],
        [InlineKeyboardButton("📊 View Progress", callback_data='view_progress')],
        [InlineKeyboardButton("⚙️ Settings", callback_data='settings')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🎯 **Learning Streak Tracker**\n\n"
        "Track your Bible reading and sound desk mastery journey.\n\n"
        "What would you like to do?",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Settings menu"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data='main_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "⚙️ **Settings**\n\n"
        f"Daily Reminder: 7:00 AM GMT\n"
        f"Timezone: Europe/London\n\n"
        f"_For now, settings are fixed. Contact bot admin to customize._",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


# ==================== DAILY REMINDER JOB ====================

async def daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Send daily morning reminders"""
    job_context = context.job.context
    user_id = job_context
    
    data = load_user_data(user_id)
    bible_plan = data.get("current_bible_plan", ["No plan set"])
    
    if isinstance(bible_plan, list) and bible_plan:
        today_reading = bible_plan[0] if bible_plan else "No plan set"
    else:
        today_reading = "No plan set"
    
    message = (
        "🌅 **Good Morning!**\n\n"
        f"📖 Today's Bible Reading: {today_reading}\n\n"
        "Ready to start your day with reflection? Use /start"
    )
    
    try:
        await context.bot.send_message(chat_id=user_id, text=message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error sending daily reminder to {user_id}: {e}")


async def setup_daily_job(user_id: int, application: Application):
    """Set up daily reminder job for a user"""
    try:
        # Remove existing job if present
        current_jobs = application.job_queue.get_jobs_by_name(f"daily_{user_id}")
        for job in current_jobs:
            job.schedule_removal()
        
        # Create new job
        application.job_queue.run_daily(
            daily_reminder,
            time=datetime.time(DAILY_REMINDER_HOUR, DAILY_REMINDER_MINUTE, tzinfo=USER_TIMEZONE),
            name=f"daily_{user_id}",
            context=user_id
        )
        logger.info(f"Set up daily job for user {user_id}")
    except Exception as e:
        logger.error(f"Error setting up daily job for {user_id}: {e}")


# ==================== MAIN APPLICATION ====================

def main():
    """Start the bot"""
    
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in environment variables")
    
    # Create application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(bible_main, pattern='^bible_main$'))
    application.add_handler(CallbackQueryHandler(sound_main, pattern='^sound_main$'))
    application.add_handler(CallbackQueryHandler(view_progress, pattern='^view_progress$'))
    application.add_handler(CallbackQueryHandler(settings, pattern='^settings$'))
    application.add_handler(CallbackQueryHandler(main_menu, pattern='^main_menu$'))
    
    # Bible handlers
    application.add_handler(CallbackQueryHandler(bible_log, pattern='^bible_log$'))
    application.add_handler(CallbackQueryHandler(bible_log_quick, pattern='^bible_log_quick$'))
    application.add_handler(CallbackQueryHandler(bible_log_reflect, pattern='^bible_log_reflect$'))
    application.add_handler(CallbackQueryHandler(bible_plan_week, pattern='^bible_plan_week$'))
    application.add_handler(CallbackQueryHandler(bible_view_plan, pattern='^bible_view_plan$'))
    
    # Sound desk handlers
    application.add_handler(CallbackQueryHandler(sound_log, pattern='^sound_log$'))
    application.add_handler(CallbackQueryHandler(sound_log_quick, pattern='^sound_log_quick$'))
    application.add_handler(CallbackQueryHandler(sound_log_reflect, pattern='^sound_log_reflect$'))
    application.add_handler(CallbackQueryHandler(sound_plan_week, pattern='^sound_plan_week$'))
    application.add_handler(CallbackQueryHandler(sound_view_plan, pattern='^sound_view_plan$'))
    
    # Reflection handlers
    application.add_handler(CallbackQueryHandler(reflect_identify, pattern='^reflect_identify$'))
    application.add_handler(CallbackQueryHandler(reflect_breakdown, pattern='^reflect_breakdown$'))
    application.add_handler(CallbackQueryHandler(reflect_apply, pattern='^reflect_apply$'))
    application.add_handler(CallbackQueryHandler(reflect_what, pattern='^reflect_what$'))
    application.add_handler(CallbackQueryHandler(reflect_why, pattern='^reflect_why$'))
    application.add_handler(CallbackQueryHandler(reflect_how, pattern='^reflect_how$'))
    application.add_handler(CallbackQueryHandler(reflect_free, pattern='^reflect_free$'))
    
    # Text message handlers (for plan inputs and reflections)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input)
    )
    
    # Start bot
    print("🤖 Learning Streak Tracker Bot is starting...")
    application.run_polling()


if __name__ == '__main__':
    main()
