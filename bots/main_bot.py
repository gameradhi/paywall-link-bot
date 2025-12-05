# bots/main_bot.py
# TELE LINK – Main/User Bot with Cashfree TEST integration
# Bot: @TeleShortLinkBot

import logging
import uuid
from datetime import datetime

import requests
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ============ BASIC CONFIG ============

BOT_TOKEN = "8301086845:AAFFFiYItPrAwgQmWLhgmS_TztqcjWx5S28"

# Force join channel
FORCE_CHANNEL_USERNAME = "TeleLinkUpdate"   # without @
FORCE_CHANNEL_ID = -1003472900442

# Admin / owner
OWNER_ID = 8545081401       # @AntManIndia
OWNER_USERNAME = "AntManIndia"

BRAND_NAME = "TELE LINK"
CURRENCY_SYMBOL = "₹"

# ============ CASHFREE TEST CONFIG ============

CF_BASE_URL = "https://sandbox.cashfree.com/pg"
CF_APP_ID = "TEST108989973cdf272dd10fda500fcd79989801"
CF_SECRET = "cfsk_ma_test_7c3535ef3e930f31810a450c342308b4_d6795ca8"
CF_API_VERSION = "2022-09-01"
CF_CURRENCY = "INR"

# NOTE for LIVE later:
# CF_BASE_URL = "https://api.cashfree.com/pg"
# CF_APP_ID   = "<LIVE APP ID>"
# CF_SECRET   = "<LIVE SECRET>"


# ============ SIMPLE IN-MEMORY STORAGE (TEST ONLY) ============

PAID_LINKS = {}      # short_code -> dict(original_url, price, creator_id)
PENDING_ORDERS = {}  # order_id -> dict(user_id, short_code, amount)


def seed_test_link():
    """
    Create one test paid link in memory so you can test the full payment flow.
    Later this will be replaced with DB links from Creator Bot.
    """
    short_code = "TEST001"
    PAID_LINKS[short_code] = {
        "original_url": "https://example.com/my-super-secret-file",
        "price": 20.0,
        "creator_id": OWNER_ID,
    }


# ============ LOGGING ============

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ============ FORCE JOIN CHECK ============

