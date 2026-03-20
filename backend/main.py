import os
import logging
from contextlib import asynccontextmanager

import bcrypt
import jwt
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from database import init_db, get_db, get_setting, set_setting, get_auth_user
from typing import Optional
from pydantic import BaseModel as _BaseModel
from models import (
    TrackOut, DownloadOut, SyncItemOut, SyncItemCreate, SyncItemUpdate,
    DuplicatePairOut, DuplicateResolve, ScanStatusOut, StatsOut,
    SettingsOut, SettingsUpdate, DownloadPreview,
    SetupRequest, LoginRequest,
    NotificationOut, ActivityOut, ScanProgressOut,
)
BaseModel = _BaseModel
import wanted as wanted_module
import youtube as youtube_module
import artists as artists_module
import albums as albums_module
import quality as quality_module
import monitored_tracks as monitored_tracks_module
import spotify_library as spotify_library_module

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("jukeboxx")

SPOTIZERR_URL = os.environ.get("SPOTIZERR_URL", "http://192.168.1.152:7171")
MUSIC_PATH = os.environ.get("MUSIC_PATH", "/music")
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
JWT_EXPIRY_HOURS = 72

PUBLIC_PATHS = {"/health", "/auth/status", "/auth/setup", "/auth/login", "/auth/logout", "/sse-test"}
PUBLIC_PREFIXES = ("/spotify/callback",)

# ── Source display name mapping ───────────────────────────────────────────────
_SOURCE_LABELS = {
    "auto_sync":  "Spotizerr",
    "auto":       "Spotizerr",
    "spotizerr":  "Spotizerr",
    "manual":     "Spotizerr",
    "torrent":    "qBittorrent",
    "usenet":     "SABnzbd",
    "soulseek":   "Soulseek",
    "youtube":    "YouTube",
    "metube":     "YouTube",
}

_ERROR_LABELS = {
    "cannot get alternate track": "No sources found",
    "Recovered: dispatch not confirmed by Spotizerr": "Connection interrupted, will retry",
    "Timed out: not found locally after 24h": "Timed out — not found after 24h",
}


def _friendly_source(source: str | None) -> str:
    if not source:
        return "Unknown"
    return _SOURCE_LABELS.get(source.lower(), source.replace("_", " ").title())


def _friendly_error(msg: str | None) -> str | None:
    if not msg:
        return msg
    for k, v in _ERROR_LABELS.items():
        if k.lower() in msg.lower():
            return v
    return msg


class AuthMiddleware:
    """Pure ASGI middleware — does not buffer streaming responses."""
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "").removeprefix("/api")
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            await self.app(scope, receive, send)
            return

        headers_raw = dict(scope.get("headers", []))

        # Check X-Api-Key header or ?apikey= query param
        api_key_header = headers_raw.get(b"x-api-key", b"").decode().strip()
        query_string = scope.get("query_string", b"").decode()
        api_key_param = ""
        for part in query_string.split("&"):
            k, _, v = part.partition("=")
            if k.lower() == "apikey":
                api_key_param = v.strip()
                break
        incoming_api_key = api_key_header or api_key_param
        if incoming_api_key:
            from database import get_setting as _gs
            stored_key = await _gs("jukeboxx_api_key", "")
            if stored_key and incoming_api_key == stored_key:
                await self.app(scope, receive, send)
                return
            # Key provided but wrong — fall through to JWT check (not reject immediately)

        # Parse cookie header
        cookie_header = headers_raw.get(b"cookie", b"").decode()
        token = None
        for part in cookie_header.split(";"):
            k, _, v = part.strip().partition("=")
            if k.strip() == "jukeboxx_token":
                token = v.strip()
                break

        if not token:
            await self._send_json(send, {"detail": "Not authenticated"}, 401)
            return
        try:
            jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            await self._send_json(send, {"detail": "Token expired"}, 401)
            return
        except jwt.InvalidTokenError:
            await self._send_json(send, {"detail": "Invalid token"}, 401)
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _send_json(send: Send, body: dict, status: int):
        import json as _j
        b = _j.dumps(body).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [[b"content-type", b"application/json"],
                                [b"content-length", str(len(b)).encode()]]})
        await send({"type": "http.response.body", "body": b})


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting JukeBoxx...")
    await init_db()
    # Clean up any scans that were running when we last shut down
    from scanner import cleanup_stale_scans
    await cleanup_stale_scans()
    # Import and start scheduler after DB is ready
    from scheduler import start_scheduler, stop_scheduler
    await start_scheduler()
    log.info("JukeBoxx ready")
    yield
    await stop_scheduler()
    log.info("JukeBoxx stopped")


app = FastAPI(title="JukeBoxx", version="1.0.0", lifespan=lifespan)

app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(wanted_module.router)
app.include_router(youtube_module.router)
app.include_router(artists_module.router)
app.include_router(albums_module.router)
app.include_router(quality_module.router)
app.include_router(monitored_tracks_module.router)
app.include_router(spotify_library_module.router)


# ─── Deezer Image Backfill ────────────────────────────────────────────

@app.post("/images/backfill-artists")
async def images_backfill_artists():
    from images import backfill_artist_images
    updated = await backfill_artist_images(batch_size=20)
    return {"updated": updated}

@app.post("/images/backfill-albums")
async def images_backfill_albums():
    from images import backfill_album_covers
    updated = await backfill_album_covers(batch_size=20)
    return {"updated": updated}


# ─── Health & Stats ─────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "jukeboxx"}


@app.get("/sse-test")
async def sse_test():
    """Minimal SSE test: sends 5 events 1s apart. No auth, no DB."""
    import json as _j, asyncio as _a
    async def gen():
        for i in range(5):
            yield f"data: {_j.dumps({'i': i, 'msg': f'event {i}'})}\n\n"
            await _a.sleep(1)
        yield f"data: {_j.dumps({'i': 'done'})}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/stats", response_model=StatsOut)
async def get_stats():
    db = await get_db()
    try:
        # Total tracks + library stats
        cur = await db.execute("SELECT COUNT(*) as c, COALESCE(SUM(size),0) as s FROM tracks")
        row = await cur.fetchone()
        total_tracks = row["c"]
        total_size = row["s"]

        cur = await db.execute("SELECT COUNT(DISTINCT COALESCE(album_artist, artist)) as c FROM tracks WHERE COALESCE(album_artist, artist) IS NOT NULL")
        total_artists = (await cur.fetchone())["c"]

        cur = await db.execute("SELECT COUNT(DISTINCT album) as c FROM tracks WHERE album IS NOT NULL")
        total_albums = (await cur.fetchone())["c"]

        cur = await db.execute("SELECT COUNT(*) as c FROM monitored_tracks WHERE status = 'wanted' AND monitored = 1")
        total_missing = (await cur.fetchone())["c"]

        # Format breakdown
        cur = await db.execute("SELECT format, COUNT(*) as c FROM tracks WHERE format IS NOT NULL GROUP BY format")
        rows = await cur.fetchall()
        format_breakdown = {r["format"]: r["c"] for r in rows}

        # Sync items
        cur = await db.execute("SELECT COUNT(*) as c FROM sync_items WHERE enabled = 1")
        sync_items = (await cur.fetchone())["c"]

        # Download stats
        cur = await db.execute("SELECT COUNT(*) as c FROM downloads WHERE status IN ('pending','downloading')")
        pending_dl = (await cur.fetchone())["c"]
        cur = await db.execute("SELECT COUNT(*) as c FROM downloads WHERE status = 'failed'")
        failed_dl = (await cur.fetchone())["c"]

        # Duplicate stats
        cur = await db.execute("SELECT COUNT(*) as c FROM duplicate_pairs WHERE status = 'pending'")
        pending_dupes = (await cur.fetchone())["c"]

        # Last scan
        cur = await db.execute("SELECT * FROM scan_history ORDER BY id DESC LIMIT 1")
        scan_row = await cur.fetchone()
        last_scan = None
        if scan_row:
            last_scan = ScanStatusOut(**dict(scan_row))

        # Spotizerr reachable
        import httpx
        spotizerr_ok = False
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{SPOTIZERR_URL}")
                spotizerr_ok = r.status_code < 500
        except Exception:
            pass

        # Spotify connected
        cur = await db.execute("SELECT access_token FROM spotify_auth WHERE id = 1")
        sp_row = await cur.fetchone()
        spotify_connected = sp_row is not None and sp_row["access_token"] is not None

        # Failed imports stats
        from tasks import get_failed_imports_stats
        failed_imports = await get_failed_imports_stats()

        return StatsOut(
            total_tracks=total_tracks,
            total_artists=total_artists,
            total_albums=total_albums,
            total_missing=total_missing,
            total_size_gb=round(total_size / (1024**3), 2) if total_size else 0.0,
            format_breakdown=format_breakdown,
            sync_items=sync_items,
            pending_downloads=pending_dl,
            failed_downloads=failed_dl,
            pending_duplicates=pending_dupes,
            last_scan=last_scan,
            spotizerr_reachable=spotizerr_ok,
            spotify_connected=spotify_connected,
            failed_imports=failed_imports,
        )
    finally:
        await db.close()


# ─── Auth ────────────────────────────────────────────────────────────

def _make_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


@app.get("/auth/status")
async def auth_status(request: Request):
    user = await get_auth_user()
    setup_complete = user is not None
    authenticated = False
    username = None
    token = request.cookies.get("jukeboxx_token")
    if token and user:
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            authenticated = True
            username = payload.get("sub")
        except jwt.InvalidTokenError:
            pass
    return {"setup_complete": setup_complete, "authenticated": authenticated, "username": username}


@app.post("/auth/setup")
async def auth_setup(body: SetupRequest):
    existing = await get_auth_user()
    if existing:
        raise HTTPException(400, "Account already exists")
    if not body.username.strip() or len(body.password) < 4:
        raise HTTPException(400, "Username required and password must be at least 4 characters")
    pw_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO auth (id, username, password_hash) VALUES (1, ?, ?)",
            (body.username.strip(), pw_hash),
        )
        await db.commit()
    finally:
        await db.close()
    token = _make_token(body.username.strip())
    response = JSONResponse({"status": "ok", "username": body.username.strip()})
    response.set_cookie(
        "jukeboxx_token", token,
        httponly=True, samesite="lax", max_age=JWT_EXPIRY_HOURS * 3600, path="/",
    )
    return response


@app.post("/auth/login")
async def auth_login(body: LoginRequest):
    user = await get_auth_user()
    if not user:
        raise HTTPException(400, "No account configured")
    if user["username"] != body.username or not bcrypt.checkpw(body.password.encode(), user["password_hash"].encode()):
        raise HTTPException(401, "Invalid credentials")
    token = _make_token(user["username"])
    response = JSONResponse({"status": "ok", "username": user["username"]})
    response.set_cookie(
        "jukeboxx_token", token,
        httponly=True, samesite="lax", max_age=JWT_EXPIRY_HOURS * 3600, path="/",
    )
    return response


@app.post("/auth/logout")
async def auth_logout():
    response = JSONResponse({"status": "ok"})
    response.delete_cookie("jukeboxx_token", path="/")
    return response


# ─── Spotify OAuth ──────────────────────────────────────────────────

@app.get("/spotify/status")
async def spotify_status():
    from spotify_auth import get_token_info, get_api_usage_info
    info = await get_token_info()
    usage = get_api_usage_info()
    if info and info.get("access_token"):
        return {"connected": True, "scopes": info.get("scope", ""), **usage}
    return {"connected": False, **usage}


@app.get("/spotify/auth-url")
async def spotify_auth_url():
    from spotify_auth import get_auth_url
    try:
        url = await get_auth_url()
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"url": url}


@app.get("/spotify/callback")
async def spotify_callback(code: str, state: str = ""):
    from spotify_auth import exchange_code
    try:
        await exchange_code(code)
    except Exception as e:
        log.error(f"Spotify callback error: {e}")
        return HTMLResponse(f"<html><body><h2>Error: {e}</h2></body></html>", status_code=400)
    return HTMLResponse("""
    <html><body><script>
    if (window.opener) {
        window.opener.postMessage({type: 'spotify-connected'}, '*');
    }
    window.close();
    </script><p>Connected! You can close this window.</p></body></html>
    """)


@app.post("/spotify/disconnect")
async def spotify_disconnect():
    from spotify_cache import cache_invalidate
    db = await get_db()
    try:
        await db.execute("DELETE FROM spotify_auth WHERE id = 1")
        await db.commit()
    finally:
        await db.close()
    await cache_invalidate()
    return {"status": "disconnected"}


@app.post("/spotify/cache/invalidate")
async def spotify_cache_invalidate_all():
    from spotify_cache import cache_invalidate
    count = await cache_invalidate()
    return {"status": "ok", "entries_cleared": count}


# ─── Spotify Library Browsing ───────────────────────────────────────

def _parse_retry_after(e: Exception) -> int:
    """Extract Retry-After seconds from a Spotify exception, with sensible defaults."""
    import re, asyncio as _asyncio
    # SpotifyException has a headers attribute
    headers = getattr(e, 'headers', None)
    if headers:
        try:
            val = headers.get('Retry-After') or headers.get('retry-after')
            if val:
                return max(int(val), 60)
        except (ValueError, TypeError):
            pass
    # Try parsing from the error message
    err_str = str(e).lower()
    m = re.search(r'retry-after[:\s]+(\d+)', err_str)
    if m:
        return max(int(m.group(1)), 60)
    # Default: 30min for timeouts, 5min for explicit 429s
    if isinstance(e, _asyncio.TimeoutError):
        return 1800
    return 300

async def _enrich_playlist_counts(playlists: list):
    """Override tracks.total with accurate counts from sync_items (populated by playlist sync)."""
    if not playlists:
        return
    db = await get_db()
    try:
        cur = await db.execute("SELECT spotify_id, track_count FROM sync_items WHERE track_count > 0")
        sync_counts = {row["spotify_id"]: row["track_count"] for row in await cur.fetchall()}
    finally:
        await db.close()
    for pl in playlists:
        pid = pl.get("id")
        if pid and pid in sync_counts:
            if not isinstance(pl.get("tracks"), dict):
                pl["tracks"] = {}
            pl["tracks"]["total"] = sync_counts[pid]


@app.get("/spotify/playlists")
async def spotify_playlists(offset: int = 0, limit: int = 50, refresh: bool = False):
    import asyncio
    from spotify_client import get_client
    from spotify_auth import is_rate_limited, get_rate_limit_remaining, set_rate_limited, record_successful_call
    from spotify_cache import cache_get, cache_set

    cache_key = "playlists"

    # Try cache first
    cached = await cache_get(cache_key, force_refresh=refresh)
    if cached is not None:
        # Slice from cached full list
        items = cached.get("items", [])
        total = cached.get("total", len(items))
        return_items = items[offset:offset + limit]
        await _enrich_playlist_counts(return_items)
        return {"items": return_items, "total": total, "offset": offset, "limit": limit, "next": None}

    if is_rate_limited():
        remaining = get_rate_limit_remaining()
        raise HTTPException(429, f"Spotify rate limited — try again in {remaining // 60} min")
    sp = await get_client()
    if not sp:
        # Distinguish: rate limited (probe set the flag) vs actually not connected
        if is_rate_limited():
            remaining = get_rate_limit_remaining()
            raise HTTPException(429, f"Spotify rate limited — try again in {remaining // 60} min")
        raise HTTPException(403, "Spotify not connected")

    # Fetch ALL playlists from Spotify (paginated) and cache the full list
    all_items = []
    fetch_offset = 0
    try:
        while True:
            results = await asyncio.wait_for(
                asyncio.to_thread(sp.current_user_playlists, 50, fetch_offset),
                timeout=15,
            )
            record_successful_call()
            items = results.get("items", [])
            if not items:
                break
            # Normalize: dev mode uses 'items' instead of 'tracks' for track count
            for pl in items:
                current_total = 0
                if isinstance(pl.get("tracks"), dict):
                    current_total = pl["tracks"].get("total", 0)
                elif isinstance(pl.get("items"), dict):
                    current_total = pl["items"].get("total", 0)
                elif isinstance(pl.get("items"), list):
                    current_total = len(pl["items"])
                if not isinstance(pl.get("tracks"), dict):
                    pl["tracks"] = {}
                pl["tracks"]["total"] = current_total
            all_items.extend(items)
            if not results.get("next"):
                break
            fetch_offset += len(items)
    except (asyncio.TimeoutError, Exception) as e:
        err_str = str(e).lower()
        is_rate_limit = isinstance(e, asyncio.TimeoutError) or "429" in str(e) or "too many requests" in err_str or "retry-after" in err_str
        if is_rate_limit:
            retry_after = _parse_retry_after(e)
            set_rate_limited(retry_after)
            log.warning(f"Spotify API failed ({type(e).__name__}), backing off for {retry_after}s")
            # Try serving stale cache
            stale = await cache_get(cache_key)
            if stale is not None:
                items = stale.get("items", [])
                return_items = items[offset:offset + limit]
                await _enrich_playlist_counts(return_items)
                return {"items": return_items, "total": stale.get("total", len(items)), "offset": offset, "limit": limit, "next": None}
            remaining = get_rate_limit_remaining()
            raise HTTPException(429, f"Spotify rate limited — try again in {remaining // 60} min")
        raise

    full_data = {"items": all_items, "total": len(all_items)}
    await cache_set(cache_key, full_data)

    return_items = all_items[offset:offset + limit]
    await _enrich_playlist_counts(return_items)
    return {"items": return_items, "total": len(all_items), "offset": offset, "limit": limit, "next": None}


