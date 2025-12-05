import logging
import os
import sys

# Make sure Python can import db.py (parent folder)
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

from db import (
    init_db,
    upsert_creator,
    get_creator_wallet,
    get_creator_by_tg_id,
    get_creator_by_referral_code,
    set_creator_payout_details,
    create_paid_link,
    get_links_for_creator,
    create_withdrawal_request,
)

# === CREATOR BOT TOKEN ===
BOT_TOKEN = "8280706073:AAED9i2p0TP42pPf9vMXoTt_HYGxqEuyy2w"

# === MAIN BOT USERNAME (for share links) ===
MAIN_BOT_USERNAME = "TeleShortLinkBot"

# === FORCE JOIN CHANNEL ===
FORCE_CHANNEL_ID = -1003472900442
FORCE_CHANNEL_LINK = "https://t.me/TeleLinkUpdate"

# === MINIMUM WITHDRAWAL ===
MIN_WITHDRAW = 100  # ₹100

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ----------------- FORCE JOIN -----------------


async def ensure_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Returns True if user is in channel (or check fails).
    If not joined, sends join message and returns False.
    """
    user = update.effective_user

    try:
        member = await context.bot.get_chat_member(FORCE_CHANNEL_ID, user.id)
        if member.status in ("member", "administrator", "creator"):
            return True
    except Exception as e:
        # If something breaks (e.g. bot not admin), don't block user
        logger.warning("Force-join check failed: %s", e)
        return True

    text = (
        "🔔 To use the *TELE LINK Creator Panel*, please join our updates channel first.\n\n"
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


# ----------------- MAIN MENU -----------------


def build_main_menu(title: str = "TELE LINK Creator Dashboard"):
    buttons = [
        [InlineKeyboardButton("🔗 Create Paid Link", callback_data="create")],
        [
            InlineKeyboardButton("💰 Wallet & Earnings", callback_data="earnings"),
            InlineKeyboardButton("📊 My Links", callback_data="stats"),
        ],
        [InlineKeyboardButton("🏦 Bank / UPI", callback_data="bank")],
        [InlineKeyboardButton("👥 Refer & Earn", callback_data="refer")],
        [InlineKeyboardButton("❓ Help", callback_data="creator_help")],
    ]
    return title, InlineKeyboardMarkup(buttons)


async def show_main_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    title: str = "TELE LINK Creator Dashboard",
):
    title, kb = build_main_menu(title)
    if update.callback_query:
        await update.callback_query.edit_message_text(title, reply_markup=kb)
    else:
        await update.message.reply_text(title, reply_markup=kb)


# ----------------- /start & /menu -----------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_force_join(update, context):
        return

    user = update.effective_user
    creator = get_creator_by_tg_id(user.id)

    if creator:
        await update.message.reply_text(
            f"Hey {user.first_name or 'Creator'} 👋\n"
            "Welcome back to your TELE LINK Creator Panel."
        )
        await show_main_menu(update, context)
        return

    btn = KeyboardButton(text="📲 Share Phone Number", request_contact=True)
    kb = ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "Hey 👋\n\n"
        "This is your *TELE LINK Creator Panel*.\n"
        "Create paid links and earn money every time someone unlocks your content.\n\n"
        "First, verify yourself by sharing your phone number.",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_force_join(update, context):
        return
    await show_main_menu(update, context)


# ----------------- LOGIN FLOW -----------------


async def save_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_force_join(update, context):
        return

    contact = update.message.contact
    context.user_data["phone"] = contact.phone_number
    context.user_data["login_state"] = "awaiting_referral"

    await update.message.reply_text(
        "Number verified ✅\n\n"
        "If any creator referred you, send their *referral code* now.\n"
        "If not, simply type `no`.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )


# ----------------- TEXT HANDLER -----------------


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_force_join(update, context):
        return

    user = update.effective_user
    msg = (update.message.text or "").strip()

    login_state = context.user_data.get("login_state")
    flow_state = context.user_data.get("state")

    # ---------- 1) Referral step on first login ----------
    if login_state == "awaiting_referral":
        ref_code = None
        ref_info_text = None

        if msg.lower() != "no":
            ref_code = msg
            ref_creator = get_creator_by_referral_code(ref_code)
            if ref_creator:
                uname = ref_creator.get("username")
                if uname:
                    ref_info_text = f"🎉 You joined using referral code of @{uname}"
                else:
                    ref_info_text = "🎉 You joined using a creator's referral code."

        phone = context.user_data.get("phone", "")

        upsert_creator(
            tg_id=user.id,
            username=user.username or "",
            full_name=user.full_name or "",
            phone=phone,
            referred_by_code=ref_code,
        )

        context.user_data["login_state"] = None

        extra = f"\n\n{ref_info_text}" if ref_info_text else ""
        await update.message.reply_text(
            "You’re now registered as a TELE LINK Creator 🎉" + extra
        )
        await show_main_menu(update, context)
        return

    # ---------- 2) Create link: waiting for URL ----------
    if flow_state == "awaiting_url":
        if not (msg.startswith("http://") or msg.startswith("https://")):
            await update.message.reply_text(
                "Please send a *valid* URL starting with http or https.",
                parse_mode="Markdown",
            )
            return

        context.user_data["new_link_url"] = msg
        context.user_data["state"] = "awaiting_price"

        await update.message.reply_text(
            "Nice 🔗\nNow send the *price in ₹* that users must pay to unlock this link.\n\nExample: `20`",
            parse_mode="Markdown",
        )
        return

    # ---------- 3) Create link: waiting for price ----------
    if flow_state == "awaiting_price":
        if not msg.isdigit():
            await update.message.reply_text(
                "Price must be a number in rupees, for example: 10, 20, 50."
            )
            return

        price = int(msg)
        if price <= 0:
            await update.message.reply_text("Price must be more than 0 ₹.")
            return

        original_url = context.user_data.get("new_link_url")
        if not original_url:
            context.user_data["state"] = None
            await update.message.reply_text(
                "Something went wrong, please try creating the link again."
            )
            return

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
            f"🔗 Original URL:\n{original_url}\n\n"
            f"💰 Price per unlock: ₹{price}\n\n"
            f"Share this link to start earning:\n`{short_link}`",
            parse_mode="Markdown",
        )

        title, kb = build_main_menu("TELE LINK Creator Dashboard")
        await update.message.reply_text("Back to your dashboard 👇", reply_markup=kb)
        return

    # ---------- 4) Bank / UPI: waiting for UPI ID ----------
    if flow_state == "awaiting_upi":
        upi_id = msg
        set_creator_payout_details(
            tg_id=user.id,
            upi_id=upi_id,
            bank_account=None,
            bank_ifsc=None,
        )
        context.user_data["state"] = None
        await update.message.reply_text(
            f"✅ UPI ID saved:\n`{upi_id}`",
            parse_mode="Markdown",
        )
        await show_main_menu(update, context)
        return

    # ---------- 5) Bank details: waiting for account ----------
    if flow_state == "awaiting_bank_acc":
        context.user_data["bank_account"] = msg
        context.user_data["state"] = "awaiting_bank_ifsc"
        await update.message.reply_text(
            "Got it ✅\nNow send your *bank IFSC code* (e.g., `HDFC0001234`).",
            parse_mode="Markdown",
        )
        return

    # ---------- 6) Bank details: waiting for IFSC ----------
    if flow_state == "awaiting_bank_ifsc":
        bank_account = context.user_data.get("bank_account")
        bank_ifsc = msg

        set_creator_payout_details(
            tg_id=user.id,
            upi_id=None,
            bank_account=bank_account,
            bank_ifsc=bank_ifsc,
        )
        context.user_data["state"] = None
        context.user_data.pop("bank_account", None)

        await update.message.reply_text("✅ Bank details saved.")
        await show_main_menu(update, context)
        return

    # ---------- 7) Withdrawal: waiting for amount ----------
    if flow_state == "awaiting_withdraw_amount":
        if not msg.isdigit():
            await update.message.reply_text(
                "Amount must be a number in rupees, for example: 100, 200."
            )
            return

        amount = int(msg)
        if amount < MIN_WITHDRAW:
            await update.message.reply_text(
                f"Minimum withdrawal is ₹{MIN_WITHDRAW}.",
            )
            return

        wallet = get_creator_wallet(user.id)
        if not wallet or wallet["wallet_balance"] < amount:
            await update.message.reply_text(
                "You don’t have enough balance to withdraw that amount."
            )
            context.user_data["state"] = None
            return

        method = context.user_data.get("withdraw_method")
        if method == "upi":
            upi_id = wallet["upi_id"]
            ok = create_withdrawal_request(
                creator_tg_id=user.id,
                amount=amount,
                method_type="upi",
                upi_id=upi_id,
                bank_account=None,
                bank_ifsc=None,
            )
        else:
            bank_acc = wallet["bank_account"]
            bank_ifsc = wallet["bank_ifsc"]
            ok = create_withdrawal_request(
                creator_tg_id=user.id,
                amount=amount,
                method_type="bank",
                upi_id=None,
                bank_account=bank_acc,
                bank_ifsc=bank_ifsc,
            )

        context.user_data["state"] = None
        context.user_data["withdraw_method"] = None

        if not ok:
            await update.message.reply_text(
                "You don’t have enough balance to withdraw that amount."
            )
            return

        await update.message.reply_text(
            "✅ Withdrawal request created.\n\n"
            "Your balance is reduced now. Admin will send payout to your UPI/Bank.\n"
            "Later this will be *automatic* when payout API is connected."
        )
        await show_main_menu(update, context)
        return

    # ---------- Default ----------
    await update.message.reply_text(
        "Use the buttons below or type /menu to open your dashboard 👇"
    )


# ----------------- BUTTON HANDLER -----------------


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_force_join(update, context):
        return

    query = update.callback_query
    data = query.data
    user = query.from_user

    await query.answer()

    # Check after "I Joined"
    if data == "check_sub":
        if await ensure_force_join(update, context):
            await query.message.reply_text(
                "✅ Thanks for joining TELE LINK Updates!\nHere is your creator dashboard:",
            )
            await show_main_menu(update, context)
        return

    # CREATE LINK
    if data == "create":
        context.user_data["state"] = "awaiting_url"
        await query.edit_message_text(
            "🔗 *Create Paid Link*\n\n"
            "Send me the *original URL* you want to lock.",
            parse_mode="Markdown",
        )
        return

    # EARNINGS
    if data == "earnings":
        wallet = get_creator_wallet(user.id)
        if not wallet:
            await query.edit_message_text(
                "You are not registered as a creator.\nSend /start again."
            )
            return

        bal = wallet["wallet_balance"]
        total = wallet["total_earned"]
        ref = wallet["referral_earned"]

        text = (
            "💰 *Your Wallet (TELE LINK)*\n\n"
            f"Available balance: ₹{bal}\n"
            f"Total earned: ₹{total}\n"
            f"From referrals: ₹{ref}\n\n"
            f"Minimum withdrawal: ₹{MIN_WITHDRAW}"
        )

        buttons = [[InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]]
        if bal >= MIN_WITHDRAW:
            buttons.insert(0, [InlineKeyboardButton("📤 Withdraw", callback_data="withdraw")])

        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    # STATS
    if data == "stats":
        links = get_links_for_creator(user.id)
        if not links:
            await query.edit_message_text(
                "📊 You have no links yet.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]]
                ),
            )
            return

        lines = ["📊 *Your Recent Links:*", ""]
        for link in links[:5]:
            lines.append(
                f"Code: `{link['code']}`\n"
                f"Price: ₹{link['price']}\n"
                f"Clicks: {link['clicks']}\n"
                f"Earnings: ₹{link['earnings']}\n"
            )
        text = "\n".join(lines)

        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]]
            ),
        )
        return

    # BANK / UPI
    if data == "bank":
        wallet = get_creator_wallet(user.id)
        upi = wallet["upi_id"] if wallet else None
        bank_acc = wallet["bank_account"] if wallet else None
        bank_ifsc = wallet["bank_ifsc"] if wallet else None

        current = "Current payout details:\n"
        if upi:
            current += f"• UPI: `{upi}`\n"
        if bank_acc and bank_ifsc:
            current += f"• Bank: `{bank_acc}` / `{bank_ifsc}`\n"
        if not (upi or bank_acc):
            current += "• None saved yet.\n"

        buttons = [
            [InlineKeyboardButton("Set UPI ID", callback_data="set_upi")],
            [InlineKeyboardButton("Set Bank Details", callback_data="set_bank")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")],
        ]

        await query.edit_message_text(
            f"🏦 *Bank / UPI*\n\n{current}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    # REFER & EARN
    if data == "refer":
        creator = get_creator_by_tg_id(user.id)
        wallet = get_creator_wallet(user.id)
        if not creator or not wallet:
            await query.edit_message_text(
                "You are not registered as a creator.\nSend /start again."
            )
            return

        rcode = creator["referral_code"]
        ref_earned = wallet["referral_earned"]

        text = (
            "👥 *Refer & Earn (Money Focus)*\n\n"
            "Invite other creators to TELE LINK.\n"
            "Whenever *your referrals* earn from their links, you get *extra 5%* from our platform share.\n\n"
            f"Your referral code:\n`{rcode}`\n\n"
            f"Referral earnings till now: ₹{ref_earned}"
        )

        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]]
            ),
        )
        return

    # HELP
    if data == "creator_help":
        await query.edit_message_text(
            "❓ *Help*\n\n"
            "For support or questions, message the admin:\n@TeleShortLinkAdminBot",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]]
            ),
        )
        return

    # SET UPI
    if data == "set_upi":
        context.user_data["state"] = "awaiting_upi"
        await query.edit_message_text(
            "Send your *UPI ID* (example: `name@okicici`).",
            parse_mode="Markdown",
        )
        return

    # SET BANK
    if data == "set_bank":
        context.user_data["state"] = "awaiting_bank_acc"
        await query.edit_message_text(
            "Send your *bank account number*.",
            parse_mode="Markdown",
        )
        return

    # WITHDRAW
    if data == "withdraw":
        wallet = get_creator_wallet(user.id)
        if not wallet:
            await query.edit_message_text("You are not registered as a creator.")
            return

        bal = wallet["wallet_balance"]
        upi = wallet["upi_id"]
        bank_acc = wallet["bank_account"]
        bank_ifsc = wallet["bank_ifsc"]

        if bal < MIN_WITHDRAW:
            await query.edit_message_text(
                f"You need at least ₹{MIN_WITHDRAW} to withdraw.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]]
                ),
            )
            return

        if not (upi or (bank_acc and bank_ifsc)):
            await query.edit_message_text(
                "You have enough balance, but no payout details saved.\n\n"
                "Please set UPI or bank details first in *Bank / UPI* menu.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")]]
                ),
            )
            return

        # both methods available → choose
        if upi and bank_acc and bank_ifsc:
            buttons = [
                [InlineKeyboardButton("Withdraw to UPI", callback_data="withdraw_upi")],
                [InlineKeyboardButton("Withdraw to Bank", callback_data="withdraw_bank")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="back_menu")],
            ]
            await query.edit_message_text(
                f"Your balance: ₹{bal}\n\nChoose withdrawal method:",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
            return

        # only one method
        if upi:
            context.user_data["withdraw_method"] = "upi"
        else:
            context.user_data["withdraw_method"] = "bank"

        context.user_data["state"] = "awaiting_withdraw_amount"
        await query.edit_message_text(
            f"Your balance: ₹{bal}\n\nSend the *amount in ₹* you want to withdraw.",
            parse_mode="Markdown",
        )
        return

    # WITHDRAW via UPI
    if data == "withdraw_upi":
        wallet = get_creator_wallet(user.id)
        bal = wallet["wallet_balance"] if wallet else 0

        context.user_data["withdraw_method"] = "upi"
        context.user_data["state"] = "awaiting_withdraw_amount"

        await query.edit_message_text(
            f"Your balance: ₹{bal}\n\nSend the *amount in ₹* you want to withdraw.",
            parse_mode="Markdown",
        )
        return

    # WITHDRAW via BANK
    if data == "withdraw_bank":
        wallet = get_creator_wallet(user.id)
        bal = wallet["wallet_balance"] if wallet else 0

        context.user_data["withdraw_method"] = "bank"
        context.user_data["state"] = "awaiting_withdraw_amount"

        await query.edit_message_text(
            f"Your balance: ₹{bal}\n\nSend the *amount in ₹* you want to withdraw.",
            parse_mode="Markdown",
        )
        return

    # BACK TO MENU
    if data == "back_menu":
        await show_main_menu(update, context)
        return


# ----------------- MAIN -----------------


def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(MessageHandler(filters.CONTACT, save_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.run_polling()


if __name__ == "__main__":
    main()