async def ensure_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Returns True if user is member of the update channel.
    If not, sends join message and returns False.
    """
    user = update.effective_user
    chat_id = update.effective_chat.id

    try:
        member = await context.bot.get_chat_member(FORCE_CHANNEL_ID, user.id)
        if member.status in ("member", "creator", "administrator"):
            return True
    except Exception as e:
        logger.warning("Force join check failed: %s", e)
        # If bot not admin or channel not found – skip force join
        return True

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📢 Join TELE LINK Updates",
                    url=f"https://t.me/{FORCE_CHANNEL_USERNAME}",
                )
            ],
            [InlineKeyboardButton("✅ I Joined", callback_data="check_join")],
        ]
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"After joining, tap *I Joined*.\n\n"
            f"To use *{BRAND_NAME}* you must join our update channel first."
        ),
        reply_markup=keyboard,
        parse_mode="Markdown",
    )
    return False


async def check_join_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        member = await context.bot.get_chat_member(FORCE_CHANNEL_ID, query.from_user.id)
        if member.status in ("member", "creator", "administrator"):
            await show_main_menu(query, context)
            return
    except Exception as e:
        logger.warning("Force join re-check failed: %s", e)
        await show_main_menu(query, context)
        return

    await query.edit_message_text(
        "❌ You have not joined the channel yet. Please join and try again."
    )


# ============ CASHFREE HELPERS ============

def create_cashfree_order(user_id: int, amount: float, description: str):
    """
    Creates an order in Cashfree (TEST).
    Returns: (payment_link, order_id, error_text)
    If success: payment_link + order_id, error_text=None
    If fail: payment_link=None, order_id=None, error_text contains reason
    """
    order_id = f"TL_{user_id}_{uuid.uuid4().hex[:8]}"

    payload = {
        "order_id": order_id,
        "order_amount": float(amount),
        "order_currency": CF_CURRENCY,
        "order_note": description[:60],
        "customer_details": {
            "customer_id": str(user_id),
            "customer_phone": "9999999999",
            "customer_email": "test@example.com",
        },
    }

    headers = {
        "x-client-id": CF_APP_ID,
        "x-client-secret": CF_SECRET,
        "x-api-version": CF_API_VERSION,
        "Content-Type": "application/json",
    }

    try:
        url = f"{CF_BASE_URL}/orders"
        logger.info("Creating Cashfree order at %s with payload %s", url, payload)
        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        text = resp.text
        logger.info("Cashfree response [%s]: %s", resp.status_code, text)

        try:
            data = resp.json()
        except Exception:
            data = {}

        if resp.status_code == 200 and data.get("order_status") == "ACTIVE":
            return data.get("payment_link"), order_id, None

        # some error from Cashfree
        err_msg = f"{resp.status_code}: {text[:200]}"
        return None, None, err_msg

    except Exception as e:
        logger.error("Cashfree exception: %s", e)
        return None, None, str(e)


# ============ UI BUILDERS ============

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🙋 Continue as User", callback_data="as_user"),
            ],
            [
                InlineKeyboardButton("🧑‍💻 Continue as Creator", callback_data="as_creator"),
            ],
            [
                InlineKeyboardButton("❓ Help", callback_data="help"),
            ],
        ]
    )


def user_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧾 My Purchases (coming soon)", callback_data="nop")],
            [InlineKeyboardButton("🧑‍💻 Become Creator", callback_data="as_creator")],
            [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="back_main")],
        ]
    )


# ============ HANDLERS ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start and deep-links for paid links."""
    user = update.effective_user

    # Seed one test link first time
    if not PAID_LINKS:
        seed_test_link()

    if not await ensure_force_join(update, context):
        return

    args = context.args or []

    # Deep-link: /start pl_CODE
    if args and args[0].startswith("pl_"):
        short_code = args[0][3:]
        await show_paid_link_screen(update, context, short_code)
        return

    greeting = (
        f"Hey {user.first_name} 👋\n\n"
        f"Welcome to *{BRAND_NAME}*.\n\n"
        "• Creators can lock any link behind a small payment.\n"
        "• Users pay once to unlock and access the content.\n\n"
        "Choose how you want to continue:"
    )
    if update.message:
        await update.message.reply_text(
            greeting, reply_markup=main_menu_keyboard(), parse_mode="Markdown"
        )
    else:
        await update.callback_query.edit_message_text(
            greeting, reply_markup=main_menu_keyboard(), parse_mode="Markdown"
        )


async def show_main_menu(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    user = (
        update_or_query.from_user
        if hasattr(update_or_query, "from_user")
        else update_or_query.effective_user
    )
    text = (
        f"Hey {user.first_name} 👋\n\n"
        f"Welcome back to *{BRAND_NAME}*.\n"
        "Choose how you want to continue:"
    )
    await update_or_query.edit_message_text(
        text, reply_markup=main_menu_keyboard(), parse_mode="Markdown"
    )


async def as_user_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = (
        "🙋 *User Mode*\n\n"
        "You can unlock paid links created by TELE LINK creators.\n\n"
        "Right now this is a TEST setup.\n"
        "Use any paid link you receive (starting with `/start pl_...`) and "
        "you will see the paywall with Cashfree TEST payment."
    )
    await query.edit_message_text(
        text, reply_markup=user_home_keyboard(), parse_mode="Markdown"
    )


async def as_creator_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = (
        "🧑‍💻 *Creator Mode*\n\n"
        "To create paid links, please go to our Creator Bot:\n\n"
        "👉 @TeleShortLinkCreatorBot\n\n"
        "There you can set price, get your unique link and share it.\n"
        "Users will unlock it here in this bot."
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🚀 Open Creator Bot", url="https://t.me/TeleShortLinkCreatorBot"
                )
            ],
            [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="back_main")],
        ]
    )
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def help_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = (
        "❓ *Help & Support*\n\n"
        f"If you are stuck, message our admin:\n"
        f"👨‍💻 @{OWNER_USERNAME}\n\n"
        "Describe your issue clearly and send screenshots if needed."
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("◀️ Back to Main Menu", callback_data="back_main")]]
    )
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def back_main_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_main_menu(query, context)


async def nop_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Coming soon…", show_alert=False)


# ============ PAID LINK FLOW ============

