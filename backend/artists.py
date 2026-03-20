"""Monitored Artists API — Phase 2"""
import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from database import get_db

log = logging.getLogger("jukeboxx.artists")
router = APIRouter(prefix="/artists", tags=["artists"])


def _parse_artist(row) -> dict:
    d = dict(row)
    try:
        d["genres"] = json.loads(d.get("genres") or "[]")
    except Exception:
        d["genres"] = []
    return d


async def _get_sp():
    from spotify_auth import get_spotify_client
    sp = await get_spotify_client()
    if not sp:
        raise HTTPException(503, "Spotify not connected or rate-limited")
    return sp


# ── List / Search ─────────────────────────────────────────────────

@router.get("")
async def list_artists(
    monitored: Optional[bool] = None,
    sort: str = Query("name", regex="^(name|added|missing)$"),
    q: Optional[str] = None,
):
    db = await get_db()
    try:
        sql = """
            SELECT a.*,
                   COUNT(DISTINCT alb.id) as album_count,
                   COUNT(DISTINCT mt.id) as track_count,
                   COUNT(DISTINCT CASE WHEN mt.status = 'wanted' AND mt.monitored = 1 THEN mt.id END) as missing_count
            FROM monitored_artists a
            LEFT JOIN monitored_albums alb ON alb.artist_id = a.id AND alb.monitored = 1
            LEFT JOIN monitored_tracks mt ON mt.artist_id = a.id AND mt.monitored = 1
        """
        where, params = [], []
        if monitored is not None:
            where.append("a.monitored = ?")
            params.append(1 if monitored else 0)
        if q:
            where.append("a.name LIKE ?")
            params.append(f"%{q}%")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " GROUP BY a.id"
        order_map = {
            "name":    "ORDER BY a.name COLLATE NOCASE ASC",
            "added":   "ORDER BY a.added_at DESC",
            "missing": "ORDER BY missing_count DESC, a.name COLLATE NOCASE ASC",
        }
        sql += " " + order_map.get(sort, order_map["name"])
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
        return [_parse_artist(r) for r in rows]
    finally:
        await db.close()


@router.get("/search")
async def search_artists(q: str = Query(..., min_length=1)):
    """Search Spotify for artists to add."""
    sp = await _get_sp()
    results = await asyncio.to_thread(sp.search, q, type="artist", limit=20)
    from spotify_auth import record_successful_call
    record_successful_call()
    artists = results.get("artists", {}).get("items", [])
    return [
        {
            "spotify_id": a["id"],
            "name": a["name"],
            "image_url": (a.get("images") or [{}])[0].get("url"),
            "genres": a.get("genres", []),
            "followers": a.get("followers", {}).get("total", 0),
            "popularity": a.get("popularity", 0),
        }
        for a in artists if a
    ]


# ── Add Artist ────────────────────────────────────────────────────

