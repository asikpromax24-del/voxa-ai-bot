"""
Entry point. Builds the Telegram application, wires every handler together
and starts long polling.

Run:  python main.py
"""
import logging
import sys

from telegram import BotCommand, Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, PicklePersistence, filters,
)

from admin import admin_approve, admin_command, admin_panel_callback, admin_reject
from config import (
    ADMIN_ID, AWAIT_SCREENSHOT, AWAIT_TRX, BOT_TOKEN, CHATTING, MENU, MISSING_VARS,
)
from handlers import (
    handle_media, handle_text, handle_voice, menu_hint, new_chat,
    select_mode, show_menu, show_premium, start,
)
from payments import receive_screenshot, receive_trx, screenshot_hint, upgrade_start

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("asikera")


def _navigation() -> list:
    """Buttons that work in every conversation state (so users can always switch modes)."""
    return [
        CallbackQueryHandler(select_mode, pattern=r"^mode:"),
        CallbackQueryHandler(show_menu, pattern=r"^menu$"),
        CallbackQueryHandler(show_premium, pattern=r"^premium$"),
        CallbackQueryHandler(upgrade_start, pattern=r"^upgrade$"),
        CommandHandler("menu", show_menu),
    ]


def build_conversation() -> ConversationHandler:
    """
    The state machine that keeps the user inside their chosen mode:
      MENU             -> waiting for a mode button
      CHATTING         -> every message goes to the active mode
      AWAIT_SCREENSHOT -> premium flow, waiting for the payment screenshot
      AWAIT_TRX        -> premium flow, waiting for the Transaction ID
    """
    return ConversationHandler(
        entry_points=[CommandHandler("start", start), *_navigation()],
        states={
            MENU: [
                *_navigation(),
                MessageHandler(filters.TEXT & ~filters.COMMAND, menu_hint),
            ],
            CHATTING: [
                *_navigation(),
                CommandHandler("new", new_chat),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
                MessageHandler(filters.VOICE, handle_voice),
                MessageHandler(filters.PHOTO | filters.Document.PDF, handle_media),
            ],
            AWAIT_SCREENSHOT: [
                *_navigation(),
                MessageHandler(filters.PHOTO, receive_screenshot),
                MessageHandler(filters.TEXT & ~filters.COMMAND, screenshot_hint),
            ],
            AWAIT_TRX: [
                *_navigation(),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_trx),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("cancel", show_menu),
        ],
        name="asikera_conversation",
        persistent=True,          # Remember the mode and payment step across bot restarts
        allow_reentry=True,
    )


async def _post_init(application: Application) -> None:
    """Register the command list shown in Telegram's '/' menu."""
    await application.bot.set_my_commands([
        BotCommand("start", "Open the main menu"),
        BotCommand("menu", "Switch mode"),
        BotCommand("new", "Clear memory in this mode"),
        BotCommand("cancel", "Cancel the current action"),
    ])


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log any unhandled exception so one bad update never crashes the bot."""
    logger.error("Unhandled exception while processing an update", exc_info=context.error)


def main() -> None:
    if MISSING_VARS:
        logger.error("Missing required environment variables: %s", ", ".join(MISSING_VARS))
        sys.exit(1)
    if ADMIN_ID == 0:
        logger.warning("ADMIN_ID is not set. The admin panel will be disabled.")

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .persistence(PicklePersistence(filepath="asikera_state.pkl"))
        .post_init(_post_init)
        .build()
    )

    application.add_handler(build_conversation())

    # Global admin handlers. They sit outside the conversation, so they work in any state.
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=r"^admin_panel$"))
    application.add_handler(CallbackQueryHandler(admin_approve, pattern=r"^admin_approve:\d+$"))
    application.add_handler(CallbackQueryHandler(admin_reject, pattern=r"^admin_reject:\d+$"))

    application.add_error_handler(_on_error)

    logger.info("ASIKERA is running. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
