"""Inline keyboard layouts (the ChatGPT-style buttons under each message)."""
from telegram import InlineKeyboardButton as Btn
from telegram import InlineKeyboardMarkup


def main_menu(is_admin: bool) -> InlineKeyboardMarkup:
    """Main menu. The Admin Panel button is added only for the owner."""
    rows = [
        [Btn("💬 General Chat", callback_data="mode:general"),
         Btn("🎓 Sir English (Tutor)", callback_data="mode:tutor")],
        [Btn("👨‍💻 Coding Assistant", callback_data="mode:coding"),
         Btn("🔍 Deep Research", callback_data="mode:research")],
        [Btn("🎨 Image Generation", callback_data="mode:image"),
         Btn("👑 Premium", callback_data="premium")],
    ]
    if is_admin:
        rows.append([Btn("🛡️ Admin Panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[Btn("🏠 Main Menu", callback_data="menu")]])


def upgrade_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [Btn("🚀 Upgrade to Premium", callback_data="upgrade")],
        [Btn("🏠 Main Menu", callback_data="menu")],
    ])


def cancel_payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[Btn("✖️ Cancel", callback_data="menu")]])


def admin_review_keyboard(payment_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        Btn("✅ Approve", callback_data=f"admin_approve:{payment_id}"),
        Btn("❌ Reject", callback_data=f"admin_reject:{payment_id}"),
    ]])
