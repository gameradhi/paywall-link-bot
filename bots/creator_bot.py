# bots/creator_bot.py
# Creator Bot: @TeleShortLinkCreatorBot
# Handles: creator dashboard, create paid links, wallet, withdrawals (with payout API)

import logging
import uuid
from typing import Dict, Any, Optional, List

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from db import (
    get_or_create_user,
    set_user_role,
    get_creator_stats,
    get_wallet,
    create_link,
    get_creator_links,
    create_withdrawal,
    get_user_withdrawals,
    set_withdrawal_status,
)

from bots.payouts import send_payout

# ================== CONFIG ==================

BOT_TOKEN = "8280706073:AAED9i2p0TP42pPf9vMXoTt_HYGxqEuyy2w"

BRAND_NAME = "Tele Link"
MAIN_BOT_USERNAME = "TeleShortLinkBot"

PLATFORM_COMMISSION_PERCENT = 10.0  # 10% platform commission
MIN_WITHDRAWAL = 100.0              # minimum withdrawable amount

# Force-join channel
FORCE_CHANNEL_ID = -1003472900442
FORCE_CHANNEL_USERNAME = "TeleLinkUpdate"

# Owner/admin (for payout notifications)
OWNER_TG_ID = 8545081401

logging.basicConfig(
    format="%(asctime)s - CREATOR_BOT - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ================== FORCE JOIN ==================

async def ensure_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Ensures user is a member of the updates channel.
    Returns True if OK, False if we showed join prompt.
    """
    user = update.effective_user
    chat_id = update.effective_chat.id
    bot = context.bot

    try:
        member = await bot.get_chat_member(FORCE_CHANNEL_ID, user.id)
        if member.status in ("member", "administrator", "creator"):
            return True
    except Exception as e:  # noqa: BLE001
        logger.warning("Force join check failed: %s", e)
        # If check fails due to any reason, fail-open (allow usage)
        return True

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📢 Join Tele Link Updates",
                    url=f"https://t.me/{FORCE_CHANNEL_USERNAME}",
                )
            ],
            [InlineKeyboardButton("✅ I Joined", callback_data="joined_channel")],
        ]
    )

    await bot.send_message(
        chat_id=chat_id,
        text=(
            "📢 *Join Tele Link Updates*\n\n"
            "To use the creator panel, you must join our updates channel.\n\n"
            "After joining, tap *I Joined* below."
        ),
        reply_markup=keyboard,
        parse_mode="Markdown",
    )
    return False


# ================== UI HELPERS ==================

def creator_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("💰 Wallet & Withdraw", callback_data="menu_wallet"),
                InlineKeyboardButton("🔗 Create Paid Link", callback_data="menu_create_link"),
            ],
            [
                InlineKeyboardButton("📎 My Links", callback_data="menu_my_links"),
                InlineKeyboardButton("📊 Earnings Report", callback_data="menu_stats"),
            ],
            [
                InlineKeyboardButton("🧾 Withdrawal History", callback_data="menu_withdraw_history"),
            ],
            [
                InlineKeyboardButton(
                    f"⬅ Back to @{MAIN_BOT_USERNAME}",
                    url=f"https://t.me/{MAIN_BOT_USERNAME}",
                ),
            ],
        ]
    )


async def send_creator_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id

    # ensure user exists & set role to creator
    db_user = get_or_create_user(user.id, user.username, role="creator")
    if db_user.get("role") != "creator":
        set_user_role(user.id, "creator")

    stats = get_creator_stats(user.id)
    wallet = get_wallet(user.id)

    text = (
        f"🔥 *{BRAND_NAME} Creator Panel*\n\n"
        f"👤 Creator: @{user.username or 'unknown'}\n\n"
        "📊 *Dashboard*\n"
        f"• Total sales: *{stats['total_sales']}*\n"
        f"• Total revenue (user payments): *₹{stats['total_revenue']:.2f}*\n"
        f"• Total earnings (your share): *₹{stats['total_creator']:.2f}*\n\n"
        "💰 *Wallet*\n"
        f"• Available balance: *₹{wallet['balance']:.2f}*\n"
        f"• Lifetime earned: *₹{wallet['total_earned']:.2f}*\n\n"
        f"_Platform commission ({BRAND_NAME} - {PLATFORM_COMMISSION_PERCENT:.0f}% of each payment) is "
        "automatically deducted from each sale._"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=creator_main_menu_keyboard(),
        parse_mode="Markdown",
    )


# ================== /start ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_force_join(update, context):
        return
    await send_creator_dashboard(update, context)


# ================== WALLET & WITHDRAW ==================

async def show_wallet_screen(chat_id: int, user, context: ContextTypes.DEFAULT_TYPE) -> None:
    wallet = get_wallet(user.id)

    text = (
        "💰 *Wallet & Earnings*\n\n"
        f"• Available balance: *₹{wallet['balance']:.2f}*\n"
        f"• Lifetime earned: *₹{wallet['total_earned']:.2f}*\n\n"
        f"You can withdraw once your balance is at least *₹{MIN_WITHDRAWAL:.0f}*."
    )

    buttons = [
        [
            InlineKeyboardButton("💸 Withdraw Earnings", callback_data="wallet_withdraw"),
            InlineKeyboardButton("📊 Earnings Report", callback_data="menu_stats"),
        ],
        [
            InlineKeyboardButton("⬅ Creator Dashboard", callback_data="back_dashboard"),
        ],
    ]

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def start_withdraw_flow(chat_id: int, user, context: ContextTypes.DEFAULT_TYPE) -> None:
    wallet = get_wallet(user.id)

    if wallet["balance"] < MIN_WITHDRAWAL:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"⚠ Your balance is *₹{wallet['balance']:.2f}*.\n"
                f"Minimum withdrawal amount is *₹{MIN_WITHDRAWAL:.0f}*."
            ),
            parse_mode="Markdown",
        )
        return

    text = (
        "💸 *Withdraw Earnings*\n\n"
        "Choose how you want to receive your money:"
    )
    buttons = [
        [
            InlineKeyboardButton("📲 UPI", callback_data="withdraw_method_upi"),
            InlineKeyboardButton("🏦 Bank Account", callback_data="withdraw_method_bank"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_withdraw")],
    ]
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


# ================== CREATE LINK FLOW ==================

async def start_create_link_flow(chat_id: int, user, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["create_link"] = {}
    context.user_data["state"] = "await_link_url"

    text = (
        "🔗 *Create Paid Link*\n\n"
        "Send the original URL you want to lock.\n\n"
        "Example: `https://your-website.com/secret-content`"
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_create_link")]]
        ),
    )


# ================== MY LINKS & STATS & HISTORY ==================

async def show_my_links(chat_id: int, user, context: ContextTypes.DEFAULT_TYPE) -> None:
    links = get_creator_links(user.id)
    if not links:
        await context.bot.send_message(
            chat_id=chat_id,
            text="📎 You have not created any paid links yet.",
        )
        return

    lines: List[str] = ["📎 *Your Paid Links:*", ""]
    for l in links[:20]:
        code = l["short_code"]
        price = l["price"]
        lines.append(
            f"• `/start {code}` – ₹{price:.2f}"
        )
    lines.append("\nShare these `/start <code>` commands with your users in the main bot.")
    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


async def show_stats_screen(chat_id: int, user, context: ContextTypes.DEFAULT_TYPE) -> None:
    stats = get_creator_stats(user.id)

    text = (
        "📊 *Earnings Report*\n\n"
        f"• Total sales: *{stats['total_sales']}*\n"
        f"• Total revenue (user payments): *₹{stats['total_revenue']:.2f}*\n"
        f"• Your share (after {PLATFORM_COMMISSION_PERCENT:.0f}% platform commission): "
        f"*₹{stats['total_creator']:.2f}*\n\n"
        f"{BRAND_NAME} commission helps run payouts, hosting and platform maintenance."
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
    )


async def show_withdraw_history(chat_id: int, user, context: ContextTypes.DEFAULT_TYPE) -> None:
    withdrawals = get_user_withdrawals(user.id)
    if not withdrawals:
        await context.bot.send_message(
            chat_id=chat_id,
            text="🧾 You have no withdrawal history yet.",
        )
        return

    lines: List[str] = ["🧾 *Withdrawal History*:", ""]
    for w in withdrawals[:20]:
        wid = w["id"]
        amt = w["amount"]
        status = w["status"]
        method = w["method"]
        created_at = w["created_at"]
        lines.append(
            f"• #{wid} – ₹{amt:.2f} – {method.upper()} – *{status}* – {created_at}"
        )

    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode="Markdown",
    )


# ================== CALLBACK HANDLER ==================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    chat_id = query.message.chat.id

    if data == "joined_channel":
        # after join, show dashboard
        await send_creator_dashboard(update, context)
        return

    if data == "menu_wallet":
        await show_wallet_screen(chat_id, user, context)
        return

    if data == "menu_create_link":
        await start_create_link_flow(chat_id, user, context)
        return

    if data == "menu_my_links":
        await show_my_links(chat_id, user, context)
        return

    if data == "menu_stats":
        await show_stats_screen(chat_id, user, context)
        return

    if data == "menu_withdraw_history":
        await show_withdraw_history(chat_id, user, context)
        return

    if data == "wallet_withdraw":
        await start_withdraw_flow(chat_id, user, context)
        return

    if data == "withdraw_method_upi":
        context.user_data["withdraw"] = {"method": "upi"}
        context.user_data["state"] = "await_withdraw_upi"
        await context.bot.send_message(
            chat_id=chat_id,
            text="💸 *Withdrawal – UPI*\n\nSend your UPI ID (example: `name@upi`).",
            parse_mode="Markdown",
        )
        return

    if data == "withdraw_method_bank":
        context.user_data["withdraw"] = {"method": "bank"}
        context.user_data["state"] = "await_withdraw_bank"
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "💸 *Withdrawal – Bank Account*\n\n"
                "Send your bank details in this format:\n"
                "`IFSC|ACCOUNTNUMBER`\n\n"
                "Example:\n"
                "`HDFC0001234|12345678901234`"
            ),
            parse_mode="Markdown",
        )
        return

    if data == "cancel_withdraw":
        context.user_data.pop("withdraw", None)
        context.user_data.pop("state", None)
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Withdrawal cancelled.",
        )
        await show_wallet_screen(chat_id, user, context)
        return

    if data == "cancel_create_link":
        context.user_data.pop("create_link", None)
        context.user_data.pop("state", None)
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Link creation cancelled.",
        )
        await send_creator_dashboard(update, context)
        return

    if data == "back_dashboard":
        await send_creator_dashboard(update, context)
        return


# ================== MESSAGE HANDLER (TEXT FLOWS) ==================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    state = context.user_data.get("state")

    # -------- Create Link: URL --------
    if state == "await_link_url":
        context.user_data["create_link"]["url"] = text
        context.user_data["state"] = "await_link_price"
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "💰 Great! Now send the price in rupees.\n\n"
                "Example: `49` (for ₹49)"
            ),
            parse_mode="Markdown",
        )
        return

    # -------- Create Link: Price --------
    if state == "await_link_price":
        try:
            price = float(text)
            if price <= 0:
                raise ValueError
        except ValueError:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠ Please send a valid positive number for price. Example: `49`",
                parse_mode="Markdown",
            )
            return

        url = context.user_data["create_link"]["url"]
        short_code = f"pl_{uuid.uuid4().hex[:8]}"

        create_link(short_code, user.id, url, price)

        context.user_data.pop("create_link", None)
        context.user_data.pop("state", None)

        text_resp = (
            "✅ *Paid Link Created!*\n\n"
            f"Original URL:\n`{url}`\n\n"
            f"Price: *₹{price:.2f}*\n\n"
            "Share this command with users to unlock via the main bot:\n"
            f"`/start {short_code}`\n\n"
            f"_Make sure users open this in @{MAIN_BOT_USERNAME}_"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=text_resp,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        return

    # -------- Withdrawal: UPI --------
    if state == "await_withdraw_upi":
        upi = text
        wd = context.user_data.get("withdraw") or {}
        wd["account"] = upi
        context.user_data["withdraw"] = wd
        context.user_data["state"] = "await_withdraw_amount"

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "✅ UPI ID saved.\n\n"
                "Now send the amount you want to withdraw (in rupees)."
            ),
        )
        return

    # -------- Withdrawal: Bank --------
    if state == "await_withdraw_bank":
        bank = text
        if "|" not in bank:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "⚠ Invalid format. Please send in `IFSC|ACCOUNTNUMBER` format.\n"
                    "Example: `HDFC0001234|12345678901234`"
                ),
                parse_mode="Markdown",
            )
            return
        wd = context.user_data.get("withdraw") or {}
        wd["account"] = bank
        context.user_data["withdraw"] = wd
        context.user_data["state"] = "await_withdraw_amount"

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "✅ Bank details saved.\n\n"
                "Now send the amount you want to withdraw (in rupees)."
            ),
        )
        return

    # -------- Withdrawal: Amount --------
    if state == "await_withdraw_amount":
        # 1) Parse amount
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError
        except ValueError:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠ Please send a valid positive amount (for example: 150 or 150.50).",
            )
            return

        # 2) Read data stored from previous steps
        wd = context.user_data.get("withdraw") or {}
        method = wd.get("method")
        account = wd.get("account")

        if not method or not account:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "❌ Something went wrong while reading your withdrawal details.\n"
                    "Please start again from *Withdraw* in the main menu."
                ),
                parse_mode="Markdown",
            )
            context.user_data.pop("withdraw", None)
            context.user_data.pop("state", None)
            return

        # 3) Create withdrawal in DB (also deducts from wallet)
        ok, msg = create_withdrawal(user.id, amount, method, account)
        await context.bot.send_message(chat_id=chat_id, text=msg)

        if not ok:
            context.user_data.pop("withdraw", None)
            context.user_data.pop("state", None)
            return

        # 4) Find the pending withdrawal we just created
        withdrawals = get_user_withdrawals(user.id)
        pending_id: Optional[int] = None
        if withdrawals:
            for w in withdrawals:
                if w["status"] == "pending" and abs(w["amount"] - amount) < 0.001:
                    pending_id = w["id"]
                    break
            if pending_id is None:
                pending_id = withdrawals[-1]["id"]

        # 5) Try payout via Cashfree (using payouts.py)
        success, ref, payout_msg = False, "", ""
        if pending_id is not None:
            success, ref, payout_msg = send_payout(
                amount=amount,
                method=method,
                account=account,
                name=user.username or "Tele Link",
                withdrawal_id=pending_id,
            )

            if success:
                set_withdrawal_status(pending_id, "paid", external_ref=ref)
            else:
                set_withdrawal_status(pending_id, "failed", external_ref=ref)

             # 6) Build final message for creator
        final_text = "💸 *Withdrawal Created*\n\n" + msg
        if pending_id is not None:
            final_text += f"\n\nPayout: {'✅ SUCCESS' if success else '❌ FAILED'}"
            if payout_msg:
                final_text += f"\nMessage: {payout_msg}"
            if ref:
                final_text += f"\nReference: `{ref}`"

        await context.bot.send_message(
            chat_id=chat_id,
            text=final_text,
            parse_mode="Markdown",
        )

        # 7) Notify admin (you)
        try:
            if pending_id is not None:
                await context.bot.send_message(
                    chat_id=OWNER_TG_ID,
                    text=(
                        "🧾 *Payout Event*\n\n"
                        f"Creator: @{user.username or 'unknown'} (ID: {user.id})\n"
                        f"Withdrawal ID: #{pending_id}\n"
                        f"Amount: ₹{amount:.2f}\n"
                        f"Method: {method.upper()} – {account}\n"
                        f"Status: {'SUCCESS' if success else 'FAILED'}\n"
                        f"Reference: {ref or '-'}"
                    ),
                    parse_mode="Markdown",
                )
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to notify owner about payout: %s", e)

        # 8) Clear state
        context.user_data.pop("withdraw", None)
        context.user_data.pop("state", None)
        return

    # -------- Default: Show dashboard again --------
    await send_creator_dashboard(update, context)


# ================== MAIN ==================

def main() -> None:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    logger.info("Creator bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()
    