@router.post("")
async def add_artist(body: dict):
    """Add artist by spotify_id. Fetches metadata from Spotify."""
    spotify_id = body.get("spotify_id")
    if not spotify_id:
        raise HTTPException(400, "spotify_id required")

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id FROM monitored_artists WHERE spotify_id = ?", (spotify_id,)
        )
        if await cur.fetchone():
            raise HTTPException(409, "Artist already monitored")

        sp = await _get_sp()
        artist_data = await asyncio.to_thread(sp.artist, spotify_id)
        from spotify_auth import record_successful_call
        record_successful_call()

        image_url = (artist_data.get("images") or [{}])[0].get("url")
        genres = json.dumps(artist_data.get("genres", []))
        followers = artist_data.get("followers", {}).get("total", 0)
        popularity = artist_data.get("popularity", 0)
        monitored = 1 if body.get("monitored", True) else 0
        monitor_new = 1 if body.get("monitor_new_releases", True) else 0
        quality_profile_id = body.get("quality_profile_id")

        await db.execute(
            """INSERT INTO monitored_artists
               (spotify_id, name, image_url, genres, followers, popularity,
                monitored, monitor_new_releases, quality_profile_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (spotify_id, artist_data.get("name", "Unknown"), image_url,
             genres, followers, popularity, monitored, monitor_new, quality_profile_id),
        )
        await db.commit()
        cur = await db.execute("SELECT last_insert_rowid() as id")
        artist_id = (await cur.fetchone())["id"]
        return {"id": artist_id, "spotify_id": spotify_id, "name": artist_data.get("name")}
    finally:
        await db.close()


# ── Get / Update / Delete ─────────────────────────────────────────

@router.get("/{artist_id}")
async def get_artist(artist_id: int):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM monitored_artists WHERE id = ?", (artist_id,)
        )
        artist = await cur.fetchone()
        if not artist:
            raise HTTPException(404, "Artist not found")

        cur = await db.execute(
            "SELECT * FROM monitored_albums WHERE artist_id = ? ORDER BY release_date DESC",
            (artist_id,),
        )
        albums = await cur.fetchall()

        # Track coverage stats
        cur = await db.execute(
            """SELECT
                 COUNT(*) as total,
                 SUM(CASE WHEN status='have' THEN 1 ELSE 0 END) as have,
                 SUM(CASE WHEN status='wanted' AND monitored=1 THEN 1 ELSE 0 END) as missing
               FROM monitored_tracks WHERE artist_id = ?""",
            (artist_id,),
        )
        stats = await cur.fetchone()

        result = _parse_artist(artist)
        result["albums"] = [dict(a) for a in albums]
        result["stats"] = dict(stats) if stats else {}
        return result
    finally:
        await db.close()


@router.patch("/{artist_id}")
async def update_artist(artist_id: int, body: dict):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id FROM monitored_artists WHERE id = ?", (artist_id,)
        )
        if not await cur.fetchone():
            raise HTTPException(404, "Artist not found")

        allowed = {"monitored", "monitor_new_releases", "quality_profile_id"}
        updates = {k: v for k, v in body.items() if k in allowed}
        if not updates:
            raise HTTPException(400, "No valid fields to update")

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [artist_id]
        await db.execute(
            f"UPDATE monitored_artists SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            params,
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.delete("/{artist_id}")
async def delete_artist(artist_id: int):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id FROM monitored_artists WHERE id = ?", (artist_id,)
        )
        if not await cur.fetchone():
            raise HTTPException(404, "Artist not found")
        await db.execute("DELETE FROM monitored_artists WHERE id = ?", (artist_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


# ── Refresh Discography ───────────────────────────────────────────

@router.post("/{artist_id}/refresh")
async def refresh_artist(artist_id: int):
    """Re-fetch discography from Spotify, insert any new albums."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM monitored_artists WHERE id = ?", (artist_id,)
        )
        artist = await cur.fetchone()
        if not artist:
            raise HTTPException(404, "Artist not found")

        sp = await _get_sp()
        # Fetch all album types
        album_types = "album,single,ep,compilation"
        result = await asyncio.to_thread(
            sp.artist_albums, artist["spotify_id"], album_type=album_types, limit=50
        )
        from spotify_auth import record_successful_call
        record_successful_call()

        albums = result.get("items", [])
        # Paginate if needed
        while result.get("next"):
            result = await asyncio.to_thread(sp.next, result)
            record_successful_call()
            albums.extend(result.get("items", []))

        added = 0
        for alb in albums:
            cur = await db.execute(
                "SELECT id FROM monitored_albums WHERE spotify_id = ?", (alb["id"],)
            )
            if not await cur.fetchone():
                image_url = (alb.get("images") or [{}])[0].get("url")
                await db.execute(
                    """INSERT INTO monitored_albums
                       (spotify_id, artist_id, artist_spotify_id, name, album_type,
                        release_date, release_date_precision, track_count, image_url)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        alb["id"], artist_id, artist["spotify_id"],
                        alb["name"], alb.get("album_type", "album"),
                        alb.get("release_date"), alb.get("release_date_precision"),
                        alb.get("total_tracks", 0), image_url,
                    ),
                )
                added += 1

        # Also refresh artist metadata from Spotify
        artist_data = await asyncio.to_thread(sp.artist, artist["spotify_id"])
        record_successful_call()
        image_url = (artist_data.get("images") or [{}])[0].get("url")
        # Fallback to Deezer if Spotify returned no image
        if not image_url:
            from images import get_artist_image
            image_url = await get_artist_image(artist_data.get("name", artist["name"]))
        genres = json.dumps(artist_data.get("genres", []))
        followers = artist_data.get("followers", {}).get("total", 0)
        popularity = artist_data.get("popularity", 0)
        name = artist_data.get("name", artist["name"])
        await db.execute(
            """UPDATE monitored_artists
               SET image_url=?, genres=?, followers=?, popularity=?, name=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (image_url, genres, followers, popularity, name, artist_id),
        )

        await db.commit()
        return {"added": added, "total": len(albums)}
    finally:
        await db.close()


@router.post("/refresh-all-metadata")
async def refresh_all_metadata():
    """Fetch images for all artists with missing image_url using Deezer (no Spotify quota used)."""
    from images import backfill_artist_images
    updated = await backfill_artist_images(batch_size=32)
    return {"updated": updated}


@router.post("/{artist_id}/command")
async def artist_command(artist_id: int, body: dict):
    command = body.get("command")
    db = await get_db()
    try:
        if command == "download-missing":
            await db.execute(
                """UPDATE monitored_tracks SET status='wanted'
                   WHERE album_id IN (
                       SELECT id FROM monitored_albums WHERE artist_id=?
                   ) AND status NOT IN ('have','ignored')""",
                (artist_id,)
            )
            await db.commit()
            cur = await db.execute(
                """SELECT COUNT(*) as n FROM monitored_tracks
                   WHERE album_id IN (
                       SELECT id FROM monitored_albums WHERE artist_id=?
                   ) AND status='wanted'""",
                (artist_id,)
            )
            wanted = (await cur.fetchone())["n"]
            from tasks import run_multi_source_dispatch
            result = await run_multi_source_dispatch(limit=min(wanted, 50))
            return {"ok": True, "queued": result.get("dispatched", 0), "breakdown": result.get("breakdown", {})}
        else:
            raise HTTPException(status_code=400, detail=f"Unknown command: {command}")
    finally:
        await db.close()
