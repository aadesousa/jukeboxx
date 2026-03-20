"""Spotify library endpoints + import APIs — Phase 5"""
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from database import get_db

log = logging.getLogger("jukeboxx.spotify_library")
router = APIRouter(tags=["spotify-library"])

# ── Helpers ───────────────────────────────────────────────────────

async def _get_sp():
    from spotify_auth import get_spotify_client, is_rate_limited, get_rate_limit_remaining
    if is_rate_limited():
        remaining = get_rate_limit_remaining()
        raise HTTPException(429, f"Spotify rate limited — try again in {remaining // 60} min")
    sp = await get_spotify_client()
    if not sp:
        raise HTTPException(403, "Spotify not connected")
    return sp


async def _local_status(spotify_ids: list[str]) -> dict[str, str]:
    """Return {spotify_id: status} for known tracks. status: 'have' | 'monitored' | 'wanted'"""
    if not spotify_ids:
        return {}
    db = await get_db()
    try:
        result = {}
        placeholders = ",".join("?" * len(spotify_ids))
        # Local library
        cur = await db.execute(
            f"SELECT spotify_id FROM tracks WHERE spotify_id IN ({placeholders})", spotify_ids
        )
        for row in await cur.fetchall():
            result[row["spotify_id"]] = "have"
        # Monitored tracks (only those not already 'have')
        remaining = [sid for sid in spotify_ids if sid not in result]
        if remaining:
            rph = ",".join("?" * len(remaining))
            cur = await db.execute(
                f"SELECT spotify_id, status FROM monitored_tracks WHERE spotify_id IN ({rph})", remaining
            )
            for row in await cur.fetchall():
                result[row["spotify_id"]] = row["status"]
        return result
    finally:
        await db.close()


def _track_from_saved(item: dict) -> dict | None:
    """Normalize a saved-track item (wraps 'track') into a flat dict."""
    t = item.get("track")
    if not t or t.get("is_local"):
        return None
    artists = t.get("artists") or []
    album   = t.get("album") or {}
    images  = album.get("images") or []
    return {
        "spotify_id":       t["id"],
        "name":             t.get("name", ""),
        "artist_name":      artists[0].get("name", "") if artists else "",
        "artist_spotify_id":artists[0].get("id", "")   if artists else "",
        "album_name":       album.get("name", ""),
        "album_spotify_id": album.get("id", ""),
        "album_image":      images[0].get("url") if images else None,
        "image_url":        images[0].get("url") if images else None,
        "track_number":     t.get("track_number"),
        "disc_number":      t.get("disc_number", 1),
        "duration_ms":      t.get("duration_ms"),
        "added_at":         item.get("added_at"),
    }


# ── GET /spotify/liked-songs ──────────────────────────────────────

@router.get("/spotify/liked-songs")
async def liked_songs(
    offset: int = 0,
    limit:  int = Query(50, le=50),
):
    sp = await _get_sp()
    from spotify_auth import record_successful_call
    from spotify_cache import cache_get, cache_set

    cache_key = f"liked_songs:{offset}:{limit}"
    cached = await cache_get(cache_key)
    if cached is not None:
        raw_items = cached.get("items", [])
        total = cached.get("total", 0)
        tracks = raw_items
    else:
        result = await asyncio.to_thread(sp.current_user_saved_tracks, limit=limit, offset=offset)
        record_successful_call()
        raw_items = result.get("items", [])
        total = result.get("total", 0)
        tracks = [t for item in raw_items if (t := _track_from_saved(item))]
        await cache_set(cache_key, {"items": tracks, "total": total})

    # Enrich with local / monitored status (always fresh from DB)
    ids = [t["spotify_id"] for t in tracks]
    status_map = await _local_status(ids)
    for t in tracks:
        t["monitored_status"] = status_map.get(t["spotify_id"])

    return {"items": tracks, "total": total, "offset": offset, "limit": limit}


# ── GET /spotify/saved-albums ─────────────────────────────────────

@router.get("/spotify/saved-albums")
async def saved_albums(
    offset: int = 0,
    limit:  int = Query(50, le=50),
):
    sp = await _get_sp()
    from spotify_auth import record_successful_call
    from spotify_cache import cache_get, cache_set

    cache_key = f"saved_albums:{offset}:{limit}"
    cached = await cache_get(cache_key)
    if cached is not None:
        albums = cached.get("items", [])
        total = cached.get("total", 0)
    else:
        result = await asyncio.to_thread(sp.current_user_saved_albums, limit=limit, offset=offset)
        record_successful_call()
        raw_items = result.get("items", [])
        total = result.get("total", 0)
        albums = []
        for item in raw_items:
            a = item.get("album")
            if not a:
                continue
            images  = a.get("images") or []
            artists = a.get("artists") or []
            albums.append({
                "spotify_id":       a["id"],
                "name":             a.get("name", ""),
                "artist_name":      artists[0].get("name", "") if artists else "",
                "artist_spotify_id":artists[0].get("id", "")   if artists else "",
                "album_type":       a.get("album_type", "album"),
                "release_date":     a.get("release_date", ""),
                "track_count":      a.get("total_tracks", 0),
                "image_url":        images[0].get("url") if images else None,
                "added_at":         item.get("added_at"),
            })
        await cache_set(cache_key, {"items": albums, "total": total})

    # Enrich with monitored status (always fresh from DB)
    db = await get_db()
    try:
        for alb in albums:
            cur = await db.execute(
                "SELECT status FROM monitored_albums WHERE spotify_id = ?", (alb["spotify_id"],)
            )
            row = await cur.fetchone()
            alb["monitored_status"] = row["status"] if row else None
    finally:
        await db.close()

    return {"items": albums, "total": total, "offset": offset, "limit": limit}


