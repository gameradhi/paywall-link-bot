import logging
from telegram import (
    Update,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from db import init_db, upsert_creator  # ⬅️ our DB helpers

# === YOUR CREATOR BOT TOKEN ===
BOT_TOKEN = "8280706073:AAED9i2p0TP42pPf9vMXoTt_HYGxqEuyy2w"

# temporary state for referral during first login
WAITING_REFERRAL = set()      # set of tg_id waiting for referral input
TEMP_REFERRALS = {}           # tg_id -> referral_code or None

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # For now, always ask for login (number) on /start
    btn = KeyboardButton(text="📲 Share Phone Number", request_contact=True)
    kb = ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "Welcome Creator 👋\n\nPlease verify login by sharing your phone number.",
        reply_markup=kb
    )


async def save_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    user = update.effective_user

    # store phone in user_data for this login flow
    context.user_data["phone"] = contact.phone_number

    # mark that we now expect referral code text
    WAITING_REFERRAL.add(user.id)
    TEMP_REFERRALS[user.id] = None

    await update.message.reply_text(
        "Number verified ✅\n\nDo you have referral code?\n• Send it now\n• Or type 'no'",
        reply_markup=ReplyKeyboardRemove()
    )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = (update.message.text or "").strip()

    # handle referral step
    if user.id in WAITING_REFERRAL:
        if msg.lower() == "no":
            ref = None
        else:
            ref = msg

        WAITING_REFERRAL.remove(user.id)
        TEMP_REFERRALS[user.id] = ref

        phone = context.user_data.get("phone", "")

        # save / update creator in DB
        upsert_creator(
            tg_id=user.id,
            username=user.username or "",
            full_name=user.full_name or "",
            phone=phone,
            referred_by=ref,
        )

        await show_main_menu(update, context, "You’re now logged in 🎉")
        return

    # any other random text
    await update.message.reply_text("Use the buttons below 👇")


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, title="Creator Menu"):
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
    data = update.callback_query.data
    await update.callback_query.answer()

    mapping = {
        "create": "🔗 Create Paid Link — coming soon",
        "earnings": "💰 Earnings — coming soon",
        "stats": "📊 Link Stats — coming soon",
        "bank": "🏦 Add/Update Bank — coming soon",
        "refer": "👥 Referral system — coming soon",
        "creator_help": "❓ Help — coming soon",
    }

    await update.callback_query.edit_message_text(mapping[data])


def main():
    # make sure DB table exists
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, save_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()


if __name__ == "__main__":
    main()
