"""
Owner-only admin panel.
  /admin or the 🛡️ Admin Panel button  -> lists pending payments with screenshots.
  ✅ Approve  -> marks approved and grants premium (extends from current expiry if already premium).
  ❌ Reject   -> marks rejected and tells the user.
Every handler re-checks the admin ID, so the panel stays locked even if buttons are forwarded.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

import database as db
from config import PREMIUM_DAYS
from keyboards import admin_review_keyboard
from utils import is_admin

logger = logging.getLogger(__name__)


async def send_payment_card(bot, chat_id: int, payment: dict) -> None:
    """Send one payment: screenshot (if any), details, and Approve/Reject buttons."""
    caption = (
        f"🧾 Payment #{payment['id']}\n"
        f"User: @{payment.get('username') or 'N/A'} (ID: {payment['telegram_id']})\n"
        f"Amount: {payment['amount']}\n"
        f"TrxID: {payment['trx_id']}"
    )
    keyboard = admin_review_keyboard(payment["id"])
    if payment.get("screenshot_url"):
        await bot.send_photo(chat_id, photo=payment["screenshot_url"], caption=caption, reply_markup=keyboard)
    else:
        await bot.send_message(chat_id, caption, reply_markup=keyboard)


async def _send_pending(bot, chat_id: int) -> None:
    pending = await db.get_pending_payments()
    if not pending:
        await bot.send_message(chat_id, "🛡️ Admin Panel\n\n✅ No pending payments.")
        return
    await bot.send_message(chat_id, f"🛡️ Admin Panel\n\n⏳ {len(pending)} pending payment(s):")
    for payment in pending:
        await send_payment_card(bot, chat_id, payment)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/admin: silently ignored for everyone except the owner."""
    if not is_admin(update.effective_user.id):
        return
    await _send_pending(context.bot, update.effective_chat.id)


async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The 🛡️ Admin Panel button in the main menu."""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Not authorized.", show_alert=True)
        return
    await query.answer()
    await _send_pending(context.bot, query.message.chat_id)


async def admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _review(update, context, approve=True)


async def admin_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _review(update, context, approve=False)


async def _review(update: Update, context: ContextTypes.DEFAULT_TYPE, approve: bool) -> None:
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Not authorized.", show_alert=True)
        return

    payment_id = int(query.data.split(":", 1)[1])
    # Atomic claim: only a still-pending payment can be processed, so double taps are harmless.
    payment = await db.claim_payment(payment_id, "approved" if approve else "rejected")
    if payment is None:
        await query.answer("This payment was already processed.", show_alert=True)
        return
    await query.answer("Done ✅" if approve else "Rejected ❌")

    if approve:
        expiry = await db.activate_premium(payment["telegram_id"], PREMIUM_DAYS)
        status_line = f"✅ APPROVED. Premium until {expiry:%d %b %Y}."
        user_message = (
            f"🎉 Your payment was approved! Premium is active until {expiry:%d %b %Y}. Enjoy ASIKERA!"
        )
    else:
        status_line = "❌ REJECTED."
        user_message = (
            "❌ We couldn't verify your payment. Please check your TrxID and screenshot, "
            "then try again from 👑 Premium."
        )

    # Remove the buttons so the payment can't be reviewed twice, then confirm in the admin chat.
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(f"Payment #{payment_id}: {status_line}")

    try:
        await context.bot.send_message(payment["telegram_id"], user_message)
    except Exception:
        logger.warning("Could not notify user %s about payment %s", payment["telegram_id"], payment_id)
