"""Monitored Albums API — Phase 2"""
import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends

from database import get_db

log = logging.getLogger("jukeboxx.albums")
router = APIRouter(prefix="/albums", tags=["albums"])


async def _get_sp():
    from spotify_auth import get_spotify_client
    sp = await get_spotify_client()
    if not sp:
        raise HTTPException(503, "Spotify not connected or rate-limited")
    return sp


# ── List Albums ───────────────────────────────────────────────────

@router.get("")
async def list_albums(
    artist_id: Optional[int] = None,
    status: Optional[str] = None,
    album_type: Optional[str] = None,
    sort: str = Query("release_date", regex="^(release_date|added|name)$"),
):
    db = await get_db()
    try:
        sql = """
            SELECT alb.*,
                   a.name as artist_name, a.image_url as artist_image,
                   COUNT(mt.id) as monitored_track_count,
                   SUM(CASE WHEN mt.status='have' THEN 1 ELSE 0 END) as have_count,
                   SUM(CASE WHEN mt.status='wanted' AND mt.monitored=1 THEN 1 ELSE 0 END) as missing_count
            FROM monitored_albums alb
            LEFT JOIN monitored_artists a ON a.id = alb.artist_id
            LEFT JOIN monitored_tracks mt ON mt.album_id = alb.id
        """
        where, params = [], []
        if artist_id is not None:
            where.append("alb.artist_id = ?")
            params.append(artist_id)
        if status:
            where.append("alb.status = ?")
            params.append(status)
        if album_type:
            where.append("alb.album_type = ?")
            params.append(album_type)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " GROUP BY alb.id"
        order_map = {
            "release_date": "ORDER BY alb.release_date DESC",
            "added":        "ORDER BY alb.added_at DESC",
            "name":         "ORDER BY alb.name COLLATE NOCASE ASC",
        }
        sql += " " + order_map.get(sort, order_map["release_date"])
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ── Get Album Detail ──────────────────────────────────────────────

