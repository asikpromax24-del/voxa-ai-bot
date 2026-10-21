"""Shared helpers: Markdown conversion, safe long-message sending, reply/edit wrapper, auth check."""
import re

from telegram.constants import ParseMode
from telegram.error import BadRequest

from config import ADMIN_ID, CHATTING, MENU

TG_MAX_CHARS = 4000  # Telegram hard limit is 4096; keep a safety margin


def is_admin(user_id: int) -> bool:
    """Only the configured owner ID counts as admin. ADMIN_ID=0 means nobody."""
    return ADMIN_ID != 0 and user_id == ADMIN_ID


def resume_state(context) -> int:
    """Return to the chat if a mode is active, otherwise to the main menu."""
    return CHATTING if context.user_data.get("mode") else MENU


def to_telegram_markdown(text: str) -> str:
    """Convert common LLM Markdown into Telegram's legacy Markdown dialect."""
    text = re.sub(r"^#{1,6}\s*(.+)$", r"*\1*", text, flags=re.MULTILINE)  # headings -> bold
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text, flags=re.DOTALL)        # **bold** -> *bold*
    return text


def split_text(text: str, size: int = TG_MAX_CHARS) -> list[str]:
    """Split long text on line breaks so each chunk fits in one Telegram message."""
    chunks = []
    while len(text) > size:
        cut = text.rfind("\n", 0, size)
        if cut < size // 2:
            cut = size
        chunks.append(text[:cut])
        text = text[cut:]
    if text:
        chunks.append(text)
    return chunks


async def _send_markdown(send, text: str, reply_markup=None) -> None:
    """Send with Markdown. If Telegram rejects the formatting, resend as plain text."""
    try:
        await send(to_telegram_markdown(text), parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    except BadRequest:
        await send(text, reply_markup=reply_markup)


async def send_markdown(message, text: str, reply_markup=None) -> None:
    """Reply to a message with (possibly long) formatted text."""
    chunks = split_text(text)
    for i, chunk in enumerate(chunks):
        markup = reply_markup if i == len(chunks) - 1 else None
        await _send_markdown(message.reply_text, chunk, reply_markup=markup)


async def reply_or_edit(update, text: str, reply_markup=None) -> None:
    """Edit the menu message when a button was pressed, or send a new one for commands."""
    query = update.callback_query
    if query is None:
        await _send_markdown(update.effective_message.reply_text, text, reply_markup=reply_markup)
        return

    await query.answer()
    try:
        await _send_markdown(query.edit_message_text, text, reply_markup=reply_markup)
    except BadRequest as exc:
        # "Message is not modified" is harmless. Other errors (e.g. editing a photo) get a new message.
        if "not modified" not in str(exc).lower():
            await _send_markdown(query.message.reply_text, text, reply_markup=reply_markup)