@app.get("/spotify/playlists/{playlist_id}/tracks")
async def spotify_playlist_tracks(playlist_id: str, offset: int = 0, limit: int = 100, refresh: bool = False):
    import asyncio
    from spotify_client import get_client, enrich_tracks_with_local_status, _extract_playlist_track, get_all_playlist_tracks
    from spotify_cache import cache_get, cache_set
    from spotify_auth import is_rate_limited, set_rate_limited

    cache_key = f"playlist_tracks:{playlist_id}"

    # Try cache first — cache stores ALL tracks for this playlist
    cached = await cache_get(cache_key, force_refresh=refresh)
    if cached is not None:
        all_tracks = cached
        sliced = all_tracks[offset:offset + limit]
        # Always enrich with live local status (not cached — changes as downloads complete)
        await enrich_tracks_with_local_status(sliced)
        return {"items": sliced, "total": len(all_tracks), "offset": offset, "limit": limit}

    sp = await get_client()
    if not sp:
        if is_rate_limited():
            from spotify_auth import get_rate_limit_remaining
            remaining = get_rate_limit_remaining()
            raise HTTPException(429, f"Spotify rate limited — try again in {remaining // 60} min")
        raise HTTPException(403, "Spotify not connected")

    try:
        all_tracks = await asyncio.wait_for(
            get_all_playlist_tracks(sp, playlist_id),
            timeout=30,
        )
    except (asyncio.TimeoutError, Exception) as e:
        err_str = str(e).lower()
        is_rate_err = isinstance(e, asyncio.TimeoutError) or "429" in str(e) or "too many requests" in err_str
        if is_rate_err:
            retry_after = _parse_retry_after(e)
            set_rate_limited(retry_after)
            log.warning(f"Spotify tracks fetch failed ({type(e).__name__}) for {playlist_id}, backing off {retry_after}s")
            # Serve stale cache if available
            stale = await cache_get(cache_key)
            if stale is not None:
                sliced = stale[offset:offset + limit]
                await enrich_tracks_with_local_status(sliced)
                return {"items": sliced, "total": len(stale), "offset": offset, "limit": limit}
            remaining = get_rate_limit_remaining()
            raise HTTPException(429, f"Spotify rate limited — try again in {remaining // 60} min")
        raise

    # Cache the full track list
    await cache_set(cache_key, all_tracks)

    sliced = all_tracks[offset:offset + limit]
    await enrich_tracks_with_local_status(sliced)
    return {"items": sliced, "total": len(all_tracks), "offset": offset, "limit": limit}




@app.get("/spotify/search")
async def spotify_search(q: str, type: str = "artist", limit: int = 10):
    """Search Spotify for artists, albums, or tracks."""
    from spotify_client import get_client
    from spotify_auth import is_rate_limited
    sp = await get_client()
    if not sp:
        if is_rate_limited():
            raise HTTPException(429, "Spotify rate limited")
        raise HTTPException(403, "Spotify not connected")
    import asyncio
    try:
        result = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, lambda: sp.search(q=q, type=type, limit=limit)),
            timeout=10
        )
        from spotify_auth import record_successful_call
        record_successful_call()
        return result
    except asyncio.TimeoutError:
        raise HTTPException(504, "Spotify search timed out")
    except Exception as e:
        raise HTTPException(502, f"Spotify search error: {e}")


@app.get("/spotify/artist/{artist_id}/albums")
async def spotify_artist_albums(artist_id: str, limit: int = 50, include_groups: str = "album,single,ep"):
    """Get all albums for a Spotify artist."""
    from spotify_client import get_client
    from spotify_auth import is_rate_limited, record_successful_call
    sp = await get_client()
    if not sp:
        if is_rate_limited():
            raise HTTPException(429, "Spotify rate limited")
        raise HTTPException(403, "Spotify not connected")
    import asyncio
    try:
        all_albums = []
        offset = 0
        while True:
            batch = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: sp.artist_albums(artist_id, album_type=include_groups, limit=50, offset=offset)
                ),
                timeout=15
            )
            record_successful_call()
            items = batch.get("items", [])
            all_albums.extend(items)
            if not batch.get("next") or len(all_albums) >= limit:
                break
            offset += 50
        return {"items": all_albums[:limit], "total": len(all_albums)}
    except asyncio.TimeoutError:
        raise HTTPException(504, "Spotify artist albums request timed out")
    except Exception as e:
        raise HTTPException(502, f"Spotify artist albums error: {e}")


# ─── Downloads ──────────────────────────────────────────────────────

@app.get("/downloads/queue-stats")
async def downloads_queue_stats():
    """Returns comprehensive queue stats for the UI visualization."""
    from spotizerr_client import get_spotizerr_queue_status
    from datetime import datetime, timedelta

    queue_status = await get_spotizerr_queue_status()

    db = await get_db()
    try:
        # Status breakdown
        cur = await db.execute(
            "SELECT status, COUNT(*) as count FROM downloads GROUP BY status"
        )
        rows = await cur.fetchall()
        status_counts = {r["status"]: r["count"] for r in rows}

        # Pending by source
        cur = await db.execute(
            "SELECT source, COUNT(*) as count FROM downloads WHERE status = 'pending' GROUP BY source"
        )
        rows = await cur.fetchall()
        pending_by_source = {r["source"]: r["count"] for r in rows}

        # Cooling count
        cur = await db.execute("SELECT COUNT(*) as c FROM downloads WHERE status = 'cooling'")
        cooling = (await cur.fetchone())["c"]

        # Stuck downloading (>2 hours)
        stale_cutoff = (datetime.utcnow() - timedelta(hours=2)).isoformat()
        cur = await db.execute(
            "SELECT COUNT(*) as c FROM downloads WHERE status = 'downloading' AND updated_at < ?",
            (stale_cutoff,),
        )
        stuck = (await cur.fetchone())["c"]

        # Recent completed (last hour)
        recent_cutoff = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        cur = await db.execute(
            "SELECT COUNT(*) as c FROM downloads WHERE status = 'completed' AND updated_at > ?",
            (recent_cutoff,),
        )
        recent_completed = (await cur.fetchone())["c"]

        # Retry distribution for failed
        cur = await db.execute(
            """SELECT
                SUM(CASE WHEN retry_count < 5 THEN 1 ELSE 0 END) as low,
                SUM(CASE WHEN retry_count >= 5 AND retry_count < 15 THEN 1 ELSE 0 END) as mid,
                SUM(CASE WHEN retry_count >= 15 THEN 1 ELSE 0 END) as high
               FROM downloads WHERE status = 'failed'"""
        )
        row = await cur.fetchone()
        retry_dist = {"low": row["low"] or 0, "mid": row["mid"] or 0, "high": row["high"] or 0}

        # Total and completed counts for overall progress bar
        cur = await db.execute("SELECT COUNT(*) as c FROM downloads")
        total_all = (await cur.fetchone())["c"]
        cur = await db.execute("SELECT COUNT(*) as c FROM downloads WHERE status = 'completed'")
        completed_total = (await cur.fetchone())["c"]

        # Next dispatch info
        from scheduler import scheduler as apscheduler
        dispatch_job = apscheduler.get_job("steady_dispatch")
        next_dispatch = str(dispatch_job.next_run_time) if dispatch_job else None

    finally:
        await db.close()

    # Unified downloads status counts
    db2 = await get_db()
    try:
        cur = await db2.execute(
            "SELECT status, COUNT(*) as count FROM unified_downloads GROUP BY status"
        )
        unified_counts = {r["status"]: r["count"] for r in await cur.fetchall()}
    finally:
        await db2.close()

    queue_paused = await get_setting("queue_paused", "0") == "1"

    return {
        "spotizerr": queue_status,
        "counts": status_counts,
        "unified_counts": unified_counts,
        "pending_by_source": pending_by_source,
        "stuck_downloading": stuck,
        "cooling": cooling,
        "recent_completed_1h": recent_completed,
        "retry_distribution": retry_dist,
        "next_dispatch": next_dispatch,
        "total_all": total_all,
        "completed_total": completed_total,
        "queue_paused": queue_paused,
    }


@app.post("/downloads/dispatch-now")
async def downloads_dispatch_now():
    """
    Trigger dispatch immediately.
    - Runs Spotizerr redispatch synchronously (fast, ~15s) for immediate feedback.
    - Kicks off full multi-source dispatch in background for non-Spotizerr sources.
    """
    import asyncio
    from spotizerr_client import get_spotizerr_queue_status, redispatch_pending
    from tasks import run_multi_source_dispatch, _dp

    sp_dispatched = 0
    breakdown: dict = {}

    # Mark dispatch as starting immediately so the frontend doesn't see stale "done" state
    _dp(running=True, phase="searching", track_index=0, track_total=-1,
        dispatched=0, breakdown={}, error="", track_name="", track_artist="", source="")

    # Fast path: Spotizerr (capacity-aware, returns quickly)
    try:
        sp_status = await get_spotizerr_queue_status()
        if sp_status.get("reachable") and sp_status.get("available", 0) > 0:
            sp_dispatched = await redispatch_pending(available_slots=sp_status["available"])
            if sp_dispatched:
                breakdown["spotizerr"] = sp_dispatched
    except Exception as e:
        log.warning(f"Spotizerr dispatch error in dispatch-now: {e}")

    # Slow path: torrent / usenet / soulseek / youtube — run in background.
    # concurrency=5: 5 tracks searched in parallel (all I/O-bound, no extra CPU cost).
    # limit=200: enough for a meaningful manual sweep; scheduler covers the rest in steady batches.
    asyncio.create_task(run_multi_source_dispatch(limit=200, concurrency=5))

    total = sp_dispatched
    return {
        "status": "dispatching",
        "dispatched": total,
        "breakdown": breakdown,
        "message": "Spotizerr dispatched immediately. Other sources searching in background — check Activity for results.",
    }


@app.post("/downloads/track/{spotify_id}")
async def download_track(spotify_id: str, force: bool = False):
    from spotizerr_client import dispatch_download
    from dedup import check_track_dedup
    if not force:
        skip, reason = await check_track_dedup(spotify_id)
        if skip:
            return {"status": "skipped", "reason": reason}
    result = await dispatch_download(spotify_id, "track")
    return result



@app.post("/downloads/playlist/{spotify_id}")
async def download_playlist(spotify_id: str):
    from spotizerr_client import dispatch_download
    result = await dispatch_download(spotify_id, "playlist")
    return result


@app.get("/downloads/active")
async def downloads_active():
    results = []
    db = await get_db()
    try:
        spotizerr_rows = await (await db.execute(
            """SELECT id, spotify_id, title, artist, album, item_type, status,
               error_message, retry_count, created_at
               FROM downloads WHERE status IN ('pending','downloading','failed','cooling')
               ORDER BY created_at DESC LIMIT 200"""
        )).fetchall()
        for r in spotizerr_rows:
            results.append({
                "id": f"sp_{r['id']}", "title": r["title"], "artist": r["artist"],
                "album": r["album"], "item_type": r["item_type"], "status": r["status"],
                "source": "spotizerr", "source_label": "Spotizerr", "progress": None,
                "error_message": _friendly_error(r["error_message"]), "retry_count": r["retry_count"],
                "created_at": r["created_at"],
            })
        unified_rows = await (await db.execute(
            """SELECT id, spotify_id, title, artist, album, item_type, status,
               source, error_message, retry_count, created_at
               FROM unified_downloads WHERE status IN ('queued','downloading','failed')
               ORDER BY created_at DESC LIMIT 200"""
        )).fetchall()
        for r in unified_rows:
            results.append({
                "id": f"ud_{r['id']}", "title": r["title"], "artist": r["artist"],
                "album": r["album"], "item_type": r["item_type"], "status": r["status"],
                "source": r["source"], "source_label": _friendly_source(r["source"]), "progress": None,
                "error_message": _friendly_error(r["error_message"]), "retry_count": r["retry_count"],
                "created_at": r["created_at"],
            })
    finally:
        await db.close()
    results.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return results


@app.get("/downloads/stream")
async def downloads_stream():
    from spotizerr_client import stream_progress
    return StreamingResponse(stream_progress(), media_type="text/event-stream")


@app.get("/downloads/history")
async def downloads_history(offset: int = 0, limit: int = 50):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM downloads ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = [dict(r) for r in await cur.fetchall()]
        for r in rows:
            r["source_label"] = _friendly_source(r.get("source"))
            r["error_message"] = _friendly_error(r.get("error_message"))
        return rows
    finally:
        await db.close()


@app.get("/downloads/failed")
async def downloads_failed():
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM downloads WHERE status = 'failed' ORDER BY updated_at DESC"
        )
        rows = [dict(r) for r in await cur.fetchall()]
        for r in rows:
            r["source_label"] = _friendly_source(r.get("source"))
            r["error_message"] = _friendly_error(r.get("error_message"))
        return rows
    finally:
        await db.close()


@app.post("/downloads/retry-all-failed")
async def download_retry_all_failed():
    from spotizerr_client import retry_all_failed
    count = await retry_all_failed()
    return {"retried": count, "total": count}


@app.post("/downloads/{download_id}/retry")
async def download_retry(download_id: int):
    from spotizerr_client import retry_download
    return await retry_download(download_id)


@app.post("/downloads/{download_id}/cancel")
async def download_cancel(download_id: int):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE downloads SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (download_id,),
        )
        await db.commit()
        return {"status": "cancelled"}
    finally:
        await db.close()


@app.post("/downloads/unified/{unified_id}/cancel")
async def unified_download_cancel(unified_id: int):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE unified_downloads SET status='cancelled', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (unified_id,),
        )
        await db.commit()
        return {"status": "cancelled"}
    finally:
        await db.close()


