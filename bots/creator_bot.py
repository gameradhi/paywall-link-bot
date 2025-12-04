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
    set_creator_payout_details,
    create_paid_link,
    get_links_for_creator,
    create_withdrawal_request,
)

# === CREATOR BOT TOKEN ===
BOT_TOKEN = "8280706073:AAED9i2p0TP42pPf9vMXoTt_HYGxqEuyy2w"

# === MAIN BOT USERNAME (for share links) ===
MAIN_BOT_USERNAME = "TeleShortLinkBot"

MIN_WITHDRAW = 100  # ₹100 min withdrawal

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ------------- /start -------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    creator = get_creator_by_tg_id(user.id)

    # If already registered, go directly to menu
    if creator:
        await show_main_menu(update, context, "Welcome back Creator 👋")
        return

    # Ask for phone to register
    btn = KeyboardButton(text="📲 Share Phone Number", request_contact=True)
    kb = ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "Welcome Creator 👋\n\nPlease verify login by sharing your phone number.",
        reply_markup=kb,
    )


# ------------- LOGIN FLOW -------------

async def save_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    user = update.effective_user

    context.user_data["phone"] = contact.phone_number
    context.user_data["login_state"] = "awaiting_referral"

    await update.message.reply_text(
        "Number verified ✅\n\nDo you have referral code?\n• Send it now\n• Or type 'no'",
        reply_markup=ReplyKeyboardRemove(),
    )


# ------------- TEXT HANDLER -------------

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = (update.message.text or "").strip()

    login_state = context.user_data.get("login_state")
    flow_state = context.user_data.get("state")

    # 1) Referral step on first login
    if login_state == "awaiting_referral":
        if msg.lower() == "no":
            ref_code = None
        else:
            ref_code = msg

        phone = context.user_data.get("phone", "")

        upsert_creator(
            tg_id=user.id,
            username=user.username or "",
            full_name=user.full_name or "",
            phone=phone,
            referred_by_code=ref_code,
        )

        context.user_data["login_state"] = None

        await show_main_menu(update, context, "You’re now logged in 🎉")
        return

    # 2) Create link: waiting for URL
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

    # 3) Create link: waiting for price
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
            f"Original URL:\n{original_url}\n\n"
            f"Price: ₹{price}\n\n"
            f"Share this link to earn:\n`{short_link}`",
            parse_mode="Markdown",
        )

        await show_main_menu(update, context, "Back to Creator Menu:")
        return

    # 4) Bank / UPI: waiting for UPI ID
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
        await show_main_menu(update, context, "Back to Creator Menu:")
        return

    # 5) Bank details: waiting for account number
    if flow_state == "awaiting_bank_acc":
        context.user_data["bank_account"] = msg
        context.user_data["state"] = "awaiting_bank_ifsc"
        await update.message.reply_text(
            "Got it ✅\nNow send your *bank IFSC code* (e.g., `HDFC0001234`).",
            parse_mode="Markdown",
        )
        return

    # 6) Bank details: waiting for IFSC
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

        await update.message.reply_text(
            "✅ Bank details saved.",
        )
        await show_main_menu(update, context, "Back to Creator Menu:")
        return

    # 7) Withdrawal: waiting for amount
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
            "Your balance is reduced now. Admin will send payout manually to your UPI/Bank soon."
        )
        await show_main_menu(update, context, "Back to Creator Menu:")
        return

    # Default
    await update.message.reply_text("Use the buttons below 👇")


# ------------- MENU -------------

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


# ------------- BUTTON HANDLER -------------

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user = query.from_user

    await query.answer()

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
            "💰 *Your Earnings*\n\n"
            f"Available balance: ₹{bal}\n"
            f"Total earned: ₹{total}\n"
            f"From referrals: ₹{ref}\n\n"
            f"Minimum withdrawal: ₹{MIN_WITHDRAW}"
        )

        buttons = [[InlineKeyboardButton("⬅ Back", callback_data="back_menu")]]
        if bal >= MIN_WITHDRAW:
            buttons.insert(0, [InlineKeyboardButton("📤 Withdraw", callback_data="withdraw")])

        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    # LINK STATS
    if data == "stats":
        links = get_links_for_creator(user.id)
        if not links:
            await query.edit_message_text(
                "📊 You have no links yet.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("⬅ Back", callback_data="back_menu")]]
                ),
            )
            return

        lines = ["📊 *Your Recent Links:*", ""]
        for link in links[:5]:  # show last 5
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
                [[InlineKeyboardButton("⬅ Back", callback_data="back_menu")]]
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
            [InlineKeyboardButton("⬅ Back", callback_data="back_menu")],
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
        if not creator:
            await query.edit_message_text(
                "You are not registered as a creator.\nSend /start again."
            )
            return

        rcode = creator["referral_code"]
        text = (
            "👥 *Refer & Earn*\n\n"
            "Share your referral code with friends.\n"
            "If they register as creators using this code, "
            "you get 5% from their earnings (from platform share).\n\n"
            f"Your referral code:\n`{rcode}`"
        )

        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅ Back", callback_data="back_menu")]]
            ),
        )
        return

    # HELP
    if data == "creator_help":
        await query.edit_message_text(
            "❓ *Help*\n\n"
            "For support, message the admin:\n@TeleShortLinkAdminBot",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅ Back", callback_data="back_menu")]]
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
            await query.edit_message_text(
                "You are not registered as a creator."
            )
            return

        bal = wallet["wallet_balance"]
        upi = wallet["upi_id"]
        bank_acc = wallet["bank_account"]
        bank_ifsc = wallet["bank_ifsc"]

        if bal < MIN_WITHDRAW:
            await query.edit_message_text(
                f"You need at least ₹{MIN_WITHDRAW} to withdraw.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("⬅ Back", callback_data="back_menu")]]
                ),
            )
            return

        if not (upi or (bank_acc and bank_ifsc)):
            await query.edit_message_text(
                "You have enough balance, but no payout details saved.\n\n"
                "Please set UPI or bank details first in *Bank / UPI* menu.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("⬅ Back", callback_data="back_menu")]]
                ),
            )
            return

        # choose method if both available
        if upi and bank_acc and bank_ifsc:
            buttons = [
                [InlineKeyboardButton("Withdraw to UPI", callback_data="withdraw_upi")],
                [InlineKeyboardButton("Withdraw to Bank", callback_data="withdraw_bank")],
                [InlineKeyboardButton("⬅ Back", callback_data="back_menu")],
            ]
            await query.edit_message_text(
                f"Your balance: ₹{bal}\n\nChoose withdrawal method:",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
            return

        # single method
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

    # WITHDRAW UPI / BANK (choice)
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
        await show_main_menu(update, context, "Creator Menu")
        return


# ------------- MAIN -------------

def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, save_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.run_polling()


if __name__ == "__main__":
    main()