# ── GET /spotify/followed-artists ────────────────────────────────

@router.get("/spotify/followed-artists")
async def followed_artists(
    after:  Optional[str] = None,
    limit:  int = Query(50, le=50),
):
    sp = await _get_sp()
    from spotify_auth import record_successful_call
    from spotify_cache import cache_get, cache_set

    cache_key = f"followed_artists:{after or 'start'}:{limit}"
    cached = await cache_get(cache_key)
    if cached is not None:
        artists = cached.get("items", [])
        total = cached.get("total", len(artists))
        next_cursor = cached.get("next_cursor")
    else:
        kwargs = {"limit": limit}
        if after:
            kwargs["after"] = after
        result = await asyncio.to_thread(sp.current_user_followed_artists, **kwargs)
        record_successful_call()

        artists_data = result.get("artists", {})
        items = artists_data.get("items", [])
        next_cursor = None
        cursors = artists_data.get("cursors") or {}
        if artists_data.get("next"):
            next_cursor = cursors.get("after")

        artists = []
        for a in items:
            images = a.get("images") or []
            artists.append({
                "spotify_id":  a["id"],
                "name":        a.get("name", ""),
                "image_url":   images[0].get("url") if images else None,
                "genres":      a.get("genres", []),
                "followers":   a.get("followers", {}).get("total", 0),
                "popularity":  a.get("popularity", 0),
            })
        total = artists_data.get("total", len(artists))
        await cache_set(cache_key, {"items": artists, "total": total, "next_cursor": next_cursor})

    # Enrich with monitored status (always fresh from DB)
    db = await get_db()
    try:
        for a in artists:
            cur = await db.execute(
                "SELECT id, monitored FROM monitored_artists WHERE spotify_id = ?", (a["spotify_id"],)
            )
            row = await cur.fetchone()
            a["monitored_status"] = "monitored" if (row and row["monitored"]) else (
                "added" if row else None
            )
    finally:
        await db.close()

    return {
        "items":       artists,
        "total":       total,
        "next_cursor": next_cursor,
    }


# ── POST /import/tracks ───────────────────────────────────────────

@router.post("/import/tracks")
async def import_tracks(body: dict):
    """Bulk import tracks from Spotify library into monitored_tracks."""
    tracks = body.get("tracks", [])
    if not tracks:
        raise HTTPException(400, "tracks list required")

    db = await get_db()
    try:
        added, skipped, already_monitored = 0, 0, 0

        for t in tracks:
            sid = t.get("spotify_id") or t.get("id")
            if not sid:
                skipped += 1
                continue

            cur = await db.execute(
                "SELECT id FROM monitored_tracks WHERE spotify_id = ?", (sid,)
            )
            if await cur.fetchone():
                already_monitored += 1
                continue

            # Ensure artist exists (create minimal entry if needed)
            artist_id = None
            a_sid = t.get("artist_spotify_id")
            if a_sid:
                cur = await db.execute(
                    "SELECT id FROM monitored_artists WHERE spotify_id = ?", (a_sid,)
                )
                row = await cur.fetchone()
                if row:
                    artist_id = row["id"]
                elif t.get("artist_name"):
                    await db.execute(
                        """INSERT OR IGNORE INTO monitored_artists
                           (spotify_id, name, image_url, monitored, monitor_new_releases)
                           VALUES (?, ?, ?, 1, 0)""",
                        (a_sid, t["artist_name"], t.get("artist_image")),
                    )
                    await db.commit()
                    cur = await db.execute(
                        "SELECT id FROM monitored_artists WHERE spotify_id = ?", (a_sid,)
                    )
                    row = await cur.fetchone()
                    if row:
                        artist_id = row["id"]

            # Ensure album exists (create minimal entry if needed)
            album_id = None
            alb_sid = t.get("album_spotify_id")
            if alb_sid:
                cur = await db.execute(
                    "SELECT id FROM monitored_albums WHERE spotify_id = ?", (alb_sid,)
                )
                row = await cur.fetchone()
                if row:
                    album_id = row["id"]
                elif t.get("album_name"):
                    await db.execute(
                        """INSERT OR IGNORE INTO monitored_albums
                           (spotify_id, artist_id, artist_spotify_id, name, image_url, monitored)
                           VALUES (?, ?, ?, ?, ?, 1)""",
                        (alb_sid, artist_id, a_sid or "", t["album_name"],
                         t.get("album_image") or t.get("image_url")),
                    )
                    await db.commit()
                    cur = await db.execute(
                        "SELECT id FROM monitored_albums WHERE spotify_id = ?", (alb_sid,)
                    )
                    row = await cur.fetchone()
                    if row:
                        album_id = row["id"]

            await db.execute(
                """INSERT OR IGNORE INTO monitored_tracks
                   (spotify_id, album_id, artist_id, album_spotify_id, artist_spotify_id,
                    name, artist_name, album_name, track_number, disc_number,
                    duration_ms, image_url, monitored, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'wanted')""",
                (
                    sid, album_id, artist_id,
                    t.get("album_spotify_id"), t.get("artist_spotify_id"),
                    t.get("name", "Unknown"), t.get("artist_name"), t.get("album_name"),
                    t.get("track_number"), t.get("disc_number", 1),
                    t.get("duration_ms"),
                    t.get("image_url") or t.get("album_image"),
                ),
            )
            added += 1

        await db.commit()

        if added > 0:
            import asyncio as _asyncio
            async def _bg_match():
                from matcher import match_local_to_monitored
                await match_local_to_monitored()
            _asyncio.create_task(_bg_match())

        return {"added": added, "skipped": skipped, "already_monitored": already_monitored}
    finally:
        await db.close()


