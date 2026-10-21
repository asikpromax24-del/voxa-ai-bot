"""
Premium upgrade flow, run as part of the main ConversationHandler:
  payment details -> screenshot -> Transaction ID -> saved as 'pending' -> admin notified.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

import database as db
from admin import send_payment_card
from config import (
    ADMIN_ID, AWAIT_SCREENSHOT, AWAIT_TRX, BINANCE_ID, BKASH_NUMBER,
    PREMIUM_CURRENCY, PREMIUM_DAYS, PREMIUM_PRICE,
)
from keyboards import cancel_payment_keyboard
from utils import reply_or_edit, resume_state

logger = logging.getLogger(__name__)


async def upgrade_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show the payment accounts and ask for a screenshot."""
    text = (
        "💳 *Upgrade to Premium*\n\n"
        f"Plan: *{PREMIUM_DAYS} days, unlimited*\n"
        f"Amount: *{PREMIUM_PRICE:g} {PREMIUM_CURRENCY}*\n\n"
        f"📱 *bKash (Send Money):* `{BKASH_NUMBER}`\n"
        f"🟡 *Binance Pay ID:* `{BINANCE_ID}`\n\n"
        "*Steps*\n"
        "1️⃣ Pay the amount to one of the accounts above.\n"
        "2️⃣ Send a *screenshot* of the payment here.\n"
        "3️⃣ Send your *Transaction ID (TrxID)*."
    )
    await reply_or_edit(update, text, cancel_payment_keyboard())
    return AWAIT_SCREENSHOT


async def screenshot_hint(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Text sent where a screenshot is expected."""
    await update.effective_message.reply_text(
        "📸 Please send a screenshot (photo) of your payment.",
        reply_markup=cancel_payment_keyboard(),
    )
    return AWAIT_SCREENSHOT


async def receive_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the screenshot's Telegram file_id until the TrxID arrives."""
    context.user_data["pay_screenshot"] = update.effective_message.photo[-1].file_id
    await update.effective_message.reply_text(
        "✅ Screenshot received. Now send your Transaction ID (TrxID).",
        reply_markup=cancel_payment_keyboard(),
    )
    return AWAIT_TRX


async def receive_trx(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save the payment as 'pending' and forward it to the admin for review."""
    trx_id = (update.effective_message.text or "").strip()
    file_id = context.user_data.get("pay_screenshot")

    if not file_id:
        await update.effective_message.reply_text("Please send the screenshot first.")
        return AWAIT_SCREENSHOT
    if not 4 <= len(trx_id) <= 64:
        await update.effective_message.reply_text("That doesn't look like a valid Transaction ID. Please try again.")
        return AWAIT_TRX

    user = update.effective_user
    payment = await db.create_payment(user.id, user.username, PREMIUM_PRICE, trx_id, file_id)
    context.user_data.pop("pay_screenshot", None)

    try:
        await send_payment_card(context.bot, ADMIN_ID, payment)
    except Exception:
        # Usually means the admin has never started the bot. The payment is still saved.
        logger.exception("Could not notify admin about payment %s", payment["id"])

    await update.effective_message.reply_text(
        "⏳ Payment submitted! The admin will verify it shortly. You'll be notified here once it's approved."
    )
    return resume_state(context)