@app.get("/downloads/unified/history")
async def unified_download_history(limit: int = 100):
    db = await get_db()
    try:
        # Exclude active (queued/downloading) — those belong in the live view, not history
        cur = await db.execute(
            "SELECT * FROM unified_downloads WHERE status NOT IN ('queued','downloading') ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = [dict(r) for r in await cur.fetchall()]
        for r in rows:
            r["source_label"] = _friendly_source(r.get("source"))
            r["error_message"] = _friendly_error(r.get("error_message"))
        return rows
    finally:
        await db.close()


@app.get("/downloads/live-status")
async def downloads_live_status():
    """Query all configured download clients for current live download status."""
    import httpx
    from grabbers import _get_client_row, _qbit_base, _sabnzbd_base, _slskd_base

    result = {"qbittorrent": [], "sabnzbd": [], "slskd": [], "youtube": []}

    # ── qBittorrent ──────────────────────────────────────────────────
    qbit_row = await _get_client_row("qbittorrent")
    if qbit_row:
        try:
            base = _qbit_base(qbit_row)
            async with httpx.AsyncClient(timeout=10) as hc:
                if qbit_row.get("username"):
                    await hc.post(
                        f"{base}/api/v2/auth/login",
                        data={"username": qbit_row["username"], "password": qbit_row.get("password", "")},
                    )
                resp = await hc.get(f"{base}/api/v2/torrents/info", params={"category": "music"})
                if resp.status_code == 200:
                    for t in resp.json():
                        state = t.get("state", "")
                        stalled = state in ("stalledDL", "stalledUP", "error", "missingFiles")
                        result["qbittorrent"].append({
                            "hash": t.get("hash", ""),
                            "name": t.get("name", ""),
                            "progress": round(t.get("progress", 0) * 100, 1),
                            "state": state,
                            "stalled": stalled,
                            "size": t.get("size", 0),
                            "dlspeed": t.get("dlspeed", 0),
                            "num_seeds": t.get("num_seeds", 0),
                            "eta": t.get("eta", -1),
                            "added_on": t.get("added_on", 0),
                        })
        except Exception as e:
            log.debug(f"qBit live-status error: {e}")
            result["qbittorrent_error"] = str(e)

    # ── SABnzbd ──────────────────────────────────────────────────────
    sabnzbd_row = await _get_client_row("sabnzbd")
    if sabnzbd_row:
        try:
            base = _sabnzbd_base(sabnzbd_row)
            async with httpx.AsyncClient(timeout=10) as hc:
                resp = await hc.get(f"{base}/api", params={
                    "mode": "queue", "output": "json",
                    "apikey": sabnzbd_row.get("api_key", ""),
                })
                if resp.status_code == 200:
                    for slot in resp.json().get("queue", {}).get("slots", []):
                        mb = float(slot.get("mb", 0) or 0)
                        mbleft = float(slot.get("mbleft", 0) or 0)
                        progress = round((mb - mbleft) / mb * 100, 1) if mb > 0 else 0
                        result["sabnzbd"].append({
                            "nzo_id": slot.get("nzo_id", ""),
                            "name": slot.get("filename") or slot.get("name", ""),
                            "status": slot.get("status", ""),
                            "size_mb": mb,
                            "size_left_mb": mbleft,
                            "progress": progress,
                            "eta": slot.get("timeleft", ""),
                        })
        except Exception as e:
            log.debug(f"SABnzbd live-status error: {e}")
            result["sabnzbd_error"] = str(e)

    # ── slskd (Soulseek) ─────────────────────────────────────────────
    slskd_row = await _get_client_row("slskd")
    if slskd_row:
        try:
            from grabbers import _slskd_base
            url = _slskd_base(slskd_row)
            api_key = slskd_row.get("api_key", "")
            headers = {"X-API-Key": api_key} if api_key else {}
            async with httpx.AsyncClient(timeout=10) as hc:
                resp = await hc.get(f"{url}/api/v0/transfers/downloads", headers=headers)
                if resp.status_code == 200:
                    for user_block in resp.json():
                        username = user_block.get("username", "")
                        for d in user_block.get("directories", []):
                            for f in d.get("files", []):
                                state = f.get("state", "")
                                if "Completed" in state:
                                    continue  # completed transfers belong in history, not live view
                                size = f.get("size", 0) or 1
                                transferred = f.get("bytesTransferred", 0) or 0
                                result["slskd"].append({
                                    "id": f.get("id", ""),
                                    "username": username,
                                    "filename": f.get("filename", "").replace("\\", "/").split("/")[-1],
                                    "state": state,
                                    "size": size,
                                    "bytes_transferred": transferred,
                                    "progress": round(transferred / size * 100, 1),
                                    "average_speed": f.get("averageSpeed", 0),
                                    "enqueued_at": f.get("enqueuedAt") or f.get("requestedAt"),
                                })
        except Exception as e:
            log.debug(f"slskd live-status error: {e}")
            result["slskd_error"] = str(e)

    # ── YouTube (MeTube /history) ─────────────────────────────────────────
    metube_url = await get_setting("metube_url", "http://metube:8081")
    try:
        async with httpx.AsyncClient(timeout=5) as hc:
            r = await hc.get(f"{metube_url}/history")
            if r.status_code == 200:
                hist = r.json()
                yt_items = []
                for category, st in (("queue", "queued"), ("pending", "pending"), ("done", None)):
                    for item in hist.get(category, []):
                        actual_status = item.get("status", st or "finished")
                        pct = item.get("percent", 100.0 if actual_status == "finished" else 0.0) or 0.0
                        raw_ts = item.get("timestamp")
                        # MeTube timestamps are nanoseconds since epoch
                        ts_sec = int(raw_ts) / 1e9 if raw_ts else None
                        yt_items.append({
                            "id": item.get("id", ""),
                            "title": item.get("title") or item.get("url", ""),
                            "url": item.get("url", ""),
                            "status": actual_status,
                            "percent": round(float(pct), 1),
                            "speed": item.get("speed"),
                            "eta": item.get("eta"),
                            "filename": (item.get("filename") or "").split("/")[-1],
                            "error": item.get("error"),
                            "timestamp": ts_sec,
                        })
                result["youtube"] = yt_items
            else:
                result["youtube"] = []
                result["youtube_error"] = f"MeTube returned {r.status_code}"
    except Exception as e:
        log.debug(f"MeTube live-status error: {e}")
        result["youtube"] = []
        result["youtube_error"] = str(e)

    return result


@app.post("/downloads/slskd/cancel-stalled")
async def slskd_cancel_stalled():
    """Cancel all slskd transfers stuck in Queued, Remotely state."""
    import httpx
    from grabbers import _get_client_row, _slskd_base
    row = await _get_client_row("slskd")
    if not row:
        raise HTTPException(404, "slskd not configured")
    url = _slskd_base(row)
    api_key = row.get("api_key", "")
    headers = {"X-API-Key": api_key} if api_key else {}
    cancelled = 0
    errors = 0
    try:
        async with httpx.AsyncClient(timeout=15) as hc:
            resp = await hc.get(f"{url}/api/v0/transfers/downloads", headers=headers)
            if resp.status_code != 200:
                raise HTTPException(502, f"slskd returned {resp.status_code}")
            for user_block in resp.json():
                username = user_block.get("username", "")
                for d in user_block.get("directories", []):
                    for f in d.get("files", []):
                        if "Queued" in f.get("state", "") or f.get("state", "") in ("Requested", "Initializing"):
                            fid = f.get("id", "")
                            if not fid:
                                continue
                            r = await hc.delete(
                                f"{url}/api/v0/transfers/downloads/{username}/{fid}",
                                headers=headers,
                            )
                            if r.status_code in (200, 204):
                                cancelled += 1
                            else:
                                errors += 1
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e))
    return {"cancelled": cancelled, "errors": errors}


@app.post("/downloads/unified/{unified_id}/blocklist")
async def unified_download_blocklist(unified_id: int):
    """Cancel a unified download, blocklist its source URL, and re-queue the track."""
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM unified_downloads WHERE id=?", (unified_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Download not found")
        dl = dict(row)

        source_url = dl.get("source_url") or ""
        source = dl.get("source", "")
        title = dl.get("title", "")

        # Blocklist the URL so it won't be grabbed again
        if source_url:
            await db.execute(
                """INSERT OR IGNORE INTO blocklist (type, value, title, reason, source, added_at)
                   VALUES ('url', ?, ?, 'User blocklisted', ?, CURRENT_TIMESTAMP)""",
                (source_url, title, source),
            )

        # Mark as cancelled
        await db.execute(
            "UPDATE unified_downloads SET status='cancelled', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (unified_id,),
        )

        # Re-queue the monitored track so it gets retried via another source
        if dl.get("monitored_track_id"):
            await db.execute(
                """UPDATE monitored_tracks SET status='wanted', updated_at=CURRENT_TIMESTAMP
                   WHERE id=? AND status IN ('downloading','wanted')""",
                (dl["monitored_track_id"],),
            )

        await db.commit()
        return {"status": "blocklisted", "source_url": source_url}
    finally:
        await db.close()


@app.get("/downloads/spotizerr-candidates")
async def downloads_spotizerr_candidates(limit: int = 500):
    """
    Tracks that need manual Spotizerr dispatch:
    monitored_tracks with status='wanted' that have no active unified_download.
    Sorted by failed_attempts desc so the most-tried tracks appear first.
    """
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT mt.id, mt.spotify_id, mt.name, mt.artist_name, mt.album_name,
                      mt.image_url, mt.status, mt.added_at,
                      COUNT(CASE WHEN ud.status='failed' THEN 1 END) as failed_attempts,
                      MAX(ud.updated_at) as last_attempt_at
               FROM monitored_tracks mt
               LEFT JOIN unified_downloads ud ON ud.monitored_track_id = mt.id
               WHERE mt.status = 'wanted' AND mt.monitored = 1
               AND NOT EXISTS (
                   SELECT 1 FROM unified_downloads ud2
                   WHERE ud2.monitored_track_id = mt.id
                   AND ud2.status IN ('queued', 'downloading')
               )
               GROUP BY mt.id
               ORDER BY failed_attempts DESC, mt.added_at ASC
               LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


class _SpotizerSendRequest(_BaseModel):
    monitored_track_ids: list[int]


@app.post("/downloads/spotizerr-send")
async def downloads_spotizerr_send(body: _SpotizerSendRequest):
    """Manually send a batch of tracks to Spotizerr."""
    from spotizerr_client import dispatch_download

    results = []
    for track_id in body.monitored_track_ids:
        db = await get_db()
        try:
            cur = await db.execute("SELECT * FROM monitored_tracks WHERE id=?", (track_id,))
            row = await cur.fetchone()
            if not row:
                results.append({"id": track_id, "status": "not_found"})
                continue
            track = dict(row)
        finally:
            await db.close()

        try:
            result = await dispatch_download(
                track["spotify_id"], "track",
                track.get("name", ""), track.get("artist_name", ""), track.get("album_name", ""),
                source="manual",
            )
            results.append({"id": track_id, "spotify_id": track["spotify_id"], **result})
        except Exception as e:
            results.append({"id": track_id, "status": "error", "reason": str(e)})

    sent = sum(1 for r in results if r.get("status") not in ("error", "not_found", "skipped"))
    return {"results": results, "sent": sent}


