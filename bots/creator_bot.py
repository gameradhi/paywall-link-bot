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

# === YOUR CREATOR BOT TOKEN ===
BOT_TOKEN = "8280706073:AAED9i2p0TP42pPf9vMXoTt_HYGxqEuyy2w"

# temporary storage (later DB)
CREATORS = {}
WAITING_REFERRAL = set()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # if already logged in
    if user.id in CREATORS:
        await show_main_menu(update, context, "Welcome back Creator 👨‍💻")
        return

    btn = KeyboardButton(text="📲 Share Phone Number", request_contact=True)
    kb = ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "Welcome Creator 👋\n\nPlease verify login by sharing your phone number.",
        reply_markup=kb
    )


async def save_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    user = update.effective_user

    CREATORS[user.id] = {
        "phone": contact.phone_number,
        "referrer": None,
    }

    WAITING_REFERRAL.add(user.id)

    await update.message.reply_text(
        "Number verified ✅\n\nDo you have referral code?\n• Send it now\n• Or type 'no'",
        reply_markup=ReplyKeyboardRemove()
    )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message.text.strip()

    if user.id in WAITING_REFERRAL:
        if msg.lower() == "no":
            CREATORS[user.id]["referrer"] = None
        else:
            CREATORS[user.id]["referrer"] = msg
        
        WAITING_REFERRAL.remove(user.id)
        await show_main_menu(update, context, "You’re now logged in 🎉")
        return

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
    # Later we’ll return to menu after actions


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, save_contact))
    app.add_handler(MessageHandler(filters.TEXT, text_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()


if __name__ == "__main__":
    main()
