"""Spotify data cache — serves playlist/track data from SQLite to avoid hitting Spotify API rate limits."""

import json
import logging
from datetime import datetime, timedelta

from database import get_db, get_setting
from spotify_auth import is_rate_limited

log = logging.getLogger("jukeboxx.spotify_cache")


async def cache_get(key: str, force_refresh: bool = False) -> dict | list | None:
    """Return cached JSON if within TTL, or stale data when rate-limited.
    Returns None on cache miss or when force_refresh is requested (and not rate-limited)."""
    if force_refresh and not is_rate_limited():
        return None

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT data, fetched_at FROM spotify_cache WHERE cache_key = ?", (key,)
        )
        row = await cur.fetchone()
        if not row:
            return None

        # Always serve stale cache during rate limits
        if is_rate_limited():
            log.info(f"Cache hit (rate-limited, serving stale): {key}")
            return json.loads(row["data"])

        # Check TTL
        ttl_hours = int(await get_setting("spotify_cache_ttl_hours", "24"))
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        if datetime.utcnow() - fetched_at < timedelta(hours=ttl_hours):
            log.debug(f"Cache hit: {key}")
            return json.loads(row["data"])

        return None
    finally:
        await db.close()


async def cache_set(key: str, data) -> None:
    """Upsert cache entry with current timestamp."""
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO spotify_cache (cache_key, data, fetched_at) VALUES (?, ?, ?) "
            "ON CONFLICT(cache_key) DO UPDATE SET data = excluded.data, fetched_at = excluded.fetched_at",
            (key, json.dumps(data), datetime.utcnow().isoformat()),
        )
        await db.commit()
    finally:
        await db.close()


async def cache_invalidate(prefix: str = "") -> int:
    """Delete cache entries matching prefix. Empty prefix = delete all. Returns count deleted."""
    db = await get_db()
    try:
        if prefix:
            cur = await db.execute(
                "DELETE FROM spotify_cache WHERE cache_key LIKE ?", (f"{prefix}%",)
            )
        else:
            cur = await db.execute("DELETE FROM spotify_cache")
        await db.commit()
        count = cur.rowcount
        log.info(f"Cache invalidated: {count} entries (prefix='{prefix}')")
        return count
    finally:
        await db.close()
