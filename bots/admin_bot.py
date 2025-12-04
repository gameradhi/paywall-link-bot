import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# === YOUR ADMIN BOT TOKEN ===
BOT_TOKEN = "8270428628:AAGni2YOm2l-P_t2IxEwyaidmiqjyLj9Zz0"

# === OWNER / ADMIN TELEGRAM ID ===
OWNER_ID = 8545081401  # @AntManIndia

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user.id != OWNER_ID:
        await update.message.reply_text(
            "⚠️ This bot is only for the platform admin."
        )
        return

    await update.message.reply_text(
        "Hello Boss 🐜\n\n"
        "You are logged in as @AntManIndia.\n"
        "Broadcast & support tools will be added soon."
    )


async def echo_non_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # if anyone else tries to chat
    if update.effective_user.id != OWNER_ID:
        return  # ignore others


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL, echo_non_owner))
    app.run_polling()


if __name__ == "__main__":
    main()
