"""
Data-access layer for Supabase (PostgreSQL). Every function is async.

The bot uses the SERVICE ROLE key, which bypasses Row Level Security.
Keep that key on the server only and never ship it to a client.
"""
import logging
from datetime import datetime, timedelta, timezone

from supabase import AsyncClient, acreate_client

from config import FREE_DAILY_LIMIT, HISTORY_LIMIT, SUPABASE_SERVICE_KEY, SUPABASE_URL

logger = logging.getLogger(__name__)
_client: AsyncClient | None = None


async def get_db() -> AsyncClient:
    """Create the Supabase async client once, then reuse it for every request."""
    global _client
    if _client is None:
        _client = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _client


# ---------------------------------------------------------------------------
# Time and premium helpers
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str | None) -> datetime | None:
    """Convert a Supabase ISO timestamp (possibly ending in 'Z') to an aware datetime."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def premium_expiry_of(user: dict) -> datetime | None:
    return _parse_ts(user.get("premium_expiry"))


def is_premium_active(user: dict) -> bool:
    """True only if the premium flag is set AND the expiry is still in the future."""
    expiry = premium_expiry_of(user)
    return bool(user.get("is_premium")) and expiry is not None and expiry > _now()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
async def get_user(telegram_id: int) -> dict | None:
    db = await get_db()
    res = await db.table("users").select("*").eq("telegram_id", telegram_id).execute()
    return res.data[0] if res.data else None


async def get_or_create_user(telegram_id: int, username: str | None) -> dict:
    """Return the user row, creating it on first contact and syncing the username."""
    user = await get_user(telegram_id)
    db = await get_db()
    if user is None:
        res = await db.table("users").insert({"telegram_id": telegram_id, "username": username}).execute()
        return res.data[0]
    if user.get("username") != username:
        await db.table("users").update({"username": username}).eq("telegram_id", telegram_id).execute()
        user["username"] = username
    return user


async def consume_quota(telegram_id: int, username: str | None) -> tuple[bool, int]:
    """
    Check and consume one message from the user's daily quota.
    Returns (allowed, remaining). remaining == -1 means unlimited (premium).
    """
    user = await get_or_create_user(telegram_id, username)
    if is_premium_active(user):
        return True, -1

    today = _now().date().isoformat()
    # The counter resets automatically when the stored date is not today.
    count = user["daily_message_count"] if user.get("last_message_date") == today else 0
    if count >= FREE_DAILY_LIMIT:
        return False, 0

    count += 1
    db = await get_db()
    await db.table("users").update(
        {"daily_message_count": count, "last_message_date": today}
    ).eq("telegram_id", telegram_id).execute()
    return True, FREE_DAILY_LIMIT - count


async def activate_premium(telegram_id: int, days: int) -> datetime:
    """Grant premium for `days`. If the user is already premium, extend from the current expiry."""
    user = await get_user(telegram_id) or {}
    base = _now()
    if is_premium_active(user):
        base = premium_expiry_of(user) or base
    new_expiry = base + timedelta(days=days)

    db = await get_db()
    await db.table("users").update(
        {"is_premium": True, "premium_expiry": new_expiry.isoformat()}
    ).eq("telegram_id", telegram_id).execute()
    return new_expiry


# ---------------------------------------------------------------------------
# Chat memory
# ---------------------------------------------------------------------------
async def get_history(telegram_id: int, mode: str, limit: int = HISTORY_LIMIT) -> list[dict]:
    """Return the last `limit` messages for this user and mode, oldest first."""
    db = await get_db()
    res = (
        await db.table("chats")
        .select("role, content")
        .eq("telegram_id", telegram_id)
        .eq("mode", mode)
        .order("timestamp", desc=True)
        .limit(limit)
        .execute()
    )
    return list(reversed(res.data or []))


async def save_message(telegram_id: int, mode: str, role: str, content: str) -> None:
    db = await get_db()
    await db.table("chats").insert(
        {"telegram_id": telegram_id, "mode": mode, "role": role, "content": content}
    ).execute()


async def clear_history(telegram_id: int, mode: str) -> None:
    db = await get_db()
    await db.table("chats").delete().eq("telegram_id", telegram_id).eq("mode", mode).execute()


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
async def create_payment(telegram_id: int, username: str | None, amount: float,
                         trx_id: str, screenshot_file_id: str) -> dict:
    db = await get_db()
    res = await db.table("payments").insert({
        "telegram_id": telegram_id,
        "username": username,
        "amount": amount,
        "trx_id": trx_id,
        "screenshot_url": screenshot_file_id,
        "status": "pending",
    }).execute()
    return res.data[0]


async def get_pending_payments(limit: int = 10) -> list[dict]:
    db = await get_db()
    res = (
        await db.table("payments").select("*")
        .eq("status", "pending").order("created_at").limit(limit).execute()
    )
    return res.data or []


async def claim_payment(payment_id: int, new_status: str) -> dict | None:
    """
    Atomically move a PENDING payment to 'approved' or 'rejected'.
    Returns the updated row, or None if it was already processed (prevents double approval).
    """
    db = await get_db()
    res = await db.table("payments").update(
        {"status": new_status, "reviewed_at": _now().isoformat()}
    ).eq("id", payment_id).eq("status", "pending").execute()
    return res.data[0] if res.data else None
