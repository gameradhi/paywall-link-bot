import logging
from typing import Set, Tuple

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# ================== CONFIG ==================

BOT_TOKEN = "8301086845:AAFFFiYItPrAwgQmWLhgmS_TztqcjWx5S28"

# Force-join channel
FORCE_CHANNEL_USERNAME = "TeleLinkUpdate"   # without @
FORCE_CHANNEL_ID = -1003472900442

# Branding
BRAND_NAME = "TELE LINK"
CURRENCY_SYMBOL = "₹"

# Creator bot username (for Creator Panel button)
CREATOR_BOT_USERNAME = "TeleShortLinkCreatorBot"

# ---- TEST paid link (for now we support only one hard-coded link) ----
TEST_SHORT_CODE = "pl_TEST001"
TEST_PRICE = 20.0

# Put any *private* URL here – this is what will be revealed after payment (TEST only)
TEST_LOCKED_URL = "https://example.com/your-secret-link"

# 👉 IMPORTANT:
# Paste your real Cashfree *TEST* payment link URL here
# (the one that opens the “Payment Success ₹20” screen you showed).
TEST_CASHFREE_LINK_URL = "https://payments-test.cashfree.com/links?code=l9j83m2sug2g_AAAAAACmTjU"

# In-memory record of who has already unlocked which short_code (TEST only)
UNLOCKED_USERS: Set[Tuple[int, str]] = set()

# ================== LOGGING ==================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ================== HELPERS ==================