@router.get("/{album_id}")
async def get_album(album_id: int):
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT alb.*, a.name as artist_name
               FROM monitored_albums alb
               LEFT JOIN monitored_artists a ON a.id = alb.artist_id
               WHERE alb.id = ?""",
            (album_id,),
        )
        album = await cur.fetchone()
        if not album:
            raise HTTPException(404, "Album not found")

        cur = await db.execute(
            "SELECT * FROM monitored_tracks WHERE album_id = ? ORDER BY disc_number, track_number",
            (album_id,),
        )
        tracks = await cur.fetchall()

        result = dict(album)
        result["tracks"] = [dict(t) for t in tracks]
        return result
    finally:
        await db.close()


# ── Update Album ──────────────────────────────────────────────────

@router.patch("/{album_id}")
async def update_album(album_id: int, body: dict):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id FROM monitored_albums WHERE id = ?", (album_id,)
        )
        if not await cur.fetchone():
            raise HTTPException(404, "Album not found")

        allowed = {"status", "monitored"}
        updates = {k: v for k, v in body.items() if k in allowed}
        if not updates:
            raise HTTPException(400, "No valid fields to update")

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [album_id]
        await db.execute(
            f"UPDATE monitored_albums SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            params,
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


# ── Fetch Tracks from Spotify ─────────────────────────────────────

@router.get("/{album_id}/tracks")
async def get_album_tracks_from_spotify(album_id: int):
    """Fetch track list from Spotify and store in monitored_tracks."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM monitored_albums WHERE id = ?", (album_id,)
        )
        album = await cur.fetchone()
        if not album:
            raise HTTPException(404, "Album not found")

        sp = await _get_sp()
        result = await asyncio.to_thread(sp.album_tracks, album["spotify_id"], limit=50)
        from spotify_auth import record_successful_call
        record_successful_call()

        tracks = result.get("items", [])
        while result.get("next"):
            result = await asyncio.to_thread(sp.next, result)
            record_successful_call()
            tracks.extend(result.get("items", []))

        artist_name = ""
        if tracks and tracks[0].get("artists"):
            artist_name = tracks[0]["artists"][0].get("name", "")

        added = 0
        for t in tracks:
            if not t:
                continue
            cur = await db.execute(
                "SELECT id FROM monitored_tracks WHERE spotify_id = ?", (t["id"],)
            )
            if not await cur.fetchone():
                t_artist = (t.get("artists") or [{}])[0].get("name", artist_name)
                await db.execute(
                    """INSERT INTO monitored_tracks
                       (spotify_id, album_id, artist_id, album_spotify_id, artist_spotify_id,
                        name, artist_name, album_name, track_number, disc_number, duration_ms)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        t["id"], album_id, album["artist_id"],
                        album["spotify_id"], album["artist_spotify_id"],
                        t["name"], t_artist, album["name"],
                        t.get("track_number"), t.get("disc_number", 1),
                        t.get("duration_ms"),
                    ),
                )
                added += 1

        # Update album track_count
        await db.execute(
            "UPDATE monitored_albums SET track_count = ? WHERE id = ?",
            (len(tracks), album_id),
        )
        await db.commit()

        # Immediately check if any newly added tracks are already in the local library
        if added > 0:
            import asyncio as _asyncio
            async def _bg_match():
                from matcher import match_local_to_monitored
                await match_local_to_monitored()
            _asyncio.create_task(_bg_match())

        return {"added": added, "total": len(tracks)}
    finally:
        await db.close()


# ── Bulk Import ───────────────────────────────────────────────────

@router.post("/bulk")
async def bulk_add_albums(body: dict):
    """Add multiple albums at once (from import wizard)."""
    spotify_ids = body.get("spotify_ids", [])
    artist_id = body.get("artist_id")
    if not spotify_ids:
        raise HTTPException(400, "spotify_ids required")

    db = await get_db()
    try:
        sp = await _get_sp()
        from spotify_auth import record_successful_call

        added, skipped = 0, 0
        for chunk_start in range(0, len(spotify_ids), 20):
            chunk = spotify_ids[chunk_start:chunk_start + 20]
            results = await asyncio.to_thread(sp.albums, chunk)
            record_successful_call()
            for alb in results.get("albums", []):
                if not alb:
                    continue
                cur = await db.execute(
                    "SELECT id FROM monitored_albums WHERE spotify_id = ?", (alb["id"],)
                )
                if await cur.fetchone():
                    skipped += 1
                    continue
                # Try to find artist_id by spotify_id
                alb_artist_spotify_id = (alb.get("artists") or [{}])[0].get("id", "")
                a_id = artist_id
                if not a_id and alb_artist_spotify_id:
                    cur = await db.execute(
                        "SELECT id FROM monitored_artists WHERE spotify_id = ?",
                        (alb_artist_spotify_id,),
                    )
                    row = await cur.fetchone()
                    if row:
                        a_id = row["id"]
                image_url = (alb.get("images") or [{}])[0].get("url")
                await db.execute(
                    """INSERT INTO monitored_albums
                       (spotify_id, artist_id, artist_spotify_id, name, album_type,
                        release_date, release_date_precision, track_count, image_url, label)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        alb["id"], a_id, alb_artist_spotify_id,
                        alb["name"], alb.get("album_type", "album"),
                        alb.get("release_date"), alb.get("release_date_precision"),
                        alb.get("total_tracks", 0), image_url,
                        alb.get("label"),
                    ),
                )
                added += 1

        await db.commit()
        return {"added": added, "skipped": skipped}
    finally:
        await db.close()


# ── Album Command ─────────────────────────────────────────────────

@router.post("/{album_id}/command")
async def album_command(album_id: int, body: dict):
    command = body.get("command")
    db = await get_db()
    try:
        if command in ("search-missing", "search-monitored"):
            cur = await db.execute(
                "SELECT id FROM monitored_tracks WHERE album_id=? AND status='wanted'",
                (album_id,)
            )
            tracks = await cur.fetchall()
            if not tracks:
                await db.execute(
                    "UPDATE monitored_tracks SET status='wanted' WHERE album_id=? AND status NOT IN ('have','ignored')",
                    (album_id,)
                )
                await db.commit()
                cur = await db.execute(
                    "SELECT id FROM monitored_tracks WHERE album_id=? AND status='wanted'",
                    (album_id,)
                )
                tracks = await cur.fetchall()
            from tasks import run_multi_source_dispatch
            result = await run_multi_source_dispatch(limit=len(tracks) or 10)
            return {"ok": True, "queued": result.get("dispatched", 0), "breakdown": result.get("breakdown", {})}
        elif command == "mark-wanted":
            await db.execute(
                "UPDATE monitored_tracks SET status='wanted' WHERE album_id=? AND status NOT IN ('have','ignored')",
                (album_id,)
            )
            await db.commit()
            cur = await db.execute(
                "SELECT COUNT(*) as n FROM monitored_tracks WHERE album_id=? AND status='wanted'",
                (album_id,)
            )
            row = await cur.fetchone()
            return {"ok": True, "marked": row["n"]}
        else:
            raise HTTPException(status_code=400, detail=f"Unknown command: {command}")
    finally:
        await db.close()
