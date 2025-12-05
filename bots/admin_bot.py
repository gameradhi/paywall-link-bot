import logging
import os
import sys

# Make sure Python can import db.py
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from db import (
    init_db,
    get_platform_stats,
    get_pending_withdrawals,
    update_withdrawal_status,
)

# === ADMIN BOT TOKEN ===
BOT_TOKEN = "8270428628:AAGni2YOm2l-P_t2IxEwyaidmiqjyLj9Zz0"

# === OWNER / ADMIN TELEGRAM ID ===
OWNER_ID = 8545081401  # @AntManIndia

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# --------- HELPERS ---------

async def send_not_allowed(update: Update):
    """Block anyone who is not the owner."""
    if update.message:
        await update.message.reply_text("🚫 This bot is only for the platform admin.")
    elif update.callback_query:
        await update.callback_query.answer("Not allowed.", show_alert=True)


async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, title="🛠 Admin Panel"):
    buttons = [
        [InlineKeyboardButton("📊 Platform Stats", callback_data="stats")],
        [InlineKeyboardButton("💸 Pending Withdrawals", callback_data="wd_list")],
        [InlineKeyboardButton("📢 Broadcast (coming soon)", callback_data="broadcast")],
    ]
    kb = InlineKeyboardMarkup(buttons)

    if update.callback_query:
        await update.callback_query.edit_message_text(title, reply_markup=kb)
    else:
        await update.message.reply_text(title, reply_markup=kb)


# --------- COMMANDS ---------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID:
        return await send_not_allowed(update)

    await update.message.reply_text("Hello Boss 👋\nWelcome to the TeleShortLink admin panel.")
    await show_admin_menu(update, context)


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID:
        return await send_not_allowed(update)

    await show_admin_menu(update, context)


# --------- CALLBACKS ---------

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    if user.id != OWNER_ID:
        return await send_not_allowed(update)

    data = query.data
    await query.answer()

    # 📊 Show platform stats
    if data == "stats":
        stats = get_platform_stats()
        pending = get_pending_withdrawals()

        total = stats["total_earnings"] if stats else 0
        ref_paid = stats["total_referral_paid"] if stats else 0
        pending_count = len(pending) if pending else 0

        text = (
            "📊 *Platform Stats*\n\n"
            f"💰 Total platform earnings (after referral share): ₹{total}\n"
            f"🎁 Total paid to referrers: ₹{ref_paid}\n"
            f"🕒 Pending withdrawals: {pending_count}\n"
        )

        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Back to Admin Menu", callback_data="back")]]
            ),
        )
        return

    # 💸 List pending withdrawals (oldest first)
    if data == "wd_list":
        pending = get_pending_withdrawals()
        if not pending:
            await query.edit_message_text(
                "💸 No pending withdrawals right now.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🏠 Back to Admin Menu", callback_data="back")]]
                ),
            )
            return

        w = pending[0]  # show first one
        text_lines = [
            "💸 *Pending Withdrawal*",
            "",
            f"ID: `{w['id']}`",
            f"Creator TG ID: `{w['creator_tg_id']}`",
            f"Amount: ₹{w['amount']}",
            f"Method: {w['method_type']}",
        ]

        if w["method_type"] == "upi":
            text_lines.append(f"UPI: `{w['upi_id']}`")
        else:
            text_lines.append(f"Bank A/C: `{w['bank_account']}`")
            text_lines.append(f"IFSC: `{w['bank_ifsc']}`")

        text_lines.append("")
        text_lines.append("1️⃣ Send payout *manually* using these details.")
        text_lines.append("2️⃣ Then tap *Approve* or *Reject* below.")

        buttons = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"wd_ok:{w['id']}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"wd_no:{w['id']}"),
            ],
            [InlineKeyboardButton("🔄 Refresh List", callback_data="wd_list")],
            [InlineKeyboardButton("🏠 Back to Admin Menu", callback_data="back")],
        ]

        await query.edit_message_text(
            "\n".join(text_lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    # ✅ Approve / ❌ Reject withdrawal
    if data.startswith("wd_ok:") or data.startswith("wd_no:"):
        parts = data.split(":")
        wid = int(parts[1])
        status = "approved" if data.startswith("wd_ok:") else "rejected"

        update_withdrawal_status(wid, status, OWNER_ID)

        await query.edit_message_text(
            f"Withdrawal #{wid} marked as *{status}* ✅",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔄 View Next Pending", callback_data="wd_list")],
                    [InlineKeyboardButton("🏠 Back to Admin Menu", callback_data="back")],
                ]
            ),
        )
        return

    # 📢 Broadcast placeholder
    if data == "broadcast":
        await query.edit_message_text(
            "📢 Broadcast feature will be added later.\n\n"
            "You’ll be able to send a message to all creators or all users.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Back to Admin Menu", callback_data="back")]]
            ),
        )
        return

    # 🏠 Back to main admin menu
    if data == "back":
        await show_admin_menu(update, context)
        return


# --------- MAIN ---------

def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.run_polling()


if __name__ == "__main__":
    main()
