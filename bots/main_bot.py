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

# === FORCE JOIN CHANNEL ===
FORCE_CHANNEL_ID = -1003472900442
FORCE_CHANNEL_LINK = "https://t.me/TeleLinkUpdate"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ------------- FORCE JOIN -------------

async def ensure_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    try:
        member = await context.bot.get_chat_member(FORCE_CHANNEL_ID, user.id)
        if member.status in ("member", "administrator", "creator"):
            return True
    except Exception as e:
        logger.warning("Force-join check failed: %s", e)
        return True  # don't block if check breaks

    text = (
        "🔔 To use *TELE LINK*, please join our updates channel first.\n\n"
        "After joining, tap *I Joined*."
    )
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📢 Join TELE LINK Updates", url=FORCE_CHANNEL_LINK)],
            [InlineKeyboardButton("✅ I Joined", callback_data="check_sub")],
        ]
    )

    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    elif update.callback_query:
        await update.callback_query.message.reply_text(
            text, parse_mode="Markdown", reply_markup=kb
        )
    return False


# ------------- MAIN MENU -------------

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
            [InlineKeyboardButton("ℹ️ How TELE LINK works", callback_data="how")],
        ]
    )


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        f"Hey {user.first_name or 'there'} 👋\n\n"
        "*Welcome to TELE LINK*\n\n"
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


# ------------- COMMANDS -------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_force_join(update, context):
        return

    text = update.message.text or ""

    # /start CODE → paywall
    if text.startswith("/start") and len(text.split()) > 1:
        code = text.split()[1]
        return await handle_paywall(update, context, code)

    # normal /start
    await show_main_menu(update, context)


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_force_join(update, context):
        return
    await show_main_menu(update, context)


# ------------- PAYWALL -------------

async def handle_paywall(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    if not await ensure_force_join(update, context):
        return

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
        f"🔒 *This content is locked (TELE LINK)*\n\n"
        f"💰 Price: ₹{price}\n\n"
        "Tap *Unlock* to simulate payment and open the link.\n"
        "_(Real payment gateway will be connected later.)_",
        reply_markup=kb,
        parse_mode="Markdown",
    )


async def pay_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_force_join(update, context):
        return

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

    # TODO: integrate real payment gateway here
    record_unlock_payment(user_tg_id=user.id, link_code=code, amount=price)

    await query.edit_message_text(
        "🎉 *Payment simulated!*\nUnlocking link...",
        parse_mode="Markdown",
    )
    await query.message.reply_text(
        f"🔓 *Unlocked!*\n\nOpen your link 👇\n{original_url}",
        parse_mode="Markdown",
    )


# ------------- GENERIC BUTTONS -------------

async def generic_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_force_join(update, context):
        return

    query = update.callback_query
    data = query.data
    await query.answer()

    # Re-check after "I Joined"
    if data == "check_sub":
        if await ensure_force_join(update, context):
            await query.message.reply_text(
                "✅ Thanks for joining TELE LINK Updates!\nHere is the main menu:",
            )
            await show_main_menu(update, context)
        return

    # Main menu
    if data == "back_menu":
        await show_main_menu(update, context)
        return

    # How it works
    if data == "how":
        text = (
            "ℹ️ *How TELE LINK works*\n\n"
            "1. Creators generate a TELE LINK paywall link.\n"
            "2. Users open the link in this bot.\n"
            "3. After payment, the bot unlocks the original URL.\n\n"
            "Creators keep 90% of the price.\n"
            "You, as the platform, keep 10%.\n"
            "Referrers earn 5% from your share.\n\n"
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
            "Just open any TELE LINK you receive from creators.\n"
            "This bot will handle the payment and unlock (test mode right now).",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]]
            ),
        )
        return


# ------------- MAIN -------------

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CallbackQueryHandler(pay_button, pattern="^pay:"))
    app.add_handler(CallbackQueryHandler(generic_buttons))
    app.run_polling()


if __name__ == "__main__":
    main()