# ── POST /import/albums ───────────────────────────────────────────

@router.post("/import/albums")
async def import_albums(body: dict):
    """Bulk import saved albums into monitored_albums."""
    albums = body.get("albums", [])
    if not albums:
        raise HTTPException(400, "albums list required")

    db = await get_db()
    try:
        added, already_monitored = 0, 0

        for a in albums:
            sid = a.get("spotify_id")
            if not sid:
                continue

            cur = await db.execute(
                "SELECT id FROM monitored_albums WHERE spotify_id = ?", (sid,)
            )
            if await cur.fetchone():
                already_monitored += 1
                continue

            # Ensure artist
            artist_id = None
            a_sid = a.get("artist_spotify_id")
            if a_sid:
                cur = await db.execute(
                    "SELECT id FROM monitored_artists WHERE spotify_id = ?", (a_sid,)
                )
                row = await cur.fetchone()
                if row:
                    artist_id = row["id"]
                elif a.get("artist_name"):
                    await db.execute(
                        """INSERT OR IGNORE INTO monitored_artists
                           (spotify_id, name, monitored, monitor_new_releases)
                           VALUES (?, ?, 1, 0)""",
                        (a_sid, a["artist_name"]),
                    )
                    await db.commit()
                    cur = await db.execute(
                        "SELECT id FROM monitored_artists WHERE spotify_id = ?", (a_sid,)
                    )
                    row = await cur.fetchone()
                    if row:
                        artist_id = row["id"]

            await db.execute(
                """INSERT OR IGNORE INTO monitored_albums
                   (spotify_id, artist_id, artist_spotify_id, name, album_type,
                    release_date, track_count, image_url, monitored, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'wanted')""",
                (
                    sid, artist_id, a.get("artist_spotify_id") or "",
                    a.get("name", "Unknown"), a.get("album_type", "album"),
                    a.get("release_date"), a.get("track_count", 0), a.get("image_url"),
                ),
            )
            added += 1

        await db.commit()
        return {"added": added, "already_monitored": already_monitored}
    finally:
        await db.close()


# ── POST /import/artists ──────────────────────────────────────────

@router.post("/import/artists")
async def import_artists(body: dict):
    """Bulk import followed artists into monitored_artists."""
    import json as _json
    artists = body.get("artists", [])
    if not artists:
        raise HTTPException(400, "artists list required")

    db = await get_db()
    try:
        added, already_monitored = 0, 0
        artist_ids = []

        for a in artists:
            sid = a.get("spotify_id")
            if not sid:
                continue

            cur = await db.execute(
                "SELECT id, monitored FROM monitored_artists WHERE spotify_id = ?", (sid,)
            )
            existing = await cur.fetchone()
            if existing:
                already_monitored += 1
                artist_ids.append(existing["id"])
                continue

            await db.execute(
                """INSERT OR IGNORE INTO monitored_artists
                   (spotify_id, name, image_url, genres, followers, popularity,
                    monitored, monitor_new_releases)
                   VALUES (?, ?, ?, ?, ?, ?, 1, 1)""",
                (
                    sid, a.get("name", "Unknown"), a.get("image_url"),
                    _json.dumps(a.get("genres", [])),
                    a.get("followers", 0), a.get("popularity", 0),
                ),
            )
            await db.commit()
            cur = await db.execute(
                "SELECT id FROM monitored_artists WHERE spotify_id = ?", (sid,)
            )
            row = await cur.fetchone()
            if row:
                artist_ids.append(row["id"])
            added += 1

        await db.commit()
        return {"added": added, "already_monitored": already_monitored, "artist_ids": artist_ids}
    finally:
        await db.close()