@app.post("/downloads/qbittorrent/clear-stalled")
async def qbittorrent_clear_stalled():
    """Remove stalled music torrents from qBittorrent and blocklist their hashes."""
    import httpx, time
    from grabbers import _get_client_row, _qbit_base

    row = await _get_client_row("qbittorrent")
    if not row:
        raise HTTPException(404, "qBittorrent client not configured")

    base = _qbit_base(row)
    stalled = []
    now = time.time()

    try:
        async with httpx.AsyncClient(timeout=15) as hc:
            if row.get("username"):
                await hc.post(f"{base}/api/v2/auth/login",
                    data={"username": row["username"], "password": row.get("password","")})
            resp = await hc.get(f"{base}/api/v2/torrents/info", params={"category": "music"})
            if resp.status_code != 200:
                raise HTTPException(502, "qBittorrent unreachable")
            for t in resp.json():
                state = t.get("state","")
                added_on = t.get("added_on", now)
                is_stalled = (
                    state in ("stalledDL", "error", "missingFiles") or
                    (state == "metaDL" and (now - added_on) > 10)
                )
                if is_stalled:
                    stalled.append(t)

            if not stalled:
                return {"removed": 0, "hashes": []}

            hashes = [t["hash"] for t in stalled]
            hash_str = "|".join(hashes)
            await hc.post(f"{base}/api/v2/torrents/delete",
                data={"hashes": hash_str, "deleteFiles": "false"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"qBittorrent error: {e}")

    # Blocklist hashes and re-queue linked tracks
    db = await get_db()
    try:
        for t in stalled:
            h = t.get("hash","")
            name = t.get("name","")
            if h:
                await db.execute(
                    "INSERT OR IGNORE INTO blocklist (type, value, title, reason, source, added_at) VALUES ('hash', ?, ?, 'Stalled torrent auto-blocklisted', 'qbittorrent', CURRENT_TIMESTAMP)",
                    (h, name),
                )
            # Try to find unified_download by source_url containing hash
            if h:
                cur = await db.execute(
                    "SELECT id, monitored_track_id FROM unified_downloads WHERE source_url LIKE ? AND status IN ('queued','downloading')",
                    (f"%{h}%",),
                )
                for ud in await cur.fetchall():
                    await db.execute(
                        "UPDATE unified_downloads SET status='cancelled', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (ud["id"],),
                    )
                    if ud["monitored_track_id"]:
                        await db.execute(
                            "UPDATE monitored_tracks SET status='wanted', updated_at=CURRENT_TIMESTAMP WHERE id=? AND status IN ('downloading','wanted')",
                            (ud["monitored_track_id"],),
                        )
        await db.commit()
    finally:
        await db.close()

    return {"removed": len(stalled), "hashes": hashes}


@app.delete("/downloads/{download_id}")
async def download_dismiss(download_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM downloads WHERE id = ?", (download_id,))
        await db.commit()
        return {"status": "deleted"}
    finally:
        await db.close()


@app.post("/downloads/clear-completed")
async def downloads_clear_completed():
    """Delete all completed and cancelled download records."""
    db = await get_db()
    try:
        cur = await db.execute(
            "DELETE FROM downloads WHERE status IN ('completed', 'cancelled')"
        )
        c1 = cur.rowcount
        cur = await db.execute(
            "DELETE FROM unified_downloads WHERE status IN ('completed', 'cancelled')"
        )
        c2 = cur.rowcount
        await db.commit()
        return {"deleted": c1 + c2}
    finally:
        await db.close()


@app.post("/downloads/clear-failed")
async def downloads_clear_failed():
    """Delete all failed download records and reset monitored_tracks back to 'wanted'."""
    db = await get_db()
    try:
        # Reset monitored_tracks linked to failed unified_downloads
        cur = await db.execute(
            """SELECT monitored_track_id FROM unified_downloads
               WHERE status = 'failed' AND monitored_track_id IS NOT NULL"""
        )
        track_ids = [r[0] for r in await cur.fetchall()]
        for tid in track_ids:
            await db.execute(
                "UPDATE monitored_tracks SET status='wanted', updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='downloading'",
                (tid,),
            )
        cur = await db.execute("DELETE FROM downloads WHERE status = 'failed'")
        c1 = cur.rowcount
        cur = await db.execute("DELETE FROM unified_downloads WHERE status = 'failed'")
        c2 = cur.rowcount
        await db.commit()
        return {"deleted": c1 + c2, "tracks_reset": len(track_ids)}
    finally:
        await db.close()


# ─── Auto-Sync ──────────────────────────────────────────────────────

@app.get("/sync/items")
async def sync_items_list():
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM sync_items ORDER BY name")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


@app.post("/sync/items")
async def sync_item_create(item: SyncItemCreate):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO sync_items (spotify_id, item_type, name) VALUES (?, ?, ?)",
            (item.spotify_id, item.item_type, item.name),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM sync_items WHERE spotify_id = ?", (item.spotify_id,))
        row = await cur.fetchone()
        return dict(row)
    finally:
        await db.close()


@app.delete("/sync/items/{item_id}")
async def sync_item_delete(item_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM sync_items WHERE id = ?", (item_id,))
        await db.commit()
        return {"status": "deleted"}
    finally:
        await db.close()


@app.put("/sync/items/{item_id}")
async def sync_item_update(item_id: int, update: SyncItemUpdate):
    db = await get_db()
    try:
        if update.enabled is not None:
            await db.execute(
                "UPDATE sync_items SET enabled = ? WHERE id = ?",
                (1 if update.enabled else 0, item_id),
            )
            await db.commit()
        cur = await db.execute("SELECT * FROM sync_items WHERE id = ?", (item_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Sync item not found")
        return dict(row)
    finally:
        await db.close()


@app.post("/sync/account-sync")
async def sync_account_sync_now():
    from tasks import refresh_sync_items_from_spotify
    from spotify_client import get_client
    sp = await get_client()
    if not sp:
        raise HTTPException(400, "Spotify not connected")
    added = await refresh_sync_items_from_spotify(sp)
    return {"status": "ok", "items_added": added}


@app.get("/sync/progress")
async def sync_progress():
    from tasks import get_sync_progress
    return get_sync_progress()


@app.get("/downloads/dispatch-progress")
async def dispatch_progress():
    from tasks import get_dispatch_progress
    return get_dispatch_progress()


@app.post("/sync/run")
async def sync_run_now():
    from tasks import run_playlist_sync
    import asyncio
    asyncio.create_task(run_playlist_sync())
    return {"status": "started"}


@app.post("/sync/items/{item_id}/sync")
async def sync_item_now(item_id: int):
    """Generate M3U for a specific sync item and push to Jellyfin."""
    db = await get_db()
    try:
        cur = await db.execute("SELECT spotify_id, name, item_type FROM sync_items WHERE id = ?", (item_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Sync item not found")
        item_type = row["item_type"]
        playlist_id = row["spotify_id"]
        playlist_name = row["name"]
    finally:
        await db.close()

    from m3u import _trigger_jellyfin_scan

    if item_type == "soundcloud":
        from m3u import generate_m3u_for_soundcloud
        path, matched, total = await generate_m3u_for_soundcloud(item_id)
        if path:
            await _trigger_jellyfin_scan()
            db2 = await get_db()
            try:
                await db2.execute(
                    "UPDATE sync_items SET last_synced_at=CURRENT_TIMESTAMP WHERE id=?", (item_id,)
                )
                await db2.commit()
            finally:
                await db2.close()
            return {"status": "ok", "path": path, "matched": matched, "total": total}
        return {"status": "no_tracks", "path": None, "matched": 0, "total": 0,
                "detail": "Playlist folder not found or empty — download it first on the SoundCloud page."}

    from m3u import generate_m3u_for_playlist
    path, matched, total = await generate_m3u_for_playlist(playlist_id, playlist_name)
    if path:
        await _trigger_jellyfin_scan()
        return {"status": "ok", "path": path, "matched": matched, "total": total}
    return {"status": "no_tracks_matched", "path": None, "matched": matched, "total": total}


@app.post("/sync/download-missing")
async def sync_download_missing_all():
    from tasks import download_missing_all
    import asyncio
    asyncio.create_task(download_missing_all())
    return {"status": "started"}


@app.post("/sync/items/{item_id}/download-missing")
async def sync_download_missing_item(item_id: int):
    from tasks import download_missing_for_playlist
    db = await get_db()
    try:
        cur = await db.execute("SELECT spotify_id, name FROM sync_items WHERE id = ?", (item_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Sync item not found")
        spotify_id = row["spotify_id"]
        name = row["name"]
    finally:
        await db.close()

    import asyncio
    async def _run():
        dispatched = await download_missing_for_playlist(spotify_id)
        if dispatched:
            from database import add_notification
            await add_notification("downloads_started", f"Downloads for '{name}'",
                f"Dispatched {dispatched} downloads")

    asyncio.create_task(_run())
    return {"status": "started"}


@app.get("/sync/status")
async def sync_status():
    from scheduler import get_sync_status
    return await get_sync_status()


# ─── SoundCloud ──────────────────────────────────────────────────────

class SoundCloudImportRequest(_BaseModel):
    url: str

@app.post("/soundcloud/import")
async def soundcloud_import(body: SoundCloudImportRequest):
    """Import a SoundCloud playlist/artist URL, fetching metadata and creating a sync item."""
    url = body.url.strip()
    if not url:
        raise HTTPException(400, "URL is required")
    if "soundcloud.com" not in url:
        raise HTTPException(400, "Must be a SoundCloud URL")

    from soundcloud import fetch_soundcloud_playlist
    try:
        playlist = await fetch_soundcloud_playlist(url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch playlist: {e}")

    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO sync_items (spotify_id, item_type, name, track_count, enabled)
               VALUES (?, 'soundcloud', ?, ?, 1)
               ON CONFLICT(spotify_id) DO UPDATE SET
                 name=excluded.name, track_count=excluded.track_count""",
            (url, playlist["name"], playlist["track_count"]),
        )
        await db.commit()
        cur = await db.execute("SELECT id FROM sync_items WHERE spotify_id=?", (url,))
        row = await cur.fetchone()
        return {"ok": True, "id": row["id"], "name": playlist["name"], "track_count": playlist["track_count"]}
    finally:
        await db.close()


@app.post("/soundcloud/profile-scan")
async def soundcloud_profile_scan(body: SoundCloudImportRequest):
    """Scan a SoundCloud profile URL and return its public playlists."""
    url = body.url.strip()
    if not url or "soundcloud.com" not in url:
        raise HTTPException(400, "Must be a SoundCloud profile URL")
    from soundcloud import scan_profile_playlists
    try:
        playlists = await scan_profile_playlists(url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Scan failed: {e}")
    return {"playlists": playlists}


@app.get("/soundcloud/downloads")
async def soundcloud_downloads():
    """Return live download status for all active SoundCloud downloads."""
    from soundcloud import get_sc_downloads
    return get_sc_downloads()


@app.get("/soundcloud/local-counts")
async def soundcloud_local_counts():
    """Return how many local audio files exist for each imported SC playlist."""
    import re as _re
    from pathlib import Path as _Path
    music_path = await get_setting("music_path", "/music")
    audio_exts = {".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".wav"}

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, name FROM sync_items WHERE item_type='soundcloud'"
        )
        rows = await cur.fetchall()
    finally:
        await db.close()

    result = {}
    for r in rows:
        safe_name = _re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", r["name"]).strip()
        sc_dir = os.path.join(music_path, "SoundCloud", safe_name)
        if os.path.isdir(sc_dir):
            count = sum(
                1 for p in _Path(sc_dir).iterdir()
                if p.is_file() and p.suffix.lower() in audio_exts
            )
        else:
            count = -1  # -1 = folder doesn't exist (not downloaded)
        result[str(r["id"])] = count
    return result


@app.post("/soundcloud/sync/{sync_id}")
async def soundcloud_sync(sync_id: int):
    """Start downloading a SoundCloud playlist via yt-dlp in the background."""
    from soundcloud import download_soundcloud_playlist
    import asyncio as _asyncio
    _asyncio.create_task(download_soundcloud_playlist(sync_id))
    return {"ok": True, "sync_id": sync_id}


@app.delete("/soundcloud/sync/{sync_id}")
async def soundcloud_remove(sync_id: int):
    """Remove a SoundCloud sync item."""
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM sync_items WHERE id=? AND item_type='soundcloud'", (sync_id,)
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


# ─── Library ────────────────────────────────────────────────────────

@app.get("/library/tracks")
async def library_tracks(
    q: str = "",
    offset: int = 0,
    limit: int = 50,
    sort: str = "artist",
    order: str = "asc",
):
    db = await get_db()
    try:
        allowed_sorts = {"artist", "title", "album", "year", "format", "bitrate", "created_at", "size"}
        if sort not in allowed_sorts:
            sort = "artist"
        direction = "DESC" if order == "desc" else "ASC"

        if q:
            cur = await db.execute(
                f"SELECT * FROM tracks WHERE artist LIKE ? OR title LIKE ? OR album LIKE ? "
                f"ORDER BY {sort} {direction} LIMIT ? OFFSET ?",
                (f"%{q}%", f"%{q}%", f"%{q}%", limit, offset),
            )
        else:
            cur = await db.execute(
                f"SELECT * FROM tracks ORDER BY {sort} {direction} LIMIT ? OFFSET ?",
                (limit, offset),
            )
        rows = await cur.fetchall()

        # Get total count
        if q:
            cur = await db.execute(
                "SELECT COUNT(*) as c FROM tracks WHERE artist LIKE ? OR title LIKE ? OR album LIKE ?",
                (f"%{q}%", f"%{q}%", f"%{q}%"),
            )
        else:
            cur = await db.execute("SELECT COUNT(*) as c FROM tracks")
        total = (await cur.fetchone())["c"]

        return {"tracks": [dict(r) for r in rows], "total": total, "offset": offset, "limit": limit}
    finally:
        await db.close()


@app.delete("/library/tracks/{track_id}")
async def library_delete_track(track_id: int):
    import aiofiles.os
    db = await get_db()
    try:
        cur = await db.execute("SELECT path FROM tracks WHERE id = ?", (track_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Track not found")
        path = row["path"]
        try:
            await aiofiles.os.remove(path)
        except FileNotFoundError:
            pass
        await db.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
        await db.execute(
            "DELETE FROM duplicate_pairs WHERE track_a_id = ? OR track_b_id = ?",
            (track_id, track_id),
        )
        await db.commit()
        return {"status": "deleted", "path": path}
    finally:
        await db.close()


@app.post("/library/scan")
async def library_scan():
    from tasks import run_scan
    import asyncio
    asyncio.create_task(run_scan())
    return {"status": "started"}


@app.post("/release-check/trigger")
async def trigger_release_check():
    """Manually trigger a release check for all monitored artists."""
    import asyncio
    from tasks import run_release_check
    asyncio.create_task(run_release_check())
    return {"status": "started"}


@app.get("/library/scan/status")
async def library_scan_status():
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM scan_history ORDER BY id DESC LIMIT 1")
        row = await cur.fetchone()
        if not row:
            return ScanStatusOut()
        return ScanStatusOut(**dict(row))
    finally:
        await db.close()


@app.get("/library/scan/progress")
async def library_scan_progress():
    from scanner import scan_progress
    import time
    sp = scan_progress
    percent = 0.0
    eta = None
    if sp["total_files"] > 0 and sp["processed"] > 0:
        percent = round(sp["processed"] / sp["total_files"] * 100, 1)
        if sp["started_at"] and sp["phase"] == "indexing":
            from datetime import datetime
            started = datetime.fromisoformat(sp["started_at"])
            elapsed = (datetime.utcnow() - started).total_seconds()
            if sp["processed"] > 0:
                remaining = sp["total_files"] - sp["processed"]
                eta = round(elapsed * remaining / sp["processed"], 1)
    return ScanProgressOut(
        phase=sp["phase"],
        total_files=sp["total_files"],
        processed=sp["processed"],
        progress_percent=percent,
        eta_seconds=eta,
        started_at=sp["started_at"],
    )


@app.get("/library/hash/status")
async def library_hash_status():
    """Kept for backward compatibility — hashing has been removed."""
    return {"total": 0, "hashed": 0, "percent": 0.0, "running": False}


@app.get("/library/ready")
async def library_ready():
    from scanner import scan_progress
    ready = await get_setting("library_ready", "0") == "1"
    if ready:
        return {"ready": True, "reason": "", "phase": "ready"}

    # Figure out what's actually happening
    phase = scan_progress.get("phase", "idle")

    # Check if a scan is currently running in the DB
    db = await get_db()
    try:
        cur = await db.execute("SELECT status FROM scan_history ORDER BY id DESC LIMIT 1")
        row = await cur.fetchone()
        scan_running = row and row["status"] == "running" if row else False
        has_any_scan = row is not None
    finally:
        await db.close()

    if scan_running or phase not in ("idle", "complete"):
        if phase == "walking":
            reason = "Counting files in music library..."
            return {"ready": False, "reason": reason, "phase": "walking"}
        elif phase == "indexing":
            sp = scan_progress
            pct = round(sp["processed"] / sp["total_files"] * 100, 1) if sp["total_files"] > 0 else 0
            reason = f"Indexing tracks: {sp['processed']:,} / {sp['total_files']:,} ({pct}%) — downloads will start when complete"
            return {"ready": False, "reason": reason, "phase": "indexing"}
        elif phase == "dedup":
            reason = "Detecting duplicates — downloads will start when complete"
            return {"ready": False, "reason": reason, "phase": "dedup"}
        else:
            reason = "Library scan in progress — downloads will start when complete"
            return {"ready": False, "reason": reason, "phase": phase}
    elif not has_any_scan:
        reason = "Library has not been scanned yet — run a scan from the Dashboard to enable downloads"
        return {"ready": False, "reason": reason, "phase": "never_scanned"}
    else:
        # Previous scan exists but wasn't successful (interrupted/failed)
        reason = "Library scan incomplete — run a scan from the Dashboard to enable downloads"
        return {"ready": False, "reason": reason, "phase": "incomplete"}



# ─── Notifications ─────────────────────────────────────────────────

@app.get("/notifications")
async def notifications_list(unread: bool = False, limit: int = 30):
    db = await get_db()
    try:
        if unread:
            cur = await db.execute(
                "SELECT * FROM notifications WHERE read = 0 ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        else:
            cur = await db.execute(
                "SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


@app.post("/notifications/{notif_id}/read")
async def notification_mark_read(notif_id: int):
    db = await get_db()
    try:
        await db.execute("UPDATE notifications SET read = 1 WHERE id = ?", (notif_id,))
        await db.commit()
        return {"status": "ok"}
    finally:
        await db.close()


@app.post("/notifications/read-all")
async def notifications_read_all():
    db = await get_db()
    try:
        await db.execute("UPDATE notifications SET read = 1 WHERE read = 0")
        await db.commit()
        return {"status": "ok"}
    finally:
        await db.close()


# ─── Activity Log ──────────────────────────────────────────────────

@app.get("/youtube/search")
async def youtube_search(artist: str = "", title: str = "", duration_ms: int = 0):
    """Search YouTube for a track and return scored candidates."""
    from yt_search import search_track
    if not artist or not title:
        raise HTTPException(400, "artist and title are required")
    results = await search_track(artist, title, duration_ms)
    return {"results": results}


@app.get("/youtube/review-queue")
async def youtube_review_queue_list(limit: int = 50, offset: int = 0):
    """List pending YouTube review items."""
    from yt_search import get_review_queue
    items = await get_review_queue(limit, offset)
    return {"items": items, "total": len(items)}


@app.post("/youtube/review-queue/{item_id}/accept")
async def youtube_review_accept(item_id: int):
    """Accept a YouTube candidate and queue it to MeTube."""
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM youtube_review_queue WHERE id=?", (item_id,))
        item = await cur.fetchone()
        if not item:
            raise HTTPException(404, "Review item not found")
        item = dict(item)
        # Queue to MeTube
        metube_url = await get_setting("metube_url", "http://metube:8081")
        audio_format = await get_setting("youtube_audio_format", "mp3")
        import httpx as _httpx
        try:
            async with _httpx.AsyncClient(timeout=30) as client:
                await client.post(f"{metube_url}/add", json={
                    "url": item["video_url"],
                    "quality": "audio",
                    "format": audio_format,
                })
        except Exception as e:
            raise HTTPException(502, f"MeTube unreachable: {e}")
        # Mark reviewed + accepted
        await db.execute(
            "UPDATE youtube_review_queue SET reviewed=1, accepted=1 WHERE id=?",
            (item_id,)
        )
        if item.get("monitored_track_id"):
            await db.execute(
                "UPDATE monitored_tracks SET status='downloading' WHERE id=?",
                (item["monitored_track_id"],)
            )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@app.post("/youtube/review-queue/{item_id}/reject")
async def youtube_review_reject(item_id: int):
    """Reject a YouTube candidate."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE youtube_review_queue SET reviewed=1, accepted=0 WHERE id=?",
            (item_id,)
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@app.get("/calendar/releases")
async def calendar_releases(year: int = 2026, month: int = 1):
    """Return monitored album releases for a given month + 2 weeks on each side."""
    from datetime import date
    import calendar as cal_mod
    # Window: from start of prev month to end of next month for context dots
    first_day = date(year, month, 1)
    last_day  = date(year, month, cal_mod.monthrange(year, month)[1])
    # Expand window by 1 month each side for "upcoming/recent" panels
    if month == 1:
        prev_month_start = date(year - 1, 12, 1)
    else:
        prev_month_start = date(year, month - 1, 1)
    if month == 12:
        next_month_end = date(year + 1, 1, cal_mod.monthrange(year + 1, 1)[1])
    else:
        next_month_end = date(year, month + 1, cal_mod.monthrange(year, month + 1)[1])

    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT alb.*, a.name AS artist_name, a.image_url AS artist_image
               FROM monitored_albums alb
               LEFT JOIN monitored_artists a ON a.id = alb.artist_id
               WHERE alb.release_date BETWEEN ? AND ?
                 AND alb.monitored = 1
               ORDER BY alb.release_date ASC""",
            (prev_month_start.isoformat(), next_month_end.isoformat())
        )
        rows = [dict(r) for r in await cur.fetchall()]
        return {
            "year": year,
            "month": month,
            "releases": rows,
            "window_start": prev_month_start.isoformat(),
            "window_end": next_month_end.isoformat(),
        }
    finally:
        await db.close()


@app.get("/activity")
async def activity_list(limit: int = 50):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


@app.get("/logs")
async def get_logs(limit: int = 100, offset: int = 0, level: str = "all"):
    db = await get_db()
    try:
        if level and level != "all":
            cur = await db.execute(
                "SELECT * FROM activity_log WHERE action=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (level, limit, offset)
            )
            rows = await cur.fetchall()
            cur2 = await db.execute(
                "SELECT COUNT(*) as n FROM activity_log WHERE action=?", (level,)
            )
            total_row = await cur2.fetchone()
        else:
            cur = await db.execute(
                "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            )
            rows = await cur.fetchall()
            cur2 = await db.execute("SELECT COUNT(*) as n FROM activity_log")
            total_row = await cur2.fetchone()
        total = total_row["n"] if total_row else 0
        return {"logs": [dict(r) for r in rows], "total": total}
    finally:
        await db.close()


@app.delete("/logs")
async def clear_logs():
    db = await get_db()
    try:
        await db.execute("DELETE FROM activity_log")
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@app.post("/sync/run-now")
async def sync_run_now_alias():
    from tasks import run_auto_sync
    import asyncio
    asyncio.create_task(run_auto_sync())
    return {"ok": True}


# ─── Failed Imports ────────────────────────────────────────────────

@app.get("/library/failed-imports")
async def failed_imports_stats():
    from tasks import get_failed_imports_stats
    return await get_failed_imports_stats()


@app.post("/library/failed-imports/clean")
async def failed_imports_clean():
    """Delete all files in the failed_imports folder."""
    import shutil
    music_path = await get_setting("music_path", MUSIC_PATH)
    failed_dir = os.path.join(music_path, "failed_imports")
    if not os.path.isdir(failed_dir):
        return {"cleaned": 0, "size_gb": 0}

    from tasks import get_failed_imports_stats
    stats = await get_failed_imports_stats()

    shutil.rmtree(failed_dir, ignore_errors=True)

    from database import add_notification, add_activity
    await add_notification("cleanup", "Failed imports purged",
        f"Removed {stats['file_count']} files ({stats['size_gb']} GB)")
    await add_activity("failed_imports_purged",
        f"Removed {stats['file_count']} files ({stats['size_gb']} GB)")

    return {"cleaned": stats["file_count"], "size_gb": stats["size_gb"]}


# ─── Duplicates ─────────────────────────────────────────────────────

@app.get("/duplicates")
async def duplicates_list(offset: int = 0, limit: int = 20):
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT dp.*,
               ta.path as a_path, ta.artist as a_artist, ta.title as a_title, ta.album as a_album,
               ta.format as a_format, ta.bitrate as a_bitrate, ta.size as a_size, ta.duration as a_duration,
               ta.track_number as a_track_number, ta.year as a_year, ta.sha256 as a_sha256,
               tb.path as b_path, tb.artist as b_artist, tb.title as b_title, tb.album as b_album,
               tb.format as b_format, tb.bitrate as b_bitrate, tb.size as b_size, tb.duration as b_duration,
               tb.track_number as b_track_number, tb.year as b_year, tb.sha256 as b_sha256
               FROM duplicate_pairs dp
               JOIN tracks ta ON dp.track_a_id = ta.id
               JOIN tracks tb ON dp.track_b_id = tb.id
               WHERE dp.status = 'pending'
               ORDER BY dp.similarity_score DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        )
        rows = await cur.fetchall()
        pairs = []
        for r in rows:
            r = dict(r)
            pairs.append({
                "id": r["id"],
                "match_type": r["match_type"],
                "similarity_score": r["similarity_score"],
                "status": r["status"],
                "track_a": {
                    "id": r["track_a_id"], "path": r["a_path"], "artist": r["a_artist"],
                    "title": r["a_title"], "album": r["a_album"], "format": r["a_format"],
                    "bitrate": r["a_bitrate"], "size": r["a_size"], "duration": r["a_duration"],
                    "track_number": r["a_track_number"], "year": r["a_year"], "sha256": r["a_sha256"],
                },
                "track_b": {
                    "id": r["track_b_id"], "path": r["b_path"], "artist": r["b_artist"],
                    "title": r["b_title"], "album": r["b_album"], "format": r["b_format"],
                    "bitrate": r["b_bitrate"], "size": r["b_size"], "duration": r["b_duration"],
                    "track_number": r["b_track_number"], "year": r["b_year"], "sha256": r["b_sha256"],
                },
            })

        cur = await db.execute("SELECT COUNT(*) as c FROM duplicate_pairs WHERE status = 'pending'")
        total = (await cur.fetchone())["c"]
        return {"pairs": pairs, "total": total, "offset": offset, "limit": limit}
    finally:
        await db.close()


@app.get("/duplicates/stats")
async def duplicates_stats():
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT status, COUNT(*) as c FROM duplicate_pairs GROUP BY status"
        )
        rows = await cur.fetchall()
        stats = {r["status"]: r["c"] for r in rows}
        return stats
    finally:
        await db.close()


@app.post("/duplicates/{pair_id}/resolve")
async def duplicate_resolve(pair_id: int, body: DuplicateResolve):
    import aiofiles.os
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT dp.*, ta.path as a_path, ta.id as a_id, ta.bitrate as a_bitrate,
               tb.path as b_path, tb.id as b_id, tb.bitrate as b_bitrate
               FROM duplicate_pairs dp
               JOIN tracks ta ON dp.track_a_id = ta.id
               JOIN tracks tb ON dp.track_b_id = tb.id
               WHERE dp.id = ?""",
            (pair_id,),
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Duplicate pair not found")
        row = dict(row)

        delete_track_id = None
        delete_path = None

        if body.action == "keep_a":
            delete_track_id = row["b_id"]
            delete_path = row["b_path"]
        elif body.action == "keep_b":
            delete_track_id = row["a_id"]
            delete_path = row["a_path"]
        elif body.action in ("keep_both", "skip"):
            pass
        else:
            raise HTTPException(400, f"Invalid action: {body.action}")

        if delete_path:
            try:
                await aiofiles.os.remove(delete_path)
            except FileNotFoundError:
                pass
            await db.execute("DELETE FROM tracks WHERE id = ?", (delete_track_id,))
            await db.execute(
                "DELETE FROM duplicate_pairs WHERE (track_a_id = ? OR track_b_id = ?) AND id != ?",
                (delete_track_id, delete_track_id, pair_id),
            )

        await db.execute(
            "UPDATE duplicate_pairs SET status = 'resolved', resolution = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
            (body.action, pair_id),
        )
        await db.commit()
        return {"status": "resolved", "action": body.action}
    finally:
        await db.close()


@app.post("/duplicates/auto-resolve")
async def duplicates_auto_resolve():
    import aiofiles.os
    db = await get_db()
    try:
        await db.execute("PRAGMA busy_timeout = 10000")
        cur = await db.execute(
            """SELECT dp.id, ta.id as a_id, ta.path as a_path, ta.bitrate as a_bitrate, ta.size as a_size,
               tb.id as b_id, tb.path as b_path, tb.bitrate as b_bitrate, tb.size as b_size
               FROM duplicate_pairs dp
               JOIN tracks ta ON dp.track_a_id = ta.id
               JOIN tracks tb ON dp.track_b_id = tb.id
               WHERE dp.status = 'pending' AND dp.similarity_score >= 95"""
        )
        rows = [dict(r) for r in await cur.fetchall()]
        resolved = 0
        deleted_track_ids = set()
        for r in rows:
            # Skip if either track was already deleted by a prior pair in this batch
            if r["a_id"] in deleted_track_ids or r["b_id"] in deleted_track_ids:
                await db.execute(
                    "UPDATE duplicate_pairs SET status = 'resolved', resolution = 'skip', resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (r["id"],),
                )
                resolved += 1
                continue

            # Keep higher bitrate, or larger file
            a_score = (r["a_bitrate"] or 0) * 1000 + (r["a_size"] or 0)
            b_score = (r["b_bitrate"] or 0) * 1000 + (r["b_size"] or 0)
            if a_score >= b_score:
                keep, delete_id, delete_path = "keep_a", r["b_id"], r["b_path"]
            else:
                keep, delete_id, delete_path = "keep_b", r["a_id"], r["a_path"]

            try:
                await aiofiles.os.remove(delete_path)
            except FileNotFoundError:
                pass
            deleted_track_ids.add(delete_id)
            await db.execute("DELETE FROM tracks WHERE id = ?", (delete_id,))
            await db.execute(
                "DELETE FROM duplicate_pairs WHERE (track_a_id = ? OR track_b_id = ?) AND id != ? AND status = 'pending'",
                (delete_id, delete_id, r["id"]),
            )
            await db.execute(
                "UPDATE duplicate_pairs SET status = 'resolved', resolution = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
                (keep, r["id"]),
            )
            resolved += 1

            # Batch commit every 50 to avoid holding the lock too long
            if resolved % 50 == 0:
                await db.commit()

        await db.commit()
        return {"resolved": resolved}
    finally:
        await db.close()


@app.post("/duplicates/resolve-all")
async def duplicates_resolve_all():
    """Resolve ALL pending duplicate pairs, keeping the higher-quality version."""
    import aiofiles.os
    db = await get_db()
    try:
        await db.execute("PRAGMA busy_timeout = 10000")
        cur = await db.execute(
            """SELECT dp.id, ta.id as a_id, ta.path as a_path, ta.bitrate as a_bitrate, ta.size as a_size,
               tb.id as b_id, tb.path as b_path, tb.bitrate as b_bitrate, tb.size as b_size
               FROM duplicate_pairs dp
               JOIN tracks ta ON dp.track_a_id = ta.id
               JOIN tracks tb ON dp.track_b_id = tb.id
               WHERE dp.status = 'pending'"""
        )
        rows = [dict(r) for r in await cur.fetchall()]
        resolved = 0
        deleted_track_ids = set()
        for r in rows:
            if r["a_id"] in deleted_track_ids or r["b_id"] in deleted_track_ids:
                await db.execute(
                    "UPDATE duplicate_pairs SET status = 'resolved', resolution = 'skip', resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (r["id"],),
                )
                resolved += 1
                continue

            a_score = (r["a_bitrate"] or 0) * 1000 + (r["a_size"] or 0)
            b_score = (r["b_bitrate"] or 0) * 1000 + (r["b_size"] or 0)
            if a_score >= b_score:
                keep, delete_id, delete_path = "keep_a", r["b_id"], r["b_path"]
            else:
                keep, delete_id, delete_path = "keep_b", r["a_id"], r["a_path"]

            try:
                await aiofiles.os.remove(delete_path)
            except FileNotFoundError:
                pass
            deleted_track_ids.add(delete_id)
            await db.execute("DELETE FROM tracks WHERE id = ?", (delete_id,))
            await db.execute(
                "DELETE FROM duplicate_pairs WHERE (track_a_id = ? OR track_b_id = ?) AND id != ? AND status = 'pending'",
                (delete_id, delete_id, r["id"]),
            )
            await db.execute(
                "UPDATE duplicate_pairs SET status = 'resolved', resolution = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
                (keep, r["id"]),
            )
            resolved += 1

            if resolved % 50 == 0:
                await db.commit()

        await db.commit()
        return {"resolved": resolved}
    finally:
        await db.close()


# ─── Settings ───────────────────────────────────────────────────────

@app.get("/settings", response_model=SettingsOut)
async def get_settings():
    db = await get_db()
    try:
        cur = await db.execute("SELECT access_token, scope FROM spotify_auth WHERE id = 1")
        sp_row = await cur.fetchone()

        client_id = await get_setting("spotify_client_id", "")
        client_secret = await get_setting("spotify_client_secret", "")
        redirect_uri = await get_setting("spotify_redirect_uri", "http://192.168.1.152:6160/api/spotify/callback")

        return SettingsOut(
            spotify_connected=sp_row is not None and sp_row["access_token"] is not None,
            spotify_scopes=sp_row["scope"] if sp_row else None,
            spotify_client_id=client_id,
            spotify_client_secret_set=bool(client_secret),
            spotify_redirect_uri=redirect_uri,
            spotizerr_url=SPOTIZERR_URL,
            sync_interval_minutes=int(await get_setting("sync_interval_minutes", "60")),
            fuzzy_threshold=int(await get_setting("fuzzy_threshold", "85")),
            m3u_path_prefix=await get_setting("m3u_path_prefix", "/mnt/storage/MUSIC"),
            scan_interval_hours=int(await get_setting("scan_interval_hours", "6")),
            account_sync_enabled=await get_setting("account_sync_enabled", "0") == "1",
            music_path=await get_setting("music_path", MUSIC_PATH),
            jellyfin_url=await get_setting("jellyfin_url", ""),
            jellyfin_api_key=await get_setting("jellyfin_api_key", ""),
            metube_url=await get_setting("metube_url", "http://metube:8081"),
            youtube_audio_format=await get_setting("youtube_audio_format", "mp3"),
            youtube_audio_quality=await get_setting("youtube_audio_quality", "0"),
            match_review_threshold=int(await get_setting("match_review_threshold", "75")),
            spotizerr_concurrent_limit=int(await get_setting("spotizerr_concurrent_limit", "20")),
            dispatch_batch_size=int(await get_setting("dispatch_batch_size", "10")),
            youtube_api_key_set=bool(await get_setting("youtube_api_key", "")),
            youtube_fallback_enabled=await get_setting("youtube_fallback_enabled", "0") == "1",
            youtube_auto_threshold=int(await get_setting("youtube_auto_threshold", "85")),
            calendar_enabled=await get_setting("calendar_enabled", "0") == "1",
            slsk_album_download=await get_setting("slsk_album_download", "1") == "1",
            download_source_priority=await get_setting(
                "download_source_priority",
                '["torrent","usenet","soulseek","youtube","spotizerr"]',
            ),
            youtube_search_mode=await get_setting("youtube_search_mode", "studio"),
            discord_webhook_url=await get_setting("discord_webhook_url", ""),
            discord_notify_download_complete=await get_setting("discord_notify_download_complete", "1") == "1",
            discord_notify_new_release=await get_setting("discord_notify_new_release", "1") == "1",
            discord_notify_dispatch=await get_setting("discord_notify_dispatch", "0") == "1",
            queue_paused=await get_setting("queue_paused", "0") == "1",
            torrent_save_path=await get_setting("torrent_save_path", ""),
            torrent_hardlink_enabled=await get_setting("torrent_hardlink_enabled", "0") == "1",
        )
    finally:
        await db.close()


@app.put("/settings")
async def update_settings(update: SettingsUpdate):
    if update.spotify_client_id is not None:
        await set_setting("spotify_client_id", update.spotify_client_id)
    if update.spotify_client_secret is not None:
        await set_setting("spotify_client_secret", update.spotify_client_secret)
    if update.spotify_redirect_uri is not None:
        await set_setting("spotify_redirect_uri", update.spotify_redirect_uri)
    if update.sync_interval_minutes is not None:
        await set_setting("sync_interval_minutes", str(update.sync_interval_minutes))
    if update.fuzzy_threshold is not None:
        await set_setting("fuzzy_threshold", str(update.fuzzy_threshold))
    if update.m3u_path_prefix is not None:
        await set_setting("m3u_path_prefix", update.m3u_path_prefix)
    if update.scan_interval_hours is not None:
        await set_setting("scan_interval_hours", str(update.scan_interval_hours))
    if update.account_sync_enabled is not None:
        await set_setting("account_sync_enabled", "1" if update.account_sync_enabled else "0")
    if update.music_path is not None:
        await set_setting("music_path", update.music_path.strip())
    if update.jellyfin_url is not None:
        await set_setting("jellyfin_url", update.jellyfin_url.strip().rstrip("/"))
    if update.jellyfin_api_key is not None:
        await set_setting("jellyfin_api_key", update.jellyfin_api_key.strip())
    if update.metube_url is not None:
        await set_setting("metube_url", update.metube_url.strip().rstrip("/"))
    if update.youtube_audio_format is not None:
        await set_setting("youtube_audio_format", update.youtube_audio_format)
    if update.youtube_audio_quality is not None:
        await set_setting("youtube_audio_quality", update.youtube_audio_quality)
    if update.match_review_threshold is not None:
        await set_setting("match_review_threshold", str(update.match_review_threshold))
    if update.spotizerr_concurrent_limit is not None:
        await set_setting("spotizerr_concurrent_limit", str(update.spotizerr_concurrent_limit))
    if update.dispatch_batch_size is not None:
        await set_setting("dispatch_batch_size", str(update.dispatch_batch_size))
    if update.youtube_api_key is not None:
        await set_setting("youtube_api_key", update.youtube_api_key.strip())
    if update.youtube_fallback_enabled is not None:
        await set_setting("youtube_fallback_enabled", "1" if update.youtube_fallback_enabled else "0")
    if update.youtube_auto_threshold is not None:
        await set_setting("youtube_auto_threshold", str(update.youtube_auto_threshold))
    if update.calendar_enabled is not None:
        await set_setting("calendar_enabled", "1" if update.calendar_enabled else "0")
    if update.slsk_album_download is not None:
        await set_setting("slsk_album_download", "1" if update.slsk_album_download else "0")
    if update.download_source_priority is not None:
        await set_setting("download_source_priority", update.download_source_priority)
    if update.youtube_search_mode is not None:
        await set_setting("youtube_search_mode", update.youtube_search_mode)
    if update.discord_webhook_url is not None:
        await set_setting("discord_webhook_url", update.discord_webhook_url.strip())
    if update.discord_notify_download_complete is not None:
        await set_setting("discord_notify_download_complete", "1" if update.discord_notify_download_complete else "0")
    if update.discord_notify_new_release is not None:
        await set_setting("discord_notify_new_release", "1" if update.discord_notify_new_release else "0")
    if update.discord_notify_dispatch is not None:
        await set_setting("discord_notify_dispatch", "1" if update.discord_notify_dispatch else "0")
    if update.torrent_save_path is not None:
        await set_setting("torrent_save_path", update.torrent_save_path.strip())
    if update.torrent_hardlink_enabled is not None:
        await set_setting("torrent_hardlink_enabled", "1" if update.torrent_hardlink_enabled else "0")
    # Reschedule if intervals changed
    from scheduler import reschedule_jobs
    await reschedule_jobs()
    return await get_settings()


# ─── Download Clients ─────────────────────────────────────────────────────────

@app.get("/download-clients")
async def get_download_clients():
    from download_clients import list_clients
    return await list_clients()


@app.post("/download-clients", status_code=201)
async def add_download_client(body: dict):
    from download_clients import create_client, SUPPORTED_TYPES
    if body.get("type") not in SUPPORTED_TYPES:
        raise HTTPException(400, f"Unsupported client type. Supported: {SUPPORTED_TYPES}")
    if not body.get("name"):
        raise HTTPException(400, "name is required")
    new_id = await create_client(body)
    from download_clients import list_clients
    clients = await list_clients()
    return next((c for c in clients if c["id"] == new_id), {"id": new_id})


@app.put("/download-clients/{client_id}")
async def update_download_client(client_id: int, body: dict):
    from download_clients import update_client, get_client
    existing = await get_client(client_id)
    if not existing:
        raise HTTPException(404, "Client not found")
    await update_client(client_id, body)
    from download_clients import list_clients
    clients = await list_clients()
    return next((c for c in clients if c["id"] == client_id), {})


@app.delete("/download-clients/{client_id}", status_code=204)
async def delete_download_client(client_id: int):
    from download_clients import delete_client, get_client
    if not await get_client(client_id):
        raise HTTPException(404, "Client not found")
    await delete_client(client_id)


@app.post("/download-clients/{client_id}/test")
async def test_download_client(client_id: int):
    from download_clients import test_client
    return await test_client(client_id)


@app.post("/download-clients/reorder")
async def reorder_download_clients(body: dict):
    from download_clients import reorder_clients
    ids = body.get("ids", [])
    if not ids:
        raise HTTPException(400, "ids array required")
    await reorder_clients(ids)
    from download_clients import list_clients
    return await list_clients()


# ─── Indexers ─────────────────────────────────────────────────────────────────

@app.get("/indexers")
async def get_indexers():
    from indexers import list_indexers
    return await list_indexers()


@app.post("/indexers", status_code=201)
async def add_indexer(body: dict):
    from indexers import create_indexer, SUPPORTED_TYPES
    if body.get("type") not in SUPPORTED_TYPES:
        raise HTTPException(400, f"Unsupported indexer type. Supported: {SUPPORTED_TYPES}")
    if not body.get("name"):
        raise HTTPException(400, "name is required")
    new_id = await create_indexer(body)
    from indexers import list_indexers
    idxs = await list_indexers()
    return next((i for i in idxs if i["id"] == new_id), {"id": new_id})


@app.put("/indexers/{indexer_id}")
async def update_indexer_endpoint(indexer_id: int, body: dict):
    from indexers import update_indexer, get_indexer
    if not await get_indexer(indexer_id):
        raise HTTPException(404, "Indexer not found")
    await update_indexer(indexer_id, body)
    from indexers import list_indexers
    idxs = await list_indexers()
    return next((i for i in idxs if i["id"] == indexer_id), {})


@app.delete("/indexers/{indexer_id}", status_code=204)
async def delete_indexer_endpoint(indexer_id: int):
    from indexers import delete_indexer, get_indexer
    if not await get_indexer(indexer_id):
        raise HTTPException(404, "Indexer not found")
    await delete_indexer(indexer_id)


@app.post("/indexers/{indexer_id}/test")
async def test_indexer_endpoint(indexer_id: int):
    from indexers import test_indexer
    return await test_indexer(indexer_id)


@app.post("/indexers/reorder")
async def reorder_indexers_endpoint(body: dict):
    from indexers import reorder_indexers
    ids = body.get("ids", [])
    if not ids:
        raise HTTPException(400, "ids array required")
    await reorder_indexers(ids)
    from indexers import list_indexers
    return await list_indexers()


# ─── Metadata Profiles ────────────────────────────────────────────────────────

@app.get("/metadata-profiles")
async def get_metadata_profiles():
    from metadata_profiles import list_profiles
    return await list_profiles()


@app.post("/metadata-profiles", status_code=201)
async def add_metadata_profile(body: dict):
    from metadata_profiles import create_profile
    if not body.get("name"):
        raise HTTPException(400, "name is required")
    new_id = await create_profile(body)
    from metadata_profiles import list_profiles
    profiles = await list_profiles()
    return next((p for p in profiles if p["id"] == new_id), {"id": new_id})


@app.put("/metadata-profiles/{profile_id}")
async def update_metadata_profile(profile_id: int, body: dict):
    from metadata_profiles import update_profile, get_profile
    if not await get_profile(profile_id):
        raise HTTPException(404, "Profile not found")
    await update_profile(profile_id, body)
    from metadata_profiles import list_profiles
    profiles = await list_profiles()
    return next((p for p in profiles if p["id"] == profile_id), {})


@app.delete("/metadata-profiles/{profile_id}", status_code=204)
async def delete_metadata_profile(profile_id: int):
    from metadata_profiles import delete_profile, get_profile
    if not await get_profile(profile_id):
        raise HTTPException(404, "Profile not found")
    await delete_profile(profile_id)


# ─── Release Profiles ─────────────────────────────────────────────────────────

@app.get("/release-profiles")
async def get_release_profiles():
    from release_profiles import list_profiles
    return await list_profiles()

@app.post("/release-profiles", status_code=201)
async def add_release_profile(body: dict):
    from release_profiles import create_profile
    if not body.get("name"):
        raise HTTPException(400, "name is required")
    new_id = await create_profile(body)
    from release_profiles import list_profiles
    profiles = await list_profiles()
    return next((p for p in profiles if p["id"] == new_id), {"id": new_id})

@app.put("/release-profiles/{profile_id}")
async def update_release_profile(profile_id: int, body: dict):
    from release_profiles import update_profile, get_profile
    if not await get_profile(profile_id):
        raise HTTPException(404, "Profile not found")
    await update_profile(profile_id, body)
    from release_profiles import list_profiles
    profiles = await list_profiles()
    return next((p for p in profiles if p["id"] == profile_id), {})

@app.delete("/release-profiles/{profile_id}", status_code=204)
async def delete_release_profile(profile_id: int):
    from release_profiles import delete_profile, get_profile
    if not await get_profile(profile_id):
        raise HTTPException(404, "Profile not found")
    await delete_profile(profile_id)


# ─── Download History ─────────────────────────────────────────────────────────

@app.get("/download-history")
async def get_download_history(status: str = None, limit: int = 50, offset: int = 0):
    db = await get_db()
    try:
        where = "WHERE status = ?" if status else ""
        params = [status, limit, offset] if status else [limit, offset]
        cur = await db.execute(
            f"SELECT * FROM download_history {where} ORDER BY imported_at DESC LIMIT ? OFFSET ?",
            params
        )
        rows = await cur.fetchall()
        cur2 = await db.execute(f"SELECT COUNT(*) FROM download_history {where}", [status] if status else [])
        total = (await cur2.fetchone())[0]
        return {"items": [dict(r) for r in rows], "total": total}
    finally:
        await db.close()


# ─── Library Unmatched ────────────────────────────────────────────────────────

@app.get("/library/unmatched")
async def library_unmatched(limit: int = 100, offset: int = 0):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, path, artist, title, album, format, bitrate FROM tracks WHERE spotify_id IS NULL OR spotify_id = '' ORDER BY artist, title LIMIT ? OFFSET ?",
            (limit, offset)
        )
        rows = await cur.fetchall()
        cur2 = await db.execute("SELECT COUNT(*) FROM tracks WHERE spotify_id IS NULL OR spotify_id = ''")
        total = (await cur2.fetchone())[0]
        return {"items": [dict(r) for r in rows], "total": total}
    finally:
        await db.close()


# ─── Search Endpoints ─────────────────────────────────────────────────────────

@app.get("/indexers/prowlarr-list")
async def get_prowlarr_indexers():
    """Fetch all indexers from the configured Prowlarr instance."""
    import httpx

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM indexers WHERE type = 'prowlarr' AND enabled = 1 LIMIT 1"
        )
        prowlarr = await cur.fetchone()
    finally:
        await db.close()

    if not prowlarr:
        return {"indexers": [], "error": "No Prowlarr indexer configured"}

    prowlarr = dict(prowlarr)
    url = prowlarr.get("url", "").rstrip("/")
    api_key = prowlarr.get("api_key", "")
    headers = {"X-Api-Key": api_key} if api_key else {}

    try:
        async with httpx.AsyncClient(timeout=10) as hc:
            resp = await hc.get(f"{url}/api/v1/indexer", headers=headers)
            if resp.status_code != 200:
                return {"indexers": [], "error": f"Prowlarr returned HTTP {resp.status_code}"}
            indexers = []
            for idx in resp.json():
                caps = idx.get("capabilities", {})
                cats = [c["name"] for c in caps.get("categories", [])]
                has_audio = any(
                    "audio" in c.lower() or "music" in c.lower() for c in cats
                )
                indexers.append({
                    "id": idx["id"],
                    "name": idx.get("name", ""),
                    "protocol": idx.get("protocol", "torrent"),
                    "enabled": idx.get("enable", True),
                    "privacy": idx.get("privacy", "public"),
                    "description": idx.get("description", ""),
                    "supports_search": idx.get("supportsSearch", True),
                    "supports_rss": idx.get("supportsRss", True),
                    "has_audio": has_audio,
                    "categories": cats[:6],
                })
            indexers.sort(key=lambda x: x["name"].lower())
            return {"indexers": indexers, "prowlarr_url": url, "total": len(indexers)}
    except Exception as e:
        return {"indexers": [], "error": str(e)}


@app.post("/indexers/prowlarr-test/{prowlarr_id}")
async def test_prowlarr_indexer(prowlarr_id: int):
    """Test a specific Prowlarr indexer by running a minimal search through it."""
    import httpx

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM indexers WHERE type = 'prowlarr' AND enabled = 1 LIMIT 1"
        )
        prowlarr = await cur.fetchone()
    finally:
        await db.close()

    if not prowlarr:
        return {"ok": False, "message": "No Prowlarr configured"}

    prowlarr = dict(prowlarr)
    url = prowlarr.get("url", "").rstrip("/")
    api_key = prowlarr.get("api_key", "")
    headers = {"X-Api-Key": api_key} if api_key else {}

    try:
        async with httpx.AsyncClient(timeout=20) as hc:
            resp = await hc.get(
                f"{url}/api/v1/search",
                params={"query": "music", "type": "search", "limit": 1,
                        "indexerIds": prowlarr_id},
                headers=headers,
            )
            if resp.status_code == 200:
                return {"ok": True, "message": "Indexer reachable and responding"}
            return {"ok": False, "message": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.get("/search/indexers")
async def search_indexers(q: str, artist: str = "", type: str = "track",
                          indexer_id: int = None):
    """Search configured Prowlarr/Torznab/Newznab indexers."""
    import httpx
    import xml.etree.ElementTree as _ET

    results = []
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM indexers WHERE enabled = 1")
        indexers = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()

    query = f"{artist} {q}".strip() if artist else q

    def _parse_torznab_xml(text: str, indexer_name: str, proto: str) -> list:
        ns = {"torznab": "http://torznab.com/schemas/2015/feed"}
        items = []
        try:
            root = _ET.fromstring(text)
            channel = root.find("channel")
            for item in (channel.findall("item") if channel is not None else []):
                def _txt(tag):
                    el = item.find(tag)
                    return el.text.strip() if el is not None and el.text else ""
                attrs = {el.get("name", ""): el.get("value", "")
                         for el in item.findall("torznab:attr", ns)}
                enc = item.find("enclosure")
                size = int(enc.get("length", "0")) if enc is not None else 0
                dl_url = _txt("link") or (enc.get("url", "") if enc is not None else "")
                items.append({
                    "title": _txt("title"),
                    "size": size or int(attrs.get("size", "0") or "0"),
                    "seeders": int(attrs.get("seeders", "0") or "0"),
                    "leechers": int(attrs.get("peers", "0") or "0"),
                    "download_url": dl_url,
                    "indexer": indexer_name,
                    "indexer_type": proto,
                    "age": _txt("pubDate"),
                })
        except Exception as e:
            log.debug(f"XML parse error: {e}")
        return items

    for indexer in indexers:
        iname = indexer.get("name", "Unknown")
        try:
            url = indexer.get("url", "").rstrip("/")
            api_key = indexer.get("api_key", "")
            itype = indexer.get("type", "torznab")

            if not url:
                continue

            # Prowlarr aggregates many indexers and can take 20-30s
            _timeout = 60 if itype == "prowlarr" else 15
            async with httpx.AsyncClient(timeout=_timeout) as client:
                if itype == "prowlarr":
                    # Prowlarr REST API — header auth, returns JSON array with protocol field
                    headers = {"X-Api-Key": api_key} if api_key else {}
                    params = {"query": query, "type": "search", "limit": 30}
                    if indexer_id is not None:
                        params["indexerIds"] = indexer_id
                    resp = await client.get(
                        f"{url}/api/v1/search",
                        params=params,
                        headers=headers,
                    )
                    if resp.status_code != 200:
                        log.debug(f"Prowlarr {iname}: HTTP {resp.status_code}")
                        continue
                    items = resp.json()
                    if not isinstance(items, list):
                        items = items.get("results", items.get("Results", []))
                    for item in items:
                        proto = (item.get("protocol") or "torrent").lower()
                        results.append({
                            "title": item.get("title") or item.get("Title", ""),
                            "size": item.get("size") or item.get("Size", 0),
                            "seeders": item.get("seeders") or item.get("Seeders", 0),
                            "leechers": item.get("leechers") or item.get("Leechers", 0),
                            "download_url": item.get("downloadUrl") or item.get("magnetUrl") or item.get("DownloadUrl") or "",
                            "indexer": iname,
                            "indexer_type": proto,
                            "age": item.get("publishDate") or item.get("PublishDate", ""),
                        })

                elif itype in ("torznab", "newznab"):
                    proto = "torrent" if itype == "torznab" else "usenet"
                    resp = await client.get(
                        url,
                        params={"t": "search", "q": query, "apikey": api_key,
                                "limit": "20", "o": "json"},
                    )
                    if resp.status_code != 200:
                        log.debug(f"{itype} {iname}: HTTP {resp.status_code}")
                        continue
                    ct = resp.headers.get("content-type", "")
                    if "json" in ct:
                        data = resp.json()
                        # Jackett/Prowlarr Torznab JSON: {"Results": [...]} PascalCase
                        items = data.get("Results", data if isinstance(data, list) else [])
                        for item in items:
                            results.append({
                                "title": item.get("Title") or item.get("title", ""),
                                "size": item.get("Size") or item.get("size", 0),
                                "seeders": item.get("Seeders") or item.get("seeders", 0),
                                "leechers": item.get("Peers") or item.get("peers", 0),
                                "download_url": item.get("Link") or item.get("link") or item.get("MagnetUri") or "",
                                "indexer": iname,
                                "indexer_type": proto,
                                "age": item.get("PublishDate") or item.get("publishDate", ""),
                            })
                    else:
                        # Standard Torznab/Newznab XML
                        results.extend(_parse_torznab_xml(resp.text, iname, proto))

        except Exception as e:
            log.debug(f"Indexer search error for {iname}: {e}")

    torrents = [r for r in results if r["indexer_type"] == "torrent"]
    usenet = [r for r in results if r["indexer_type"] == "usenet"]
    return {"torrents": torrents, "usenet": usenet, "query": query}


@app.post("/search/grab-torrent")
async def grab_torrent(body: dict):
    """Add a torrent URL or magnet to qBittorrent."""
    import httpx

    download_url = body.get("download_url", "")
    if not download_url:
        raise HTTPException(400, "download_url required")

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM download_clients WHERE type='qbittorrent' AND enabled=1 ORDER BY priority ASC LIMIT 1"
        )
        row = await cur.fetchone()
    finally:
        await db.close()

    if not row:
        raise HTTPException(503, "No qBittorrent client configured")

    row = dict(row)
    scheme = "https" if row.get("use_ssl") else "http"
    base = f"{scheme}://{row['host']}:{row['port']}{(row.get('url_base') or '').rstrip('/')}"

    try:
        async with httpx.AsyncClient(timeout=15) as hc:
            if row.get("username"):
                login = await hc.post(
                    f"{base}/api/v2/auth/login",
                    data={"username": row["username"], "password": row.get("password", "")},
                )
                if login.text.strip().lower() == "fails":
                    raise HTTPException(401, "qBittorrent authentication failed")
            resp = await hc.post(
                f"{base}/api/v2/torrents/add",
                data={"urls": download_url, "category": "music"},
            )
            if resp.status_code not in (200, 201) or resp.text.strip().lower() == "fails":
                raise HTTPException(502, f"qBittorrent rejected the torrent: {resp.text[:200]}")
        return {"ok": True, "message": "Torrent queued in qBittorrent"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e))


@app.post("/search/grab-usenet")
async def grab_usenet(body: dict):
    """Add an NZB URL to SABnzbd."""
    import httpx

    download_url = body.get("download_url", "")
    if not download_url:
        raise HTTPException(400, "download_url required")

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM download_clients WHERE type='sabnzbd' AND enabled=1 ORDER BY priority ASC LIMIT 1"
        )
        row = await cur.fetchone()
    finally:
        await db.close()

    if not row:
        raise HTTPException(503, "No SABnzbd client configured")

    row = dict(row)
    scheme = "https" if row.get("use_ssl") else "http"
    base = f"{scheme}://{row['host']}:{row['port']}{(row.get('url_base') or '').rstrip('/')}"

    try:
        async with httpx.AsyncClient(timeout=15) as hc:
            resp = await hc.get(
                f"{base}/api",
                params={
                    "mode": "addurl",
                    "name": download_url,
                    "apikey": row.get("api_key", ""),
                    "cat": "music",
                    "output": "json",
                },
            )
            if resp.status_code != 200:
                raise HTTPException(502, f"SABnzbd error: HTTP {resp.status_code}")
            data = resp.json()
            if not data.get("status"):
                raise HTTPException(502, f"SABnzbd rejected: {data}")
        return {"ok": True, "message": "NZB queued in SABnzbd"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e))


@app.get("/search/soulseek")
async def search_soulseek(q: str, artist: str = "", album: str = ""):
    """Search slskd for tracks and albums. Groups results by folder."""
    import httpx
    import asyncio as _asyncio

    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM download_clients WHERE type = 'slskd' AND enabled = 1 LIMIT 1")
        client_row = await cur.fetchone()
    finally:
        await db.close()

    if not client_row:
        return {"results": [], "folders": [], "error": "No slskd client configured"}

    client_row = dict(client_row)
    url = (client_row.get("url_base") or "").rstrip("/")
    if not url:
        host = client_row.get("host", "localhost")
        port = client_row.get("port", 5030)
        url = f"http://{host}:{port}"
    api_key = client_row.get("api_key", "")
    headers = {"X-API-Key": api_key} if api_key else {}

    track_query = f"{artist} {q}".strip() if artist else q
    album_query = f"{artist} {album}".strip() if album else None
    if album_query and album_query.lower() == track_query.lower():
        album_query = None

    _AUDIO_EXTS = {".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav", ".ape", ".wv", ".aac", ".alac"}

    def _is_audio(filename: str) -> bool:
        ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
        return ext in _AUDIO_EXTS

    def _folder_key(filename: str) -> str:
        parts = filename.replace("\\", "/").rstrip("/").split("/")
        return "/".join(parts[:-1]) if len(parts) > 1 else ""

    async def run_search(hc, query):
        try:
            resp = await hc.post(f"{url}/api/v0/searches",
                json={"searchText": query}, headers=headers)
            if resp.status_code not in (200, 201):
                return []
            search_id = resp.json().get("id")
            data = {}
            for _ in range(10):
                await _asyncio.sleep(1)
                r = await hc.get(f"{url}/api/v0/searches/{search_id}", headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("state") in ("Completed", "Finished"):
                        break
            return data.get("responses", []) or []
        except Exception:
            return []

    def process_responses(responses):
        """Group files by (username, folder). Returns (album_folders, solo_files)."""
        folders: dict = {}
        for resp_item in (responses or [])[:60]:
            username = resp_item.get("username", "")
            folder_map: dict = {}
            for f in (resp_item.get("files", []) or []):
                fname = f.get("filename", "")
                if not _is_audio(fname):
                    continue
                key = _folder_key(fname)
                folder_map.setdefault(key, []).append(f)
            for folder_path, flist in folder_map.items():
                fk = (username, folder_path)
                if fk not in folders:
                    fname_last = folder_path.replace("\\", "/").rstrip("/").split("/")[-1] if folder_path else username
                    folders[fk] = {
                        "username": username,
                        "folder": folder_path,
                        "folder_name": fname_last,
                        "files": [],
                        "total_size": 0,
                        "formats": set(),
                    }
                for f in flist:
                    ext = f.get("filename", "").rsplit(".", 1)[-1].upper() if "." in f.get("filename", "") else ""
                    folders[fk]["files"].append({
                        "filename": f.get("filename", ""),
                        "size": f.get("size", 0),
                        "bitrate": f.get("bitRate") or f.get("bitrate", 0),
                        "length": f.get("length", 0),
                    })
                    folders[fk]["total_size"] += f.get("size", 0)
                    if ext:
                        folders[fk]["formats"].add(ext)

        album_folders, solo_files = [], []
        for fd in folders.values():
            fd["formats"] = sorted(fd["formats"])
            fd["file_count"] = len(fd["files"])
            if fd["file_count"] >= 2:
                album_folders.append(fd)
            else:
                solo_files.append({**fd["files"][0], "username": fd["username"]})
        album_folders.sort(key=lambda x: x["file_count"], reverse=True)
        return album_folders, solo_files

    try:
        async with httpx.AsyncClient(timeout=35) as hc:
            if album_query:
                track_resps, album_resps = await _asyncio.gather(
                    run_search(hc, track_query),
                    run_search(hc, album_query),
                )
            else:
                track_resps = await run_search(hc, track_query)
                album_resps = []

        track_folders, track_solos = process_responses(track_resps)
        album_folders, _ = process_responses(album_resps)

        # Merge: album_folders first, then non-duplicate track_folders
        seen = {(f["username"], f["folder"]) for f in album_folders}
        for f in track_folders:
            if (f["username"], f["folder"]) not in seen:
                album_folders.append(f)
                seen.add((f["username"], f["folder"]))

        return {
            "folders": album_folders[:30],
            "results": track_solos[:50],
            "query": track_query,
            "album_query": album_query,
        }
    except Exception as e:
        return {"results": [], "folders": [], "error": str(e)}


@app.post("/search/grab-soulseek")
async def grab_soulseek(body: dict):
    """Queue files for download via slskd."""
    import httpx

    username = body.get("username")
    files = body.get("files", [])
    if not username or not files:
        raise HTTPException(400, "username and files required")

    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM download_clients WHERE type = 'slskd' AND enabled = 1 LIMIT 1")
        client_row = await cur.fetchone()
    finally:
        await db.close()

    if not client_row:
        raise HTTPException(503, "No slskd client configured")

    client_row = dict(client_row)
    url = (client_row.get("url_base") or "").rstrip("/")
    if not url:
        host = client_row.get("host", "localhost")
        port = client_row.get("port", 5030)
        url = f"http://{host}:{port}"
    api_key = client_row.get("api_key", "")
    headers = {"X-API-Key": api_key} if api_key else {}

    payload = [{"filename": f.get("filename", ""), "size": f.get("size", 0)} for f in files]
    try:
        async with httpx.AsyncClient(timeout=30) as hc:
            resp = await hc.post(
                f"{url}/api/v0/transfers/downloads/{username}",
                json=payload,
                headers=headers,
            )
            if resp.status_code not in (200, 201, 204):
                raise HTTPException(502, f"slskd error {resp.status_code}: {resp.text[:300]}")
        return {"ok": True, "queued": len(files)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e))


@app.get("/search/youtube")
async def search_youtube(q: str, artist: str = ""):
    """Search YouTube for tracks using yt-dlp."""
    import asyncio as _asyncio
    import json as _json

    mode = await get_setting("youtube_search_mode", "studio")
    suffix = "official audio" if mode == "studio" else "official music video"
    query = f"{artist} {q} {suffix}".strip() if artist else f"{q} {suffix}"

    try:
        proc = await _asyncio.create_subprocess_exec(
            "yt-dlp", "--flat-playlist", "--dump-json", "--no-warnings",
            f"ytsearch10:{query}",
            stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.DEVNULL
        )
        stdout, _ = await _asyncio.wait_for(proc.communicate(), timeout=25)
        results = []
        for line in stdout.decode().strip().split("\n"):
            if not line.strip():
                continue
            try:
                item = _json.loads(line)
                results.append({
                    "id": item.get("id", ""),
                    "title": item.get("title", ""),
                    "uploader": item.get("uploader", item.get("channel", "")),
                    "duration": item.get("duration", 0),
                    "view_count": item.get("view_count", 0),
                    "url": f"https://www.youtube.com/watch?v={item.get('id', '')}",
                    "thumbnail": item.get("thumbnail", ""),
                })
            except Exception:
                pass
        return {"results": results[:10], "query": query}
    except Exception as e:
        return {"results": [], "error": str(e), "query": query}


@app.get("/search/spotizerr-history")
async def search_spotizerr_history(spotify_id: str):
    """Check Spotizerr history for a specific spotify_id."""
    import httpx

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM downloads WHERE spotify_id = ? ORDER BY created_at DESC LIMIT 10",
            (spotify_id,)
        )
        local = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()

    spotizerr_item = None
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(f"{SPOTIZERR_URL}/api/history/", params={"limit": 500})
            if resp.status_code == 200:
                for item in resp.json().get("downloads", []):
                    sid = item.get("external_ids", {}).get("spotify", "")
                    if sid == spotify_id:
                        spotizerr_item = item
                        break
    except Exception:
        pass

    return {"local_history": local, "spotizerr": spotizerr_item}


@app.post("/search/grab-spotizerr")
async def grab_spotizerr(body: dict):
    """Send a track/album to Spotizerr for download."""
    from spotizerr_client import dispatch_download
    spotify_id = body.get("spotify_id", "")
    item_type = body.get("item_type", "track")
    title = body.get("title", "")
    artist = body.get("artist", "")
    album = body.get("album", "")
    if not spotify_id:
        raise HTTPException(status_code=400, detail="spotify_id required")
    result = await dispatch_download(spotify_id, item_type, title, artist, album, source="manual")
    return result


# ─── Library Browse Endpoints ──────────────────────────────────────────────────

@app.get("/library/stats")
async def library_stats():
    db = await get_db()
    try:
        cur = await db.execute("SELECT COUNT(*) as total, SUM(size) as total_size FROM tracks")
        row = dict(await cur.fetchone())
        total_tracks = row["total"] or 0
        total_size = row["total_size"] or 0

        cur = await db.execute("""
            SELECT COUNT(DISTINCT COALESCE(NULLIF(TRIM(album_artist),''), NULLIF(TRIM(artist),''))) as cnt
            FROM tracks WHERE COALESCE(NULLIF(TRIM(album_artist),''), NULLIF(TRIM(artist),'')) IS NOT NULL
        """)
        total_artists = (await cur.fetchone())["cnt"] or 0

        cur = await db.execute("""
            SELECT COUNT(DISTINCT LOWER(COALESCE(NULLIF(TRIM(album_artist),''), NULLIF(TRIM(artist),''), '')) || '|' || LOWER(COALESCE(NULLIF(TRIM(album),''), ''))) as cnt
            FROM tracks WHERE album IS NOT NULL AND album != ''
        """)
        total_albums = (await cur.fetchone())["cnt"] or 0

        cur = await db.execute(
            "SELECT COUNT(*) as cnt FROM tracks WHERE (spotify_id IS NULL OR spotify_id = '') AND (mbid IS NULL OR mbid = '')"
        )
        unmatched = (await cur.fetchone())["cnt"] or 0

        cur = await db.execute("SELECT * FROM scan_history ORDER BY started_at DESC LIMIT 1")
        last_scan_row = await cur.fetchone()
        last_scan = dict(last_scan_row) if last_scan_row else None

        return {
            "total_tracks": total_tracks,
            "total_artists": total_artists,
            "total_albums": total_albums,
            "total_size": total_size,
            "unmatched_tracks": unmatched,
            "last_scan": last_scan,
        }
    finally:
        await db.close()


@app.get("/library/browse/artists")
async def library_browse_artists(q: str = "", letter: str = "", offset: int = 0, limit: int = 50):
    db = await get_db()
    try:
        base = """
            SELECT
                COALESCE(NULLIF(TRIM(album_artist),''), NULLIF(TRIM(artist),'')) as artist_name,
                COUNT(*) as track_count,
                COUNT(DISTINCT LOWER(COALESCE(NULLIF(TRIM(album),''), ''))) as album_count
            FROM tracks
            WHERE COALESCE(NULLIF(TRIM(album_artist),''), NULLIF(TRIM(artist),'')) IS NOT NULL
        """
        params = []
        if q:
            base += " AND LOWER(COALESCE(NULLIF(TRIM(album_artist),''), NULLIF(TRIM(artist),''))) LIKE ?"
            params.append(f"%{q.lower()}%")
        if letter:
            if letter == "#":
                base += " AND SUBSTR(LOWER(COALESCE(NULLIF(TRIM(album_artist),''), NULLIF(TRIM(artist),''))), 1, 1) NOT BETWEEN 'a' AND 'z'"
            else:
                base += " AND UPPER(SUBSTR(COALESCE(NULLIF(TRIM(album_artist),''), NULLIF(TRIM(artist),'')), 1, 1)) = ?"
                params.append(letter.upper())
        base += " GROUP BY artist_name ORDER BY LOWER(artist_name) LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cur = await db.execute(base, params)
        artists = [dict(r) for r in await cur.fetchall()]

        count_q = """
            SELECT COUNT(DISTINCT COALESCE(NULLIF(TRIM(album_artist),''), NULLIF(TRIM(artist),''))) as cnt
            FROM tracks WHERE COALESCE(NULLIF(TRIM(album_artist),''), NULLIF(TRIM(artist),'')) IS NOT NULL
        """
        cparams = []
        if q:
            count_q += " AND LOWER(COALESCE(NULLIF(TRIM(album_artist),''), NULLIF(TRIM(artist),''))) LIKE ?"
            cparams.append(f"%{q.lower()}%")
        if letter:
            if letter == "#":
                count_q += " AND SUBSTR(LOWER(COALESCE(NULLIF(TRIM(album_artist),''), NULLIF(TRIM(artist),''))), 1, 1) NOT BETWEEN 'a' AND 'z'"
            else:
                count_q += " AND UPPER(SUBSTR(COALESCE(NULLIF(TRIM(album_artist),''), NULLIF(TRIM(artist),'')), 1, 1)) = ?"
                cparams.append(letter.upper())
        cur = await db.execute(count_q, cparams)
        total = (await cur.fetchone())["cnt"] or 0

        return {"artists": artists, "total": total, "offset": offset, "limit": limit}
    finally:
        await db.close()


@app.get("/library/browse/albums")
async def library_browse_albums(artist: str):
    db = await get_db()
    try:
        cur = await db.execute("""
            SELECT
                COALESCE(NULLIF(TRIM(album),''), '(Unknown Album)') as album_name,
                COUNT(*) as track_count,
                MIN(year) as year,
                MIN(format) as format
            FROM tracks
            WHERE COALESCE(NULLIF(TRIM(album_artist),''), NULLIF(TRIM(artist),'')) = ?
            GROUP BY album_name
            ORDER BY year, album_name
        """, (artist,))
        albums = [dict(r) for r in await cur.fetchall()]
        return {"albums": albums}
    finally:
        await db.close()


@app.get("/library/browse/tracks")
async def library_browse_tracks(artist: str, album: str = ""):
    db = await get_db()
    try:
        if album:
            cur = await db.execute("""
                SELECT id, path, title, track_number, disc_number, duration, format, bitrate, spotify_id
                FROM tracks
                WHERE COALESCE(NULLIF(TRIM(album_artist),''), NULLIF(TRIM(artist),'')) = ?
                AND COALESCE(NULLIF(TRIM(album),''), '(Unknown Album)') = ?
                ORDER BY disc_number, track_number
            """, (artist, album))
        else:
            cur = await db.execute("""
                SELECT id, path, title, track_number, disc_number, duration, format, bitrate, spotify_id
                FROM tracks
                WHERE COALESCE(NULLIF(TRIM(album_artist),''), NULLIF(TRIM(artist),'')) = ?
                ORDER BY album, disc_number, track_number
            """, (artist,))
        tracks = [dict(r) for r in await cur.fetchall()]
        return {"tracks": tracks}
    finally:
        await db.close()


@app.get("/library/unmatched/search")
async def library_unmatched_search(q: str = "", offset: int = 0, limit: int = 50):
    db = await get_db()
    try:
        where = "WHERE (spotify_id IS NULL OR spotify_id = '') AND (mbid IS NULL OR mbid = '')"
        params = []
        if q:
            where += " AND (LOWER(path) LIKE ? OR LOWER(COALESCE(title,'')) LIKE ? OR LOWER(COALESCE(artist,'')) LIKE ?)"
            lq = f"%{q.lower()}%"
            params.extend([lq, lq, lq])

        cur = await db.execute(f"SELECT COUNT(*) as cnt FROM tracks {where}", params)
        total = (await cur.fetchone())["cnt"] or 0

        cur = await db.execute(
            f"SELECT id, path, artist, album_artist, title, album, year, format, bitrate, duration, size FROM tracks {where} ORDER BY path LIMIT ? OFFSET ?",
            params + [limit, offset]
        )
        items = [dict(r) for r in await cur.fetchall()]
        return {"items": items, "total": total, "offset": offset, "limit": limit}
    finally:
        await db.close()


def _normalize_for_match(s: str) -> str:
    """Strip feat./ft./featuring, bracketed annotations, and normalize spacing."""
    import re
    s = re.sub(r'\s*[\(\[]?(?:feat\.?|ft\.?|featuring|with)\s+[^\)\]]+[\)\]]?', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s*\([^)]*\)', '', s)   # remove any remaining (...) suffixes
    s = re.sub(r'\s*\[[^\]]*\]', '', s)  # remove any remaining [...] suffixes
    return s.strip().lower()


def _score_candidate(title: str, artist: str, duration_ms: int, track: dict) -> tuple[int, float]:
    """Return (confidence 0-100, duration_delta_s) for a Spotify track candidate.

    Scoring mirrors Lidarr's approach:
      - Exact duration match (within 1s) is a near-certain signal
      - Title similarity (normalized): 45%
      - Artist similarity (normalized): 35%
      - Duration closeness: 20%
      - Hard reject if duration differs by >10s and title/artist aren't both 100
    """
    from rapidfuzz import fuzz

    nt = _normalize_for_match(title)
    na = _normalize_for_match(artist)
    track_title  = track.get("name", "")
    track_artist = track["artists"][0]["name"] if track.get("artists") else ""
    nt2 = _normalize_for_match(track_title)
    na2 = _normalize_for_match(track_artist)

    title_score  = fuzz.token_sort_ratio(nt, nt2)
    artist_score = fuzz.token_sort_ratio(na, na2) if artist else 50

    duration_delta = abs(duration_ms - track["duration_ms"]) if duration_ms and track.get("duration_ms") else 30000
    duration_delta_s = round(duration_delta / 1000, 1)

    # Duration scoring: 100 at 0s diff, 0 at 10s+ diff
    duration_score = max(0, 100 - int(duration_delta / 100))

    confidence = int((title_score * 0.45) + (artist_score * 0.35) + (duration_score * 0.20))

    # Hard cap: if duration is off by >10s and it's not a near-perfect title+artist match, reduce confidence
    if duration_delta > 10000 and (title_score < 95 or artist_score < 95):
        confidence = min(confidence, 70)

    return confidence, duration_delta_s


@app.get("/library/match/candidates")
async def library_match_candidates(title: str, artist: str = "", duration_ms: int = 0):
    """Search monitored_tracks locally and MusicBrainz for potential matches."""
    import asyncio as _asyncio
    from matcher import _score, _norm, musicbrainz_search, fuzz

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT spotify_id, name, artist_name, duration_ms FROM monitored_tracks WHERE name IS NOT NULL AND name != ''"
        )
        all_mt = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()

    ld_s = (duration_ms or 0) / 1000

    # Phase 1: score against monitored_tracks
    def _score_all():
        scored = []
        for mt in all_mt:
            s = _score(title, artist, ld_s, mt["name"], mt["artist_name"], mt["duration_ms"])
            if s >= 50:
                delta = round(abs(ld_s - (mt["duration_ms"] or 0) / 1000), 1) if ld_s else 0
                scored.append({
                    "type": "monitored",
                    "spotify_id": mt["spotify_id"],
                    "mbid": None,
                    "title": mt["name"],
                    "artist": mt["artist_name"],
                    "album": "",
                    "duration_ms": mt["duration_ms"],
                    "image_url": None,
                    "confidence": s,
                    "duration_delta_s": delta,
                })
        scored.sort(key=lambda x: -x["confidence"])
        return scored[:5]

    local_results = await _asyncio.to_thread(_score_all) if all_mt else []

    # Phase 2: MusicBrainz search (always run — provides richer identification)
    mb_raw = await musicbrainz_search(title, artist)
    mb_results = []
    for cand in mb_raw:
        if cand.get("score", 0) < 75:
            continue
        title_score = fuzz.token_sort_ratio(_norm(title), _norm(cand["title"]))
        a_cand = cand.get("artist") or ""
        artist_score = fuzz.token_sort_ratio(_norm(artist), _norm(a_cand)) if artist and a_cand else 50
        cand_dur_s = (cand.get("duration_ms") or 0) / 1000
        if ld_s and cand_dur_s:
            delta = abs(ld_s - cand_dur_s)
            dur_score = max(0, 100 - int(delta * 12))
        else:
            dur_score = 50
        conf = int(title_score * 0.45 + artist_score * 0.35 + dur_score * 0.20)
        if ld_s and cand_dur_s and abs(ld_s - cand_dur_s) > 10:
            if title_score < 95 or artist_score < 95:
                conf = min(conf, 65)
        if conf >= 50:
            mb_results.append({
                "type": "musicbrainz",
                "spotify_id": None,
                "mbid": cand["mbid"],
                "title": cand["title"],
                "artist": a_cand,
                "album": "",
                "duration_ms": cand.get("duration_ms"),
                "image_url": None,
                "confidence": conf,
                "duration_delta_s": round(abs(ld_s - cand_dur_s), 1) if ld_s and cand_dur_s else 0,
            })
    mb_results.sort(key=lambda x: -x["confidence"])
    mb_results = mb_results[:5]

    return {"candidates": local_results, "mb_results": mb_results}


_auto_match_state: dict = {"running": False, "pct": 0, "matched": 0, "processed": 0, "total": 0, "current": "", "wanted_count": 0, "done": False, "error": None}


@app.post("/library/auto-match/start")
async def auto_match_start():
    """Start auto-match as a background task. Poll /library/auto-match/progress for updates."""
    import asyncio as _asyncio
    from matcher import match_local_to_monitored_stream

    if _auto_match_state["running"]:
        return {"started": False, "reason": "already running"}

    _auto_match_state.update(running=True, pct=0, matched=0, processed=0, total=0, current="", wanted_count=0, done=False, error=None)

    async def _run():
        try:
            async for event in match_local_to_monitored_stream():
                s = event.get("status")
                if s == "started":
                    _auto_match_state["total"] = event.get("total", 0)
                    _auto_match_state["wanted_count"] = event.get("wanted_count", 0)
                elif s == "progress":
                    _auto_match_state["pct"]       = event.get("pct", 0)
                    _auto_match_state["matched"]   = event.get("matched", 0)
                    _auto_match_state["processed"] = event.get("processed", 0)
                    _auto_match_state["current"]   = event.get("current", "")
                elif s == "done":
                    _auto_match_state["pct"]       = 100
                    _auto_match_state["matched"]   = event.get("matched", 0)
                    _auto_match_state["processed"] = event.get("processed", 0)
                    _auto_match_state["done"]      = True
        except Exception as e:
            _auto_match_state["error"] = str(e)
        finally:
            _auto_match_state["running"] = False

    _asyncio.create_task(_run())
    return {"started": True}


@app.get("/library/auto-match/progress")
async def auto_match_progress():
    """Return current auto-match progress for polling."""
    return dict(_auto_match_state)


_mb_identify_state: dict = {"running": False, "pct": 0, "identified": 0, "processed": 0, "total": 0, "current": "", "done": False, "error": None}


@app.post("/library/mb-identify/start")
async def mb_identify_start():
    """Identify local tracks via MusicBrainz search. Rate-limited to ~1 req/s."""
    import asyncio as _asyncio
    from matcher import identify_via_mb_stream

    if _mb_identify_state["running"]:
        return {"started": False, "reason": "already running"}

    _mb_identify_state.update(running=True, pct=0, identified=0, processed=0, total=0, current="", done=False, error=None)

    async def _run():
        try:
            async for event in identify_via_mb_stream():
                s = event.get("status")
                if s == "started":
                    _mb_identify_state["total"] = event.get("total", 0)
                elif s == "progress":
                    _mb_identify_state["pct"]        = event.get("pct", 0)
                    _mb_identify_state["identified"]  = event.get("identified", 0)
                    _mb_identify_state["processed"]   = event.get("processed", 0)
                    _mb_identify_state["current"]     = event.get("current", "")
                elif s == "done":
                    _mb_identify_state["pct"]        = 100
                    _mb_identify_state["identified"]  = event.get("identified", 0)
                    _mb_identify_state["processed"]   = event.get("processed", 0)
                    _mb_identify_state["done"]        = True
        except Exception as e:
            _mb_identify_state["error"] = str(e)
        finally:
            _mb_identify_state["running"] = False

    _asyncio.create_task(_run())
    return {"started": True}


@app.get("/library/mb-identify/progress")
async def mb_identify_progress():
    """Return current MusicBrainz identify progress for polling."""
    return dict(_mb_identify_state)


@app.post("/library/unmatched/{track_id}/match")
async def library_match_track(track_id: int, body: dict):
    """Manually assign a spotify_id or mbid to an unmatched local track."""
    spotify_id = body.get("spotify_id", "")
    mbid = body.get("mbid", "")
    if not spotify_id and not mbid:
        raise HTTPException(status_code=400, detail="spotify_id or mbid required")
    db = await get_db()
    try:
        if spotify_id:
            await db.execute(
                "UPDATE tracks SET spotify_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (spotify_id, track_id)
            )
            await db.execute(
                "UPDATE monitored_tracks SET status = 'have', local_track_id = ?, local_path = (SELECT path FROM tracks WHERE id = ?), updated_at = CURRENT_TIMESTAMP WHERE spotify_id = ? AND status != 'have'",
                (track_id, track_id, spotify_id)
            )
        else:
            await db.execute(
                "UPDATE tracks SET mbid = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (mbid, track_id)
            )
        await db.commit()
        return {"success": True}
    finally:
        await db.close()


@app.post("/library/unmatched/{track_id}/ignore")
async def library_ignore_track(track_id: int):
    """Mark a track as ignored in the unmatched list."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE tracks SET spotify_id = 'IGNORED', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (track_id,)
        )
        await db.commit()
        return {"success": True}
    finally:
        await db.close()


# ─── Phase 6: Blocklist ───────────────────────────────────────────────────────

@app.get("/blocklist")
async def blocklist_list():
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM blocklist ORDER BY added_at DESC")
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


class BlocklistAdd(BaseModel):
    value: str
    type: str = "url"
    title: Optional[str] = None
    reason: Optional[str] = None
    source: Optional[str] = None


@app.post("/blocklist")
async def blocklist_add(body: BlocklistAdd):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR IGNORE INTO blocklist (type, value, title, reason, source) VALUES (?, ?, ?, ?, ?)",
            (body.type, body.value.strip(), body.title, body.reason, body.source),
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@app.delete("/blocklist/{item_id}")
async def blocklist_delete(item_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM blocklist WHERE id=?", (item_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@app.delete("/blocklist")
async def blocklist_clear():
    db = await get_db()
    try:
        await db.execute("DELETE FROM blocklist")
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


# ─── Phase 6: Queue management ───────────────────────────────────────────────

@app.get("/downloads/queue/status")
async def queue_status():
    paused = await get_setting("queue_paused", "0") == "1"
    return {"paused": paused}


@app.post("/downloads/queue/pause")
async def queue_pause():
    await set_setting("queue_paused", "1")
    await add_activity("queue_paused", "Download queue paused")
    return {"paused": True}


@app.post("/downloads/queue/resume")
async def queue_resume():
    await set_setting("queue_paused", "0")
    await add_activity("queue_resumed", "Download queue resumed")
    return {"paused": False}


@app.post("/downloads/queue/clear-failed")
async def queue_clear_failed():
    db = await get_db()
    try:
        cur = await db.execute(
            "DELETE FROM downloads WHERE status IN ('failed','cancelled','cooling')"
        )
        deleted = cur.rowcount
        # Also clear failed unified_downloads
        cur2 = await db.execute(
            "DELETE FROM unified_downloads WHERE status IN ('failed','cancelled')"
        )
        deleted += cur2.rowcount
        await db.commit()
    finally:
        await db.close()
    await add_activity("queue_clear_failed", f"Cleared {deleted} failed/cancelled downloads")
    return {"deleted": deleted}


@app.post("/downloads/queue/clear-completed")
async def queue_clear_completed():
    db = await get_db()
    try:
        cur = await db.execute("DELETE FROM downloads WHERE status = 'completed'")
        deleted = cur.rowcount
        cur2 = await db.execute("DELETE FROM unified_downloads WHERE status = 'completed'")
        deleted += cur2.rowcount
        await db.commit()
    finally:
        await db.close()
    return {"deleted": deleted}


# ─── Phase 6: API Key auth helper ────────────────────────────────────────────

@app.get("/auth/api-key")
async def get_api_key():
    """Return (or generate) the API key for external integrations."""
    import secrets
    key = await get_setting("jukeboxx_api_key", "")
    if not key:
        key = secrets.token_hex(32)
        await set_setting("jukeboxx_api_key", key)
    return {"api_key": key}


@app.post("/auth/api-key/regenerate")
async def regenerate_api_key():
    import secrets
    key = secrets.token_hex(32)
    await set_setting("jukeboxx_api_key", key)
    return {"api_key": key}


# ─── Phase 6: Discord webhook test ───────────────────────────────────────────

@app.post("/notifications/test-discord")
async def test_discord_webhook():
    from discord import send_discord, COLOR_BLUE
    webhook_url = await get_setting("discord_webhook_url", "")
    if not webhook_url:
        raise HTTPException(400, "discord_webhook_url not configured")
    await send_discord(
        title="JukeBoxx — Test Notification",
        description="Discord webhook is working correctly.",
        color=COLOR_BLUE,
    )
    return {"ok": True}




# ─── Single-container static file serving ────────────────────────────────────
import os as _os
from fastapi import FastAPI as _FastAPI
from fastapi.staticfiles import StaticFiles as _StaticFiles
from fastapi.middleware.cors import CORSMiddleware as _CORSMiddleware

_static_dir = "/app/static"
if _os.path.isdir(_static_dir):
    from contextlib import asynccontextmanager as _asynccontextmanager

    @_asynccontextmanager
    async def _root_lifespan(_app):
        # Run the inner app's full startup (DB init, scheduler, etc.)
        async with lifespan(app):
            yield

    root_app = _FastAPI(title="JukeBoxx", lifespan=_root_lifespan)
    root_app.add_middleware(
        _CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    root_app.mount("/api", app)
    root_app.mount("/", _StaticFiles(directory=_static_dir, html=True), name="static")
else:
    root_app = app  # dev mode: no static dir, routes served at root
