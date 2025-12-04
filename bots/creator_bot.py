import logging
import os
import sys

# Make sure Python can find db.py (parent folder)
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

from telegram import (
    Update,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
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

from db import init_db, upsert_creator, create_paid_link  # DB helpers

# === CREATOR BOT TOKEN ===
BOT_TOKEN = "8280706073:AAED9i2p0TP42pPf9vMXoTt_HYGxqEuyy2w"

# === MAIN BOT USERNAME (for building share links) ===
MAIN_BOT_USERNAME = "TeleShortLinkBot"

# state flags
WAITING_REFERRAL = set()  # creators waiting for referral code


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ----------------- COMMANDS -----------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask creator to login with phone number."""
    user = update.effective_user

    btn = KeyboardButton(text="📲 Share Phone Number", request_contact=True)
    kb = ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "Welcome Creator 👋\n\nPlease verify login by sharing your phone number.",
        reply_markup=kb,
    )


# ----------------- LOGIN FLOW -----------------


async def save_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle phone number and ask for referral."""
    contact = update.message.contact
    user = update.effective_user

    context.user_data["phone"] = contact.phone_number

    WAITING_REFERRAL.add(user.id)

    await update.message.reply_text(
        "Number verified ✅\n\nDo you have referral code?\n• Send it now\n• Or type 'no'",
        reply_markup=ReplyKeyboardRemove(),
    )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle referral and Create-Link questions."""
    user = update.effective_user
    msg = (update.message.text or "").strip()

    # 1) referral step
    if user.id in WAITING_REFERRAL:
        if msg.lower() == "no":
            ref = None
        else:
            ref = msg

        WAITING_REFERRAL.remove(user.id)

        phone = context.user_data.get("phone", "")

        upsert_creator(
            tg_id=user.id,
            username=user.username or "",
            full_name=user.full_name or "",
            phone=phone,
            referred_by=ref,
        )

        await show_main_menu(update, context, "You’re now logged in 🎉")
        return

    # 2) create link - step: waiting for URL
    if context.user_data.get("state") == "awaiting_url":
        # very basic URL check
        if not (msg.startswith("http://") or msg.startswith("https://")):
            await update.message.reply_text("Please send a *valid* URL starting with http or https.", parse_mode="Markdown")
            return

        context.user_data["new_link_url"] = msg
        context.user_data["state"] = "awaiting_price"

        await update.message.reply_text(
            "Nice 🔗\nNow send the *price in ₹* that users must pay to unlock this link.\n\nExample: `20`",
            parse_mode="Markdown",
        )
        return

    # 3) create link - step: waiting for price
    if context.user_data.get("state") == "awaiting_price":
        if not msg.isdigit():
            await update.message.reply_text("Price must be a number in rupees, for example: 10, 20, 50.")
            return

        price = int(msg)
        if price <= 0:
            await update.message.reply_text("Price must be more than 0 ₹.")
            return

        original_url = context.user_data.get("new_link_url")
        if not original_url:
            # something went wrong, reset
            context.user_data["state"] = None
            await update.message.reply_text("Something went wrong, please try creating the link again.")
            return

        # create in DB
        code = create_paid_link(
            creator_tg_id=user.id,
            original_url=original_url,
            price=price,
        )

        context.user_data["state"] = None
        context.user_data.pop("new_link_url", None)

        short_link = f"https://t.me/{MAIN_BOT_USERNAME}?start={code}"

        await update.message.reply_text(
            "✅ *Paid Link Created!*\n\n"
            f"Original URL:\n{original_url}\n\n"
            f"Price: ₹{price}\n\n"
            f"Share this link to earn:\n`{short_link}`",
            parse_mode="Markdown",
        )

        await show_main_menu(update, context, "Back to Creator Menu:")
        return

    # default
    await update.message.reply_text("Use the buttons below 👇")


# ----------------- MENU & BUTTONS -----------------


async def show_main_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    title: str = "Creator Menu",
):
    menu = [
        [InlineKeyboardButton("🔗 Create Paid Link", callback_data="create")],
        [
            InlineKeyboardButton("💰 Earnings", callback_data="earnings"),
            InlineKeyboardButton("📊 Link Stats", callback_data="stats"),
        ],
        [InlineKeyboardButton("🏦 Bank / UPI", callback_data="bank")],
        [InlineKeyboardButton("👥 Refer & Earn", callback_data="refer")],
        [InlineKeyboardButton("❓ Help", callback_data="creator_help")],
    ]
    kb = InlineKeyboardMarkup(menu)

    if update.callback_query:
        await update.callback_query.edit_message_text(title, reply_markup=kb)
    else:
        await update.message.reply_text(title, reply_markup=kb)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    # Handle each button
    if data == "create":
        # start create link flow
        context.user_data["state"] = "awaiting_url"
        await query.edit_message_text(
            "🔗 *Create Paid Link*\n\n"
            "Send me the *original URL* you want to protect behind payment.",
            parse_mode="Markdown",
        )
        return

    if data == "earnings":
        await query.edit_message_text(
            "💰 *Earnings* — coming soon.\n\n"
            "You’ll see total earnings & withdrawable balance here.",
            parse_mode="Markdown",
        )
        return

    if data == "stats":
        await query.edit_message_text(
            "📊 *Link Stats* — coming soon.\n\n"
            "You’ll see clicks and unlock stats here.",
            parse_mode="Markdown",
        )
        return

    if data == "bank":
        await query.edit_message_text(
            "🏦 *Bank / UPI* — coming soon.\n\n"
            "You’ll be able to add or edit your payout details here.",
            parse_mode="Markdown",
        )
        return

    if data == "refer":
        await query.edit_message_text(
            "👥 *Refer & Earn* — coming soon.\n\n"
            "You’ll get a referral code and extra commission.",
            parse_mode="Markdown",
        )
        return

    if data == "creator_help":
        await query.edit_message_text(
            "❓ *Help* — coming soon.\n\n"
            "You’ll be able to contact support from here.",
            parse_mode="Markdown",
        )
        return


# ----------------- MAIN -----------------


def main():
    # ensure tables exist
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, save_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()


if __name__ == "__main__":
    main()
