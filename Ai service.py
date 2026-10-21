"""
Wrappers around every external AI / media service:
  - Groq        : fast chat completions and Whisper speech-to-text
  - Gemini      : image and PDF analysis (vision / documents)
  - edge-tts    : text-to-speech (free Microsoft neural voices)
  - DuckDuckGo  : live web search (sync library, run in a thread)
  - Pollinations: image generation over plain HTTP
All functions are async so the bot never blocks other users.
"""
import asyncio
import logging
import re
import urllib.parse
from functools import lru_cache

import edge_tts
import httpx
from ddgs import DDGS
from google import genai
from google.genai import types
from groq import AsyncGroq

from config import (
    GEMINI_API_KEY, GEMINI_MODEL, GROQ_API_KEY, GROQ_TEXT_MODEL, GROQ_WHISPER_MODEL,
    POLLINATIONS_URL, SYSTEM_PROMPTS, TTS_MAX_CHARS, TTS_VOICE,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_groq() -> AsyncGroq:
    return AsyncGroq(api_key=GROQ_API_KEY)


@lru_cache(maxsize=1)
def get_gemini() -> genai.Client:
    return genai.Client(api_key=GEMINI_API_KEY)


# ---------------------------------------------------------------------------
# Text generation (Groq)
# ---------------------------------------------------------------------------
async def chat_completion(mode: str, history: list[dict], user_text: str) -> str:
    """Send the mode's system prompt, the saved history and the new message to Groq."""
    messages = [{"role": "system", "content": SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["general"])}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": user_text})

    response = await get_groq().chat.completions.create(
        model=GROQ_TEXT_MODEL,
        messages=messages,
        temperature=0.7,
        max_tokens=1500,
    )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Speech-to-text (Groq Whisper)
# ---------------------------------------------------------------------------
async def transcribe_audio(audio: bytes, filename: str = "voice.ogg") -> str:
    """Transcribe a Telegram voice note. Language is auto-detected."""
    result = await get_groq().audio.transcriptions.create(
        file=(filename, audio),
        model=GROQ_WHISPER_MODEL,
        response_format="json",
    )
    return result.text.strip()


# ---------------------------------------------------------------------------
# Image and PDF analysis (Gemini)
# ---------------------------------------------------------------------------
async def analyze_media(data: bytes, mime_type: str, prompt: str) -> str:
    """Send an image or PDF plus the user's prompt to Gemini."""
    response = await get_gemini().aio.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=data, mime_type=mime_type),
            types.Part.from_text(text=prompt),
        ],
    )
    return response.text or "The model returned no analysis."


# ---------------------------------------------------------------------------
# Text-to-speech (edge-tts)
# ---------------------------------------------------------------------------
_MARKDOWN_CHARS = re.compile(r"[*_`#>\[\]()~|]")


async def text_to_speech(text: str, path: str) -> str:
    """Render speech to an MP3 file. Markdown symbols are stripped so they are not read aloud."""
    spoken = _MARKDOWN_CHARS.sub("", text)[:TTS_MAX_CHARS]
    await edge_tts.Communicate(spoken, TTS_VOICE).save(path)
    return path


# ---------------------------------------------------------------------------
# Web search (DuckDuckGo)
# ---------------------------------------------------------------------------
async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Return a list of {title, href, body}. Returns [] on failure instead of raising."""
    def _run() -> list[dict]:
        return DDGS().text(query, max_results=max_results)

    try:
        return await asyncio.to_thread(_run) or []
    except Exception:
        logger.exception("DuckDuckGo search failed")
        return []


def build_research_prompt(query: str, results: list[dict]) -> str:
    """Turn search results into a numbered source list the model can cite."""
    if not results:
        return (f"{query}\n\n(Web search returned no results. Answer from your own knowledge "
                "and say clearly that the answer is not based on live sources.)")
    blocks = [
        f"[{i}] {r.get('title', '')}\nURL: {r.get('href', '')}\n{r.get('body', '')}"
        for i, r in enumerate(results, 1)
    ]
    return (
        "Web search results:\n\n" + "\n\n".join(blocks) +
        f"\n\nUsing these sources, answer the research question below. Cite sources as [n].\n\n{query}"
    )


# ---------------------------------------------------------------------------
# Image generation (Pollinations)
# ---------------------------------------------------------------------------
async def generate_image(prompt: str) -> bytes:
    """Fetch a generated image as raw bytes."""
    url = f"{POLLINATIONS_URL}/{urllib.parse.quote(prompt)}"
    params = {"width": 1024, "height": 1024, "nologo": "true"}
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
        response = await http.get(url, params=params)
        response.raise_for_status()
        return response.content
