# bots/creator_bot.py
# TELE LINK - Creator Bot
# This bot lets creators generate paid links that are unlocked via the main user bot.

import logging
import uuid
import os
import sys

# ===== FIX PYTHON PATH SO WE CAN IMPORT db.py FROM PROJECT ROOT =====
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ========= CONFIG =========

# TODO: put your CREATOR bot token here (NOT the user bot token)
BOT_TOKEN = "PASTE_YOUR_CREATOR_BOT_TOKEN_HERE"

# Username of the MAIN user bot which handles payments & unlocking
MAIN_BOT_USERNAME = "TeleShortLinkBot"  # without @

BRAND_NAME = "TELE LINK"

# ========= DB IMPORT =========
from db import init_db, create_paid_link, get_creator_stats

# ========= LOGGING =========
logging.basicConfig(
    format="%(asctime)s - CREATOR_BOT - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ========= STATE KEYS =========
STATE_KEY = "state"
STATE_WAIT_URL = "wait_url"
STATE_WAIT_PRICE = "wait_price"
TEMP_URL_KEY = "tmp_original_url"


# ========= HELPER: MAIN MENU =========
def main_menu_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("➕ Create Paid Link", callback_data="create_link"),
        ],
        [
            InlineKeyboardButton("📊 My Stats", callback_data="creator_stats"),
        ],
        [
            InlineKeyboardButton("❓ Help", callback_data="help"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = (
        update.effective_chat.id
        if update.effective_chat
        else (update.callback_query.message.chat_id if update.callback_query else None)
    )
    if chat_id is None:
        return

    text = (
        f"Hey {update.effective_user.first_name or 'Creator'} 👋\n\n"
        f"Welcome to {BRAND_NAME} Creator Panel.\n\n"
        "Here you can:\n"
        "• Lock any link (file, video, channel, bot, etc.) behind a small payment.\n"
        "• Share a special unlock link with your users.\n"
        "• Earn money every time someone unlocks your link.\n\n"
        "Choose an option below:"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=main_menu_keyboard(),
    )


# ========= /start =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    await send_main_menu(update, context)


# ========= CALLBACKS =========
async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Back to main menu from inline button."""
    query = update.callback_query
    await query.answer()
    await send_main_menu(update, context)


async def on_create_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start create-link flow."""
    query = update.callback_query
    await query.answer()

    context.user_data[STATE_KEY] = STATE_WAIT_URL
    context.user_data.pop(TEMP_URL_KEY, None)

    text = (
        "🧷 Create a Paid Link\n\n"
        "Send me the original URL you want to lock.\n"
        "Example:\n"
        "https://t.me/TeleShortLinkCreatorBot\n\n"
        "Make sure it starts with http:// or https://."
    )

    await query.message.reply_text(text)


async def on_creator_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show basic creator stats from DB."""
    query = update.callback_query
    await query.answer()

    tg_id = update.effective_user.id
    stats = get_creator_stats(tg_id)  # implemented in db.py

    total_links = stats.get("total_links", 0)
    total_earned = stats.get("total_earned_rupees", 0.0)
    total_unlocks = stats.get("total_unlocks", 0)

    text = (
        "📊 Your Creator Stats:\n\n"
        f"• Total paid links: {total_links}\n"
        f"• Total unlocks: {total_unlocks}\n"
        f"• Total earnings (approx): ₹{total_earned:.2f}\n\n"
        "Keep creating more paid links and share them with your audience!"
    )

    buttons = [
        [InlineKeyboardButton("⬅️ Back to Menu", callback_data="menu")],
    ]
    await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def on_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    text = (
        f"❓ How {BRAND_NAME} Creator Bot works:\n\n"
        "1) Tap Create Paid Link.\n"
        "2) Send the original URL you want to lock.\n"
        "3) Send the price in rupees.\n"
        "4) You will get a special unlock link like:\n"
        "   https://t.me/TeleShortLinkBot?start=pl_xxxxxx\n\n"
        "Share that unlock link anywhere. Users will:\n"
        "• Open the main bot\n"
        "• Pay the amount\n"
        "• Instantly get redirected to your original URL\n\n"
        "You earn commission from each successful unlock."
    )

    await query.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back to Menu", callback_data="menu")]]
        ),
    )


# ========= MESSAGE HANDLER FOR CREATE FLOW =========
async def on_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain text messages based on simple state machine."""
    user_state = context.user_data.get(STATE_KEY)

    # If user not in any flow, show menu
    if not user_state:
        await send_main_menu(update, context)
        return

    if user_state == STATE_WAIT_URL:
        await handle_original_url(update, context)
    elif user_state == STATE_WAIT_PRICE:
        await handle_price(update, context)
    else:
        # Unknown state, reset
        context.user_data.pop(STATE_KEY, None)
        await send_main_menu(update, context)


async def handle_original_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User sends original URL."""
    text = (update.message.text or "").strip()

    if not (text.startswith("http://") or text.startswith("https://")):
        await update.message.reply_text(
            "❌ That doesn't look like a valid URL.\n"
            "Please send a link starting with http:// or https://"
        )
        return

    # Save URL and ask for price
    context.user_data[TEMP_URL_KEY] = text
    context.user_data[STATE_KEY] = STATE_WAIT_PRICE

    await update.message.reply_text(
        "✅ Got your URL.\n\n"
        "Now send the price in ₹ that users must pay to unlock this link.\n"
        "Example: 20"
    )


async def handle_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User sends price."""
    original_url = context.user_data.get(TEMP_URL_KEY)
    if not original_url:
        # Somehow lost URL, restart.
        context.user_data.pop(STATE_KEY, None)
        await update.message.reply_text(
            "⚠️ I lost the previous URL. Let's start again."
        )
        await send_main_menu(update, context)
        return

    text_price = (update.message.text or "").strip()

    try:
        price_rupees = float(text_price)
        if price_rupees <= 0:
            raise ValueError()
    except Exception:
        await update.message.reply_text(
            "❌ Please send a valid positive number for price. Example: 25"
        )
        return

    # Create short code for the paid link
    short_code = "pl_" + uuid.uuid4().hex[:8]

    # Save in DB
    creator_id = update.effective_user.id
    try:
        create_paid_link(
            creator_tg_id=creator_id,
            original_url=original_url,
            price_rupees=price_rupees,
            short_code=short_code,
        )
    except Exception as e:
        logger.exception("Error saving paid link to DB: %s", e)
        await update.message.reply_text(
            "⚠️ Something went wrong while saving your link. "
            "Please try again later."
        )
        # reset state
        context.user_data.pop(STATE_KEY, None)
        context.user_data.pop(TEMP_URL_KEY, None)
        return

    # Build unlock command and clickable link for MAIN bot
    unlock_command = f"/start {short_code}"
    unlock_url = f"https://t.me/{MAIN_BOT_USERNAME}?start={short_code}"

    # Clear state
    context.user_data.pop(STATE_KEY, None)
    context.user_data.pop(TEMP_URL_KEY, None)

    msg = (
        "✅ Paid Link Created!\n\n"
        f"Original URL:\n{original_url}\n\n"
        f"Price: ₹{price_rupees:.2f}\n\n"
        "Share this link with users to unlock via the main bot:\n"
        f"{unlock_url}\n\n"
        "For Telegram only (command style), you can also share:\n"
        f"{unlock_command}\n\n"
        f"Make sure users open it in @{MAIN_BOT_USERNAME}."
    )

    buttons = [
        [InlineKeyboardButton("⬅️ Back to Menu", callback_data="menu")],
    ]

    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons))


# ========= MAIN =========
def main() -> None:
    # Initialize DB schema
    try:
        init_db()
        logger.info("DB initialized successfully")
    except Exception as e:
        logger.exception("Failed to initialize DB: %s", e)

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands
    application.add_handler(CommandHandler("start", start))

    # Callback buttons
    application.add_handler(CallbackQueryHandler(on_menu, pattern="^menu$"))
    application.add_handler(CallbackQueryHandler(on_create_link, pattern="^create_link$"))
    application.add_handler(CallbackQueryHandler(on_creator_stats, pattern="^creator_stats$"))
    application.add_handler(CallbackQueryHandler(on_help, pattern="^help$"))

    # Text messages (for URL + price)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_message)
    )

    logger.info("Creator bot started.")
    application.run_polling()


if __name__ == "__main__":
    main()
