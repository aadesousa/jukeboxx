import os
import time
import asyncio
import logging
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from database import get_db, get_setting

log = logging.getLogger("jukeboxx.spotify_auth")

# ─── Rate-limit tracking ─────────────────────────────────────────
_rate_limit_until = 0.0  # epoch timestamp when rate limit expires
_api_calls_window = []  # timestamps of recent API calls for rate estimation
API_CALL_WINDOW = 1800  # track calls over 30 min window


def is_rate_limited() -> bool:
    return time.time() < _rate_limit_until


def get_rate_limit_remaining() -> int:
    """Seconds remaining on rate limit, or 0 if not limited."""
    remaining = _rate_limit_until - time.time()
    return int(remaining) if remaining > 0 else 0


def set_rate_limited(retry_after: int):
    global _rate_limit_until
    _rate_limit_until = time.time() + retry_after
    log.warning(f"Spotify rate limited for {retry_after}s (until {time.ctime(_rate_limit_until)})")

REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI", "http://192.168.1.152:6160/api/spotify/callback")
SCOPES = "playlist-read-private,playlist-read-collaborative,user-library-read,user-follow-read"


async def _get_credentials() -> tuple[str, str, str]:
    """Get Spotify credentials from DB settings, falling back to env vars."""
    client_id = await get_setting("spotify_client_id", os.environ.get("SPOTIFY_CLIENT_ID", ""))
    client_secret = await get_setting("spotify_client_secret", os.environ.get("SPOTIFY_CLIENT_SECRET", ""))
    redirect_uri = await get_setting("spotify_redirect_uri", REDIRECT_URI)
    return client_id, client_secret, redirect_uri


async def _get_oauth() -> SpotifyOAuth:
    client_id, client_secret, redirect_uri = await _get_credentials()
    if not client_id or not client_secret:
        raise ValueError("Spotify Client ID and Client Secret must be configured in Settings")
    return SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=SCOPES,
        open_browser=False,
    )


async def get_auth_url() -> str:
    oauth = await _get_oauth()
    return oauth.get_authorize_url()


async def exchange_code(code: str):
    oauth = await _get_oauth()
    token_info = await asyncio.to_thread(oauth.get_access_token, code, True)
    await store_token(token_info)
    return token_info


async def store_token(token_info: dict):
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO spotify_auth (id, access_token, refresh_token, token_type, expires_at, scope, updated_at)
               VALUES (1, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(id) DO UPDATE SET
               access_token=excluded.access_token, refresh_token=excluded.refresh_token,
               token_type=excluded.token_type, expires_at=excluded.expires_at,
               scope=excluded.scope, updated_at=CURRENT_TIMESTAMP""",
            (
                token_info.get("access_token"),
                token_info.get("refresh_token"),
                token_info.get("token_type", "Bearer"),
                token_info.get("expires_at"),
                token_info.get("scope"),
            ),
        )
        await db.commit()
    finally:
        await db.close()


async def get_token_info() -> dict | None:
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM spotify_auth WHERE id = 1")
        row = await cur.fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        await db.close()


async def refresh_token_if_needed():
    info = await get_token_info()
    if not info or not info.get("refresh_token"):
        return
    expires_at = info.get("expires_at", 0)
    if time.time() < expires_at - 300:
        return  # Still valid for >5min
    log.info("Refreshing Spotify token...")
    oauth = await _get_oauth()
    new_info = await asyncio.to_thread(oauth.refresh_access_token, info["refresh_token"])
    await store_token(new_info)
    log.info("Spotify token refreshed")


async def probe_rate_limit(token: str) -> int | None:
    """Quick raw request to check if Spotify is rate-limiting us.
    Returns Retry-After seconds if rate-limited, None if OK."""
    import requests as _req
    try:
        r = await asyncio.to_thread(
            lambda: _req.get(
                "https://api.spotify.com/v1/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
        )
        if r.status_code == 429:
            ra = int(r.headers.get("Retry-After", 300))
            return max(ra, 60)
    except Exception:
        pass
    return None


# Track successful API calls to skip probing when things are working
_last_successful_call = 0.0
_probe_interval = 300  # only probe every 5 min at most


def record_successful_call():
    """Called after a successful Spotify API call to avoid unnecessary probing."""
    global _last_successful_call
    _last_successful_call = time.time()
    now = time.time()
    _api_calls_window.append(now)
    # Prune old entries
    cutoff = now - API_CALL_WINDOW
    while _api_calls_window and _api_calls_window[0] < cutoff:
        _api_calls_window.pop(0)


def get_api_usage_info() -> dict:
    """Return rate limit status and recent API call count for the UI."""
    now = time.time()
    # Prune old entries
    cutoff = now - API_CALL_WINDOW
    while _api_calls_window and _api_calls_window[0] < cutoff:
        _api_calls_window.pop(0)

    limited = is_rate_limited()
    remaining_secs = get_rate_limit_remaining()

    return {
        "rate_limited": limited,
        "rate_limit_remaining_secs": remaining_secs,
        "calls_last_30min": len(_api_calls_window),
        # Spotify's undocumented limit is roughly 180 requests per minute rolling window,
        # but for dev/free apps it's much lower. Estimate conservatively.
        "estimated_limit": "~180/min",
    }


async def get_spotify_client() -> spotipy.Spotify | None:
    if is_rate_limited():
        return None
    info = await get_token_info()
    if not info or not info.get("access_token"):
        return None
    # Check if expired and refresh
    if info.get("expires_at", 0) < time.time() + 60:
        await refresh_token_if_needed()
        info = await get_token_info()
        if not info:
            return None
    # Only probe if we haven't had a successful call recently
    # This avoids burning an API call on every single client creation
    if time.time() - _last_successful_call > _probe_interval:
        _api_calls_window.append(time.time())  # probe counts as an API call
        ra = await probe_rate_limit(info["access_token"])
        if ra is not None:
            set_rate_limited(ra)
            log.warning(f"Spotify probe: rate limited, Retry-After={ra}s")
            return None
        record_successful_call()  # probe succeeded = API is working

    return spotipy.Spotify(
        auth=info["access_token"],
        retries=0,
        status_retries=0,
        requests_timeout=10,
    )
