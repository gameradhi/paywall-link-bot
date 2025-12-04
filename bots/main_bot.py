import logging
import os
import sys

# allow importing db.py
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from db import get_link_by_code, increment_link_click  # DB helpers

# === MAIN BOT TOKEN ===
BOT_TOKEN = "8301086845:AAFFFiYItPrAwgQmWLhgmS_TztqcjWxS28"

# Platform commission (10%)
PLATFORM_COMMISSION_PERCENT = 10

# Force join channel (not active yet)
FORCE_CHANNEL = "@TeleLinkUpdate"


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text or ""

    # Detect paywall link code
    if text.startswith("/start") and len(text.split()) > 1:
        code = text.split()[1]
        return await handle_paywall(update, context, code)

    # Default /start
    await update.message.reply_text(
        "👋 Welcome!\n\nSend /help to learn how this bot works."
    )


async def handle_paywall(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    """Handles unlocking paid links by code."""

    link = get_link_by_code(code)
    if not link:
        await update.message.reply_text("⛔ Invalid or expired link.")
        return

    price = link["price"]

    # Show paywall screen
    btn = InlineKeyboardButton(
        f"💰 Unlock for ₹{price}", callback_data=f"pay:{code}"
    )
    kb = InlineKeyboardMarkup([[btn]])

    await update.message.reply_text(
        f"🔒 *This content is locked*\n\n"
        f"💰 Price: ₹{price}\n\n"
        f"Click the button below to unlock.",
        reply_markup=kb,
        parse_mode="Markdown",
    )


async def pay_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles when user presses pay button (mock payment for now)."""
    query = update.callback_query
    await query.answer()

    data = query.data
    code = data.split(":")[1]

    link = get_link_by_code(code)
    if not link:
        await query.edit_message_text("⛔ Invalid or expired link.")
        return

    original_url = link["original_url"]
    price = link["price"]

    # mock payment — later we replace with real Razorpay
    increment_link_click(code, price)  # price added to earnings
    await query.edit_message_text(
        "🎉 *Payment successful!*\n"
        "Unlocking link...",
        parse_mode="Markdown",
    )

    await query.message.reply_text(
        f"🔓 *Unlocked!*\n\nOpen your link 👇\n{original_url}",
        parse_mode="Markdown",
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ This bot helps creators earn money by sharing paid links.\n\n"
        "• Creators make pay-to-access links\n"
        "• Users pay a small price to unlock content\n\n"
        "Use /start to continue."
    )


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(pay_button, pattern="^pay:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, help_cmd))
    app.run_polling()


if __name__ == "__main__":
    main()
