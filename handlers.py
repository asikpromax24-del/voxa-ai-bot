"""
User-facing handlers: main menu, mode selection, AI chat, voice notes,
photos and PDFs, and image generation.
"""
import logging
import os
import tempfile
import uuid

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

import database as db
from ai_services import (
    analyze_media, build_research_prompt, chat_completion, generate_image,
    text_to_speech, transcribe_audio, web_search,
)
from config import CHATTING, FREE_DAILY_LIMIT, MENU, PREMIUM_CURRENCY, PREMIUM_DAYS, PREMIUM_PRICE
from keyboards import back_to_menu, main_menu, upgrade_keyboard
from utils import is_admin, reply_or_edit, resume_state, send_markdown

logger = logging.getLogger(__name__)

MAX_MEDIA_BYTES = 20 * 1024 * 1024  # 20 MB limit for files sent to Gemini

WELCOME_TEXT = (
    "👋 *Welcome to ASIKERA*\n\n"
    "Your AI assistant for chat, voice, images, PDFs, live web research and image generation.\n\n"
    "Choose a mode to begin 👇"
)

# mode key -> (button title, short description shown when the mode activates)
MODE_INFO = {
    "general": ("💬 General Chat", "Ask me anything. I remember your last 10 messages in this mode."),
    "tutor": ("🎓 Sir English", "Practice English. Write or send a voice note and I'll correct and teach you."),
    "coding": ("👨‍💻 Coding Assistant", "Send code or a question. I'll write, debug and explain."),
    "research": ("🔍 Deep Research", "Ask a topic. I'll search the live web and summarize it with sources."),
    "image": ("🎨 Image Generation", "Describe the image you want and I'll create it."),
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _footer(remaining: int) -> str:
    """Show the remaining free messages for the day (premium users see nothing)."""
    return "" if remaining < 0 else f"\n\n_Free messages left today: {remaining}_"


async def _gate(update: Update) -> tuple[bool, int]:
    """Enforce the daily free quota. Sends the upgrade prompt when the limit is reached."""
    user = update.effective_user
    allowed, remaining = await db.consume_quota(user.id, user.username)
    if not allowed:
        await update.effective_message.reply_text(
            f"🚫 You've used your {FREE_DAILY_LIMIT} free messages for today.\n"
            "Upgrade to Premium for unlimited access.",
            reply_markup=upgrade_keyboard(),
        )
    return allowed, remaining


async def _ai_reply(user_id: int, mode: str, text: str) -> str:
    """Build context (history, optional web search), call Groq and store both sides of the turn."""
    history = await db.get_history(user_id, mode)
    prompt = text
    if mode == "research":
        prompt = build_research_prompt(text, await web_search(text))

    answer = await chat_completion(mode, history, prompt)
    await db.save_message(user_id, mode, "user", text)
    await db.save_message(user_id, mode, "assistant", answer)
    return answer


async def _send_image(update: Update, prompt: str, remaining: int) -> None:
    """Generate an image with Pollinations and send it back as a photo."""
    await update.effective_chat.send_action(ChatAction.UPLOAD_PHOTO)
    try:
        image = await generate_image(prompt)
    except Exception:
        logger.exception("Image generation failed")
        await update.effective_message.reply_text("❌ Image generation failed. Please try again.")
        return
    await update.effective_message.reply_photo(photo=image, caption=f"🎨 {prompt[:180]}")


async def _send_voice_reply(update: Update, text: str) -> None:
    """Convert the answer to an MP3 with edge-tts and send it as a voice note."""
    path = os.path.join(tempfile.gettempdir(), f"asikera_{uuid.uuid4().hex}.mp3")
    try:
        await update.effective_chat.send_action(ChatAction.RECORD_VOICE)
        await text_to_speech(text, path)
        with open(path, "rb") as audio:
            await update.effective_message.reply_voice(voice=audio)
    except Exception:
        logger.exception("Text-to-speech failed")
    finally:
        if os.path.exists(path):
            os.remove(path)


# ---------------------------------------------------------------------------
# Menu navigation
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/start: register the user and show the main menu."""
    user = update.effective_user
    await db.get_or_create_user(user.id, user.username)
    await update.effective_message.reply_text(
        WELCOME_TEXT, parse_mode="Markdown", reply_markup=main_menu(is_admin(user.id))
    )
    return MENU


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show the main menu (from a button or /menu). The user must pick a mode."""
    await reply_or_edit(update, WELCOME_TEXT, main_menu(is_admin(update.effective_user.id)))
    return MENU


async def select_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Activate a mode. The bot stays in it until the user changes mode or opens the menu."""
    query = update.callback_query
    mode = query.data.split(":", 1)[1]
    if mode not in MODE_INFO:
        await query.answer("Unknown mode")
        return resume_state(context)

    context.user_data["mode"] = mode
    title, description = MODE_INFO[mode]
    await reply_or_edit(
        update,
        f"*{title}* activated ✅\n\n{description}\n\n"
        "Use /new to clear this mode's memory, or /menu to switch modes.",
        back_to_menu(),
    )
    return CHATTING


async def show_premium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Premium info screen with the user's current plan status."""
    user = update.effective_user
    row = await db.get_or_create_user(user.id, user.username)
    if db.is_premium_active(row):
        status = f"✅ Premium is active until *{db.premium_expiry_of(row):%d %b %Y}*."
    else:
        status = f"🆓 You're on the *Free* plan ({FREE_DAILY_LIMIT} messages per day)."

    text = (
        "👑 *ASIKERA Premium*\n\n"
        "♾️ Unlimited messages\n"
        "🎨 Unlimited image generation\n"
        "⚡ Priority responses\n\n"
        f"💰 Price: *{PREMIUM_PRICE:g} {PREMIUM_CURRENCY}* for {PREMIUM_DAYS} days\n\n"
        f"{status}"
    )
    await reply_or_edit(update, text, upgrade_keyboard())
    return resume_state(context)


async def menu_hint(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Typed text while no mode is active: nudge the user to choose one."""
    await update.effective_message.reply_text(
        "👇 Please choose a mode first.",
        reply_markup=main_menu(is_admin(update.effective_user.id)),
    )
    return MENU


async def new_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/new: wipe the memory of the current mode."""
    mode = context.user_data.get("mode", "general")
    await db.clear_history(update.effective_user.id, mode)
    await update.effective_message.reply_text("🧹 Memory cleared. Fresh start!")
    return CHATTING


# ---------------------------------------------------------------------------
# Chat: text, voice, media, images
# ---------------------------------------------------------------------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Plain text in an active mode: AI reply, or image generation in Image mode."""
    mode = context.user_data.get("mode", "general")
    allowed, remaining = await _gate(update)
    if not allowed:
        return CHATTING

    text = update.effective_message.text
    if mode == "image":
        await _send_image(update, text, remaining)
        return CHATTING

    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        answer = await _ai_reply(update.effective_user.id, mode, text)
    except Exception:
        logger.exception("AI reply failed")
        await update.effective_message.reply_text("⚠️ Something went wrong. Please try again in a moment.")
        return CHATTING

    await send_markdown(update.effective_message, answer + _footer(remaining))
    return CHATTING


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Voice note: transcribe (Whisper via Groq), answer, then reply with text and a voice note."""
    mode = context.user_data.get("mode", "general")
    allowed, remaining = await _gate(update)
    if not allowed:
        return CHATTING

    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        voice_file = await update.effective_message.voice.get_file()
        audio = bytes(await voice_file.download_as_bytearray())
        transcript = await transcribe_audio(audio)
    except Exception:
        logger.exception("Transcription failed")
        await update.effective_message.reply_text("⚠️ I couldn't process that voice message. Please try again.")
        return CHATTING

    if not transcript:
        await update.effective_message.reply_text("🔇 I couldn't hear anything. Please try again.")
        return CHATTING

    await update.effective_message.reply_text(f"🗣️ You said: {transcript}")

    if mode == "image":
        await _send_image(update, transcript, remaining)
        return CHATTING

    try:
        answer = await _ai_reply(update.effective_user.id, mode, transcript)
    except Exception:
        logger.exception("AI reply failed")
        await update.effective_message.reply_text("⚠️ Something went wrong. Please try again in a moment.")
        return CHATTING

    await send_markdown(update.effective_message, answer + _footer(remaining))
    await _send_voice_reply(update, answer)
    return CHATTING


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Photos and PDFs: send to Gemini together with the caption (or a default prompt)."""
    mode = context.user_data.get("mode", "general")
    allowed, remaining = await _gate(update)
    if not allowed:
        return CHATTING

    msg = update.effective_message
    if msg.photo:
        tg_file = msg.photo[-1]  # largest available resolution
        mime_type, label = "image/jpeg", "[Image]"
    else:
        tg_file = msg.document
        mime_type, label = "application/pdf", "[PDF]"
        if tg_file.file_size and tg_file.file_size > MAX_MEDIA_BYTES:
            await msg.reply_text("⚠️ That file is too large (maximum 20 MB).")
            return CHATTING

    prompt = msg.caption or "Analyze this file and summarize the key points."
    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        file_obj = await tg_file.get_file()
        data = bytes(await file_obj.download_as_bytearray())
        analysis = await analyze_media(data, mime_type, prompt)
    except Exception:
        logger.exception("Media analysis failed")
        await msg.reply_text("⚠️ I couldn't analyze that file. Please try again.")
        return CHATTING

    user_id = update.effective_user.id
    await db.save_message(user_id, mode, "user", f"{label} {prompt}")
    await db.save_message(user_id, mode, "assistant", analysis)
    await send_markdown(msg, analysis + _footer(remaining))
    return CHATTING