async def check_force_join(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Return True if user is a member of the force-join channel.
    If the check fails (bot not admin / channel not found), we fail-open (return True).
    """
    bot = context.bot
    try:
        member = await bot.get_chat_member(FORCE_CHANNEL_ID, user_id)
        if member.status in ("member", "administrator", "creator", "owner"):
            return True
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning("Force-join check failed: %s", e)
        # To avoid locking everyone out because of a config issue, we allow them.
        return True


async def send_main_menu(chat_id: int, context: ContextTypes.DEFAULT_TYPE, first_name: str) -> None:
    text = (
        f"Hey {first_name} 👋\n\n"
        f"Welcome to *{BRAND_NAME}*.\n\n"
        "• Creators can lock any link behind a small one-time payment.\n"
        "• Users pay once to unlock and access the content forever.\n\n"
        "Choose how you want to continue:"
    )

    keyboard = [
        [InlineKeyboardButton("🙋‍♂️ Continue as User", callback_data="menu:as_user")],
        [InlineKeyboardButton("👨‍💻 Creator Panel", url=f"https://t.me/{CREATOR_BOT_USERNAME}")],
        [InlineKeyboardButton("ℹ️ How TELE LINK works", callback_data="menu:how_it_works")],
    ]

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def send_force_join_message(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    payload: str,
) -> None:
    """
    Ask user to join the updates channel.
    `payload` is what we should continue with after they press 'I Joined':
      - 'main'          → go back to main menu
      - 'pl_<short>'    → resume paid-link flow for that short code
    """
    text = (
        "📢 *Join TELE LINK Updates* first.\n\n"
        "We share important updates, tips, and creator news there.\n\n"
        "After joining the channel, tap *I Joined* below."
    )
    keyboard = [
        [
            InlineKeyboardButton(
                "🔔 Join TELE LINK Updates",
                url=f"https://t.me/{FORCE_CHANNEL_USERNAME}",
            )
        ],
        [InlineKeyboardButton("✅ I Joined", callback_data=f"joined:{payload}")],
    ]

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def send_paid_link_menu(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    short_code: str,
) -> None:
    """
    Show the lock screen + Pay + I Paid (TEST) buttons for a paid link.
    For now we support only TEST_SHORT_CODE and always unlock in TEST without real verification.
    """
    price = TEST_PRICE
    pay_button_row = []
    if TEST_CASHFREE_LINK_URL and TEST_CASHFREE_LINK_URL.startswith("http"):
        pay_button_row.append(
            InlineKeyboardButton(
                f"💳 Pay {CURRENCY_SYMBOL}{price:.0f} (Cashfree TEST)",
                url=TEST_CASHFREE_LINK_URL,
            )
        )
    else:
        # Fallback: simple info button, no URL
        pay_button_row.append(
            InlineKeyboardButton(
                f"💳 Pay {CURRENCY_SYMBOL}{price:.0f} (Cashfree TEST)",
                callback_data="info:cashfree_test",
            )
        )

    keyboard = [
        pay_button_row,
        [InlineKeyboardButton("✅ I have paid (TEST – unlock)", callback_data=f"test_paid:{short_code}")],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="menu:back_main")],
    ]

    text = (
        "🔒 *This link is locked*\n\n"
        f"To unlock this content, please pay *{CURRENCY_SYMBOL}{price:.0f}*.\n\n"
        "_Note: This is TEST mode, no real money is moving. In LIVE mode the bot "
        "will verify your payment automatically with Cashfree before unlocking._"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


# ================== HANDLERS ==================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id
    args = context.args

    # If /start came with a paid-link short code param
    if args and args[0].startswith("pl_"):
        short_code = args[0]

        # Only TEST short code is supported right now
        if short_code != TEST_SHORT_CODE:
            await update.message.reply_text("❌ Unknown or expired paid link.")
            return

        joined = await check_force_join(user.id, context)
        if not joined:
            await send_force_join_message(chat_id, context, payload=short_code)
            return

        await send_paid_link_menu(chat_id, context, short_code)
        return

    # Normal /start → show main menu (after force-join)
    joined = await check_force_join(user.id, context)
    if not joined:
        await send_force_join_message(chat_id, context, payload="main")
        return

    await send_main_menu(chat_id, context, user.first_name or "there")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    chat_id = query.message.chat.id

    logger.info("Callback data from %s: %s", user.id, data)

    # User pressed "I Joined"
    if data.startswith("joined:"):
        payload = data.split(":", 1)[1]
        joined = await check_force_join(user.id, context)
        if not joined:
            await query.answer("Please join the channel first 🙂", show_alert=True)
            return

        # Remove the old message to keep chat clean
        try:
            await query.message.delete()
        except Exception:  # noqa: BLE001
            pass

        if payload == "main":
            await send_main_menu(chat_id, context, user.first_name or "there")
        elif payload.startswith("pl_"):
            await send_paid_link_menu(chat_id, context, payload)
        return

    # Main-menu navigation
    if data == "menu:back_main" or data == "menu:as_user":
        try:
            await query.message.delete()
        except Exception:  # noqa: BLE001
            pass
        await send_main_menu(chat_id, context, user.first_name or "there")
        return

    if data == "menu:how_it_works":
        text = (
            f"📘 *How {BRAND_NAME} works*\n\n"
            "1️⃣ Creators go to the *Creator Panel* bot and generate a paid link.\n"
            "2️⃣ They share that paid link with their audience.\n"
            "3️⃣ Users open the link here, pay once, and get the *original unlocked URL*.\n"
            "4️⃣ The creator earns money, and referrers can earn a small commission (coming soon).\n\n"
            "_You are currently in TEST mode. In LIVE mode, all payments will be processed "
            "via Cashfree and withdrawals will go directly to your bank._"
        )
        await query.message.edit_text(text, parse_mode="Markdown")
        return

    # Info about Cashfree test mode (for the fallback button)
    if data == "info:cashfree_test":
        text = (
            "ℹ️ *Cashfree TEST mode*\n\n"
            "Right now we are in sandbox/testing mode. To fully test the payment flow, "
            "create a Cashfree Payment Link in your dashboard and paste that URL into "
            "`TEST_CASHFREE_LINK_URL` in the bot code.\n\n"
            "Then, when you tap the Pay button, it will open that test link."
        )
        await query.message.edit_text(text, parse_mode="Markdown")
        return

    # TEST payment confirmation → unlock link
    if data.startswith("test_paid:"):
        short_code = data.split(":", 1)[1]

        if short_code != TEST_SHORT_CODE:
            await query.message.edit_text("❌ Unknown or expired paid link.")
            return

        # Mark as unlocked (so we could later reuse this info)
        UNLOCKED_USERS.add((user.id, short_code))

        text = (
            "✅ *TEST payment confirmed*\n\n"
            "_In real LIVE mode, the bot will check your payment with Cashfree before unlocking._\n\n"
            f"Here is your unlocked link:\n{TEST_LOCKED_URL}"
        )
        await query.message.edit_text(text, parse_mode="Markdown", disable_web_page_preview=False)
        return


# ================== MAIN ==================


def main() -> None:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("User bot (%s) started.", BRAND_NAME)
    app.run_polling()


if __name__ == "__main__":
    main()
