# bots/main_bot.py
# TELE LINK – Main/User Bot with Cashfree TEST payment links
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
FORCE_CHANNEL_ID = -1003472900442          # your updates channel ID

# Admin / owner
OWNER_ID = 8545081401                      # @AntManIndia
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
# CF_APP_ID = "<LIVE APP ID>"
# CF_SECRET = "<LIVE SECRET>"

# ============ SIMPLE IN-MEMORY STORAGE (TEST ONLY) ============

# short_code -> dict(original_url, price, creator_id)
PAID_LINKS: dict[str, dict] = {}

# order_id -> dict(user_id, short_code, amount)
PENDING_ORDERS: dict[str, dict] = {}


def seed_test_link() -> None:
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


# ============ HELPER: FORCE JOIN ============

async def ensure_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Returns True if user is already in updates channel or force-join is disabled.
    If not joined, sends join prompt and returns False.
    """
    if not FORCE_CHANNEL_ID:
        return True  # force join disabled

    user = update.effective_user
    chat_id = update.effective_chat.id

    try:
        member = await context.bot.get_chat_member(FORCE_CHANNEL_ID, user.id)
        if member.status in ("member", "administrator", "creator"):
            return True
    except Exception as e:
        # If channel not found / bot not admin etc., log & skip force-join
        logger.warning("Force-join check failed: %s", e)
        return True

    # Not a member → show join button
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=f"📢 Join TELE LINK Updates",
                    url=f"https://t.me/{FORCE_CHANNEL_USERNAME}",
                )
            ],
            [InlineKeyboardButton(text="✅ I Joined", callback_data="CHECK_JOIN")],
        ]
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text="To use TELE LINK, please join our updates channel first.",
        reply_markup=keyboard,
    )
    return False


# ============ HELPER: MAIN MENU ============

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧑‍💻 Continue as User", callback_data="AS_USER")],
            [InlineKeyboardButton("👨‍🎨 Continue as Creator", callback_data="AS_CREATOR")],
            [InlineKeyboardButton("❓ Help", callback_data="HELP")],
        ]
    )


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user

    text = (
        f"Hey {user.first_name} 👋\n\n"
        f"Welcome to {BRAND_NAME}.\n\n"
        "• Creators can lock any link behind a small payment.\n"
        "• Users pay once to unlock and access the content.\n\n"
        "Choose how you want to continue:"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=main_menu_keyboard(),
    )


# ============ CASHFREE HELPER ============

def create_cashfree_payment_link(
    *,
    amount: float,
    short_code: str,
    user_id: int,
) -> str:
    """
    Calls Cashfree TEST Payment Links API and returns the URL.
    Raises Exception on any error.
    """
    url = f"{CF_BASE_URL}/links"

    order_id = f"{short_code}-{user_id}-{uuid.uuid4().hex[:8]}"
    payload = {
        "link_amount": amount,
        "link_currency": CF_CURRENCY,
        "link_id": order_id,
        "link_purpose": f"{BRAND_NAME} – Unlock content {short_code}",
        "customer_details": {
            "customer_name": "TeleLink User",
            "customer_phone": "9999999999",
            "customer_email": "test@example.com",
        },
    }

    headers = {
        "Content-Type": "application/json",
        "x-api-version": CF_API_VERSION,
        "x-client-id": CF_APP_ID,
        "x-client-secret": CF_SECRET,
    }

    logger.info("Creating Cashfree test link: %s", payload)

    resp = requests.post(url, json=payload, headers=headers, timeout=15)
    logger.info(
        "Cashfree response [%s]: %s", resp.status_code, resp.text.replace("\n", " ")
    )

    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}

    if resp.status_code != 200:
        msg = data.get("message") or data.get("error") or str(data)
        raise Exception(f"Cashfree error (status {resp.status_code}): {msg}")

    # Payment Links API returns "link_url"
    payment_url = (
        data.get("link_url")
        or data.get("payment_link")
        or data.get("url")
    )

    if not payment_url:
        raise Exception(f"Cashfree success but no link_url found. Response: {data}")

    # store minimal info for later (webhook / manual check)
    PENDING_ORDERS[order_id] = {
        "user_id": user_id,
        "short_code": short_code,
        "amount": amount,
        "created_at": datetime.utcnow().isoformat(),
    }

    return payment_url


# ============ COMMAND HANDLERS ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user

    # 1) Check force join
    if not await ensure_force_join(update, context):
        return

    # 2) Deep-link parameter (e.g. /start pl_TEST001)
    args = context.args
    if args:
        param = args[0]
        if param.startswith("pl_"):
            short_code = param.replace("pl_", "", 1)
            await start_with_paid_link(update, context, short_code)
            return

    # 3) Normal start → main menu
    await show_main_menu(update, context)


async def start_with_paid_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    short_code: str,
) -> None:
    """
    User opened t.me/bot?start=pl_SHORTCODE
    """
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # Ensure still in channel (in case they left & click link later)
    if not await ensure_force_join(update, context):
        return

    info = PAID_LINKS.get(short_code)
    if not info:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ This paid link is invalid or expired.",
        )
        return

    price = float(info["price"])

    try:
        pay_url = create_cashfree_payment_link(
            amount=price,
            short_code=short_code,
            user_id=user_id,
        )
    except Exception as e:
        logger.error("Failed to create Cashfree test link: %s", e)
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "❌ Failed to create Cashfree TEST payment link.\n"
                f"Error from Cashfree: {e}\n\n"
                "If this keeps happening, please send this message to admin."
            ),
        )
        return

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=f"💳 Pay {CURRENCY_SYMBOL}{price:.2f} (Cashfree TEST)",
                    url=pay_url,
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Back to Main Menu", callback_data="BACK_MAIN"
                )
            ],
        ]
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"Here is your *TEST* payment link for `{short_code}`.\n\n"
            "Complete the payment on Cashfree's sandbox page.\n"
            "_No real money will be taken in TEST mode._"
        ),
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


# ============ CALLBACK HANDLER ============

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "CHECK_JOIN":
        # Re-run /start after user says "I Joined"
        await start(update, context)
        return

    if data == "BACK_MAIN":
        await show_main_menu(update, context)
        return

    if data == "AS_USER":
        await query.edit_message_text(
            "🧑‍💻 *User mode*\n\n"
            "You can open paid links like this:\n"
            "`https://t.me/TeleShortLinkBot?start=pl_TEST001`\n\n"
            "In future we will show your unlocked links and purchase history here.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="BACK_MAIN")]]
            ),
        )
        return

    if data == "AS_CREATOR":
        await query.edit_message_text(
            "👨‍🎨 *Creator Panel*\n\n"
            "This is the user bot. To *create* paid links and manage earnings,\n"
            "please use the Creator Bot: @TeleShortLinkCreatorBot",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="BACK_MAIN")]]
            ),
        )
        return

    if data == "HELP":
        await query.edit_message_text(
            "❓ *How TELE LINK works*\n\n"
            "1️⃣ Creators generate paid links in the Creator Bot.\n"
            "2️⃣ Users open those links here and pay via Cashfree.\n"
            "3️⃣ After successful payment, users get access to the original URL.\n\n"
            "This is *TEST* mode right now – no real money is charged.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="BACK_MAIN")]]
            ),
        )
        return


# ============ MAIN ============

def main() -> None:
    seed_test_link()

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(on_callback))

    logger.info("User bot (TELE LINK) started with Cashfree TEST mode.")
    application.run_polling()


if __name__ == "__main__":
    main()