async def show_paid_link_screen(update: Update, context: ContextTypes.DEFAULT_TYPE, short_code: str):
    """Show the paywall for a given short_code."""
    if not await ensure_force_join(update, context):
        return

    link = PAID_LINKS.get(short_code)
    if not link:
        text = "❌ This paid link is invalid or expired."
        if update.message:
            await update.message.reply_text(text)
        else:
            await update.callback_query.edit_message_text(text)
        return

    price = link["price"]
    description = (
        f"🔒 *Paid Link*\n\n"
        f"Creator has locked this content.\n"
        f"To unlock, pay *{CURRENCY_SYMBOL}{price}*.\n\n"
        "⚠️ You are currently in *TEST MODE* with Cashfree sandbox.\n"
        "No real money will be taken."
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"💳 Pay {CURRENCY_SYMBOL}{price} (Cashfree TEST)",
                    callback_data=f"cfpay_{short_code}",
                )
            ],
            [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="back_main")],
        ]
    )

    if update.message:
        await update.message.reply_text(
            description, reply_markup=keyboard, parse_mode="Markdown"
        )
    else:
        await update.callback_query.edit_message_text(
            description, reply_markup=keyboard, parse_mode="Markdown"
        )


async def cfpay_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User clicked Pay with Cashfree (TEST)."""
    query = update.callback_query
    await query.answer()

    _, short_code = query.data.split("_", 1)
    link = PAID_LINKS.get(short_code)
    if not link:
        await query.edit_message_text("❌ This paid link is invalid or expired.")
        return

    amount = link["price"]

    await query.edit_message_text("⏳ Creating Cashfree TEST order…")

    payment_link, order_id, err = create_cashfree_order(
        query.from_user.id,
        amount,
        f"Paid link {short_code}",
    )

    if not payment_link:
        err_text = err or "Unknown error"
        await query.edit_message_text(
            "❌ Failed to create Cashfree TEST payment link.\n\n"
            f"Error from Cashfree:\n`{err_text}`\n\n"
            "If this keeps happening, please send this message to admin.",
            parse_mode="Markdown",
        )
        return

    # Save pending order (TEST only, in memory)
    PENDING_ORDERS[order_id] = {
        "user_id": query.from_user.id,
        "short_code": short_code,
        "amount": amount,
        "created_at": datetime.utcnow().isoformat(),
    }

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔗 Open Payment Page", url=payment_link)],
            [
                InlineKeyboardButton(
                    "✅ I’ve Paid (TEST)", callback_data=f"cfpaid_{order_id}"
                )
            ],
            [InlineKeyboardButton("◀️ Back to Main Menu", callback_data="back_main")],
        ]
    )

    await query.edit_message_text(
        f"💳 *Cashfree Sandbox Payment*\n\n"
        f"Amount: *{CURRENCY_SYMBOL}{amount}*\n\n"
        "1️⃣ Tap *Open Payment Page* and complete the TEST payment.\n"
        "2️⃣ Then tap *I’ve Paid (TEST)* to unlock the link.\n\n"
        "_Note: This is TEST mode, real money is not charged._",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


async def cfpaid_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User clicked I've Paid (TEST) – we directly unlock in test mode."""
    query = update.callback_query
    await query.answer()

    _, order_id = query.data.split("_", 1)
    order = PENDING_ORDERS.pop(order_id, None)

    if not order:
        await query.edit_message_text("⚠️ No pending order found for this payment.")
        return

    short_code = order["short_code"]
    link = PAID_LINKS.get(short_code)

    if not link:
        await query.edit_message_text("❌ Paid link not found anymore.")
        return

    original_url = link["original_url"]

    text = (
        "✅ *Payment marked successful (TEST)*\n\n"
        "Here is your unlocked link 👇\n"
        f"{original_url}\n\n"
        "_In LIVE mode this will work only after real payment confirmation from Cashfree._"
    )

    await query.edit_message_text(text, parse_mode="Markdown")


# ============ MAIN ============

def main():
    seed_test_link()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))

    # Callbacks
    app.add_handler(CallbackQueryHandler(check_join_cb, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(as_user_cb, pattern="^as_user$"))
    app.add_handler(CallbackQueryHandler(as_creator_cb, pattern="^as_creator$"))
    app.add_handler(CallbackQueryHandler(help_cb, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(back_main_cb, pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(nop_cb, pattern="^nop$"))

    app.add_handler(CallbackQueryHandler(cfpay_cb, pattern=r"^cfpay_"))
    app.add_handler(CallbackQueryHandler(cfpaid_cb, pattern=r"^cfpaid_"))

    logger.info("Starting TELE LINK main bot (TEST Cashfree)…")
    app.run_polling()


if __name__ == "__main__":
    main()
