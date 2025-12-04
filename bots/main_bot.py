import logging
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ====== YOUR MAIN / USER BOT TOKEN (DO NOT SHARE THIS) ======
BOT_TOKEN = "8301086845:AAFFFiYItPrAwgQmWLhgmS_TztqcjWx5S28"

# (we'll use this later for force-join)
FORCE_JOIN_CHANNEL_USERNAME = "TeleLinkUpdate"
FORCE_JOIN_CHANNEL_ID = -1003472900442

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    text = (
        f"Hey {user.first_name or 'there'} 👋\n\n"
        "Welcome to TeleShortLink Bot.\n"
        "Choose how you want to continue:"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "👤 Continue as User",
                callback_data="as_user",
            ),
        ],
        [
            InlineKeyboardButton(
                "👨‍💻 Continue as Creator",
                url="https://t.me/TeleShortLinkCreatorBot",
            ),
        ],
    ]

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()


if __name__ == "__main__":
    main()
