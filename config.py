"""
Central configuration. Every secret and tunable value is read from environment
variables (loaded from a local .env file by python-dotenv).
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    """Read a string environment variable, stripping stray whitespace."""
    return os.getenv(name, default).strip()


def _int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back to `default`."""
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


# ---- Secrets and IDs -----------------------------------------------------
BOT_TOKEN = _env("BOT_TOKEN")
ADMIN_ID = _int("ADMIN_ID", 0)               # Owner's numeric Telegram user ID
SUPABASE_URL = _env("SUPABASE_URL")
SUPABASE_SERVICE_KEY = _env("SUPABASE_SERVICE_KEY")
GROQ_API_KEY = _env("GROQ_API_KEY")
GEMINI_API_KEY = _env("GEMINI_API_KEY")

# ---- AI models -----------------------------------------------------------
GROQ_TEXT_MODEL = _env("GROQ_TEXT_MODEL", "llama-3.3-70b-versatile")
GROQ_WHISPER_MODEL = _env("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-2.5-flash")
TTS_VOICE = _env("TTS_VOICE", "en-US-AriaNeural")
TTS_MAX_CHARS = 1500                         # Keep voice replies short and fast
POLLINATIONS_URL = "https://image.pollinations.ai/prompt"

# ---- Limits and business rules -------------------------------------------
FREE_DAILY_LIMIT = _int("FREE_DAILY_LIMIT", 10)
HISTORY_LIMIT = 10                           # Messages of memory sent to the AI
PREMIUM_PRICE = float(_env("PREMIUM_PRICE", "300"))
PREMIUM_CURRENCY = _env("PREMIUM_CURRENCY", "BDT")
PREMIUM_DAYS = _int("PREMIUM_DAYS", 30)
BKASH_NUMBER = _env("BKASH_NUMBER", "not-set")
BINANCE_ID = _env("BINANCE_ID", "not-set")

# ---- ConversationHandler states ------------------------------------------
MENU, CHATTING, AWAIT_SCREENSHOT, AWAIT_TRX = range(4)

# ---- Persona per mode ----------------------------------------------------
SYSTEM_PROMPTS = {
    "general": (
        "You are ASIKERA, a helpful, friendly and accurate AI assistant. "
        "Answer clearly and concisely. Use Markdown (bold, bullet points, code blocks) when it helps."
    ),
    "tutor": (
        "You are Sir English, a patient and encouraging English tutor. Correct the user's mistakes "
        "gently, show the corrected sentence, briefly explain the grammar rule, and end with one "
        "short practice exercise."
    ),
    "coding": (
        "You are an expert software engineer. Give correct, production-quality code in fenced code "
        "blocks with the language tag. Explain briefly and point out edge cases and bugs."
    ),
    "research": (
        "You are a careful research analyst. Use the numbered web search results supplied in the "
        "message, synthesize them into a clear answer, and cite sources as [n]. If the results are "
        "insufficient or contradictory, say so."
    ),
}

# ---- Startup validation --------------------------------------------------
REQUIRED_VARS = {
    "BOT_TOKEN": BOT_TOKEN,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_SERVICE_KEY": SUPABASE_SERVICE_KEY,
    "GROQ_API_KEY": GROQ_API_KEY,
    "GEMINI_API_KEY": GEMINI_API_KEY,
}
MISSING_VARS = [name for name, value in REQUIRED_VARS.items() if not value]
