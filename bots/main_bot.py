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

# Force join channel (kept for later)
FORCE_CHANNEL = "@TeleLinkUpdate"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main_menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👤 Continue as User", callback_data="as_user")],
            [
                InlineKeyboardButton(
                    "👨‍💻 Creator Panel",
                    url="https://t.me/TeleShortLinkCreatorBot",
                )
            ],
            [InlineKeyboardButton("ℹ️ How it works", callback_data="how")],
        ]
    )


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        f"Hey {user.first_name or 'there'} 👋\n\n"
        "Welcome to *TeleShortLink*.\n\n"
        "• Creators can lock any link behind a small payment.\n"
        "• Users pay once to unlock and access the content.\n\n"
        "Choose how you want to continue:"
    )
    if update.message:
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
        )
    else:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""

    # /start CODE → paywall
    if text.startswith("/start") and len(text.split()) > 1:
        code = text.split()[1]
        return await handle_paywall(update, context, code)

    # normal /start
    await show_main_menu(update, context)


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)


async def handle_paywall(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    link = get_link_by_code(code)
    if not link:
        await update.message.reply_text("⛔ Invalid or expired link.")
        return

    price = link["price"]
    btn_pay = InlineKeyboardButton(
        f"💰 Unlock for ₹{price}", callback_data=f"pay:{code}"
    )
    btn_home = InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")
    kb = InlineKeyboardMarkup([[btn_pay], [btn_home]])

    await update.message.reply_text(
        f"🔒 *This content is locked*\n\n"
        f"💰 Price: ₹{price}\n\n"
        "Tap *Unlock* to simulate payment and open the link.\n"
        "_(Real payment gateway will be connected later.)_",
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
        "🎉 *Payment simulated!*\nUnlocking link...",
        parse_mode="Markdown",
    )
    await query.message.reply_text(
        f"🔓 *Unlocked!*\n\nOpen your link 👇\n{original_url}",
        parse_mode="Markdown",
    )


async def generic_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    # Main menu
    if data == "back_menu":
        await show_main_menu(update, context)
        return

    # How it works
    if data == "how":
        text = (
            "ℹ️ *How TeleShortLink works*\n\n"
            "1. Creators generate a special paywall link.\n"
            "2. Users open the link in this bot.\n"
            "3. After payment, the bot unlocks the original URL.\n\n"
            "Creators earn 90%, you earn 10%, and referrers get 5% from your share.\n\n"
            "To start earning, click *Creator Panel* and create your first link."
        )
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]]
            ),
        )
        return

    # User mode placeholder
    if data == "as_user":
        await query.edit_message_text(
            "👤 *User Mode*\n\n"
            "Just open any TeleShortLink link you receive from creators.\n"
            "This bot will handle the payment and unlock (test mode right now).",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]]
            ),
        )
        return


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CallbackQueryHandler(pay_button, pattern="^pay:"))
    app.add_handler(CallbackQueryHandler(generic_buttons))
    app.run_polling()


if __name__ == "__main__":
    main()
