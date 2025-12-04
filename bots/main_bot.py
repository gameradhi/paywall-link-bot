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
    CallbackQueryHandler,
    ContextTypes,
)

from db import get_link_by_code, record_unlock_payment

# === MAIN BOT TOKEN ===
BOT_TOKEN = "8301086845:AAFFFiYItPrAwgQmWLhgmS_TztqcjWx5S28"

# Force join channel (will use later)
FORCE_CHANNEL = "@TeleLinkUpdate"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text or ""

    # /start CODE → paywall
    if text.startswith("/start") and len(text.split()) > 1:
        code = text.split()[1]
        return await handle_paywall(update, context, code)

    # normal /start (no code)
    keyboard = [
        [
            InlineKeyboardButton("👤 Continue as User", callback_data="as_user"),
        ],
        [
            InlineKeyboardButton(
                "👨‍💻 Continue as Creator",
                url="https://t.me/TeleShortLinkCreatorBot",
            ),
        ],
    ]
    await update.message.reply_text(
        f"Hey {user.first_name or 'there'} 👋\n\n"
        "Welcome to TeleShortLink Bot.\n"
        "Choose how you want to continue:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_paywall(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    link = get_link_by_code(code)
    if not link:
        await update.message.reply_text("⛔ Invalid or expired link.")
        return

    price = link["price"]
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
    query = update.callback_query
    user = query.from_user
    await query.answer()

    data = query.data
    code = data.split(":")[1]

    link = get_link_by_code(code)
    if not link:
        await query.edit_message_text("⛔ Invalid or expired link.")
        return

    original_url = link["original_url"]
    price = link["price"]

    # TODO: here we will integrate real payment later.
    # For now, we treat as if payment succeeded
    record_unlock_payment(user_tg_id=user.id, link_code=code, amount=price)

    await query.edit_message_text(
        "🎉 *Payment successful!*\nUnlocking link...",
        parse_mode="Markdown",
    )
    await query.message.reply_text(
        f"🔓 *Unlocked!*\n\nOpen your link 👇\n{original_url}",
        parse_mode="Markdown",
    )


async def menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("User mode coming soon 🙂", show_alert=False)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(pay_button, pattern="^pay:"))
    app.add_handler(CallbackQueryHandler(menu_button, pattern="^as_user$"))
    app.run_polling()


if __name__ == "__main__":
    main()
