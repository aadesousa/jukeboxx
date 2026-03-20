"""Monitored Tracks API — Phase 2"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from database import get_db

log = logging.getLogger("jukeboxx.monitored_tracks")
router = APIRouter(prefix="/monitored-tracks", tags=["tracks"])


@router.get("")
async def list_monitored_tracks(
    artist_id: Optional[int] = None,
    album_id: Optional[int] = None,
    status: Optional[str] = None,
    monitored: Optional[bool] = None,
    q: Optional[str] = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    db = await get_db()
    try:
        sql = """
            SELECT mt.*,
                   a.name as artist_display_name,
                   alb.name as album_display_name, alb.image_url as album_image
            FROM monitored_tracks mt
            LEFT JOIN monitored_artists a ON a.id = mt.artist_id
            LEFT JOIN monitored_albums alb ON alb.id = mt.album_id
        """
        where, params = [], []
        if artist_id is not None:
            where.append("mt.artist_id = ?")
            params.append(artist_id)
        if album_id is not None:
            where.append("mt.album_id = ?")
            params.append(album_id)
        if status:
            where.append("mt.status = ?")
            params.append(status)
        if monitored is not None:
            where.append("mt.monitored = ?")
            params.append(1 if monitored else 0)
        if q:
            where.append("(mt.name LIKE ? OR mt.artist_name LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY mt.artist_name COLLATE NOCASE, mt.album_name, mt.disc_number, mt.track_number"
        sql += " LIMIT ? OFFSET ?"
        params += [limit, offset]

        cur = await db.execute(sql, params)
        rows = await cur.fetchall()

        # Total count for pagination
        count_sql = "SELECT COUNT(*) as c FROM monitored_tracks mt"
        if where:
            count_sql += " WHERE " + " AND ".join(where)
        cur = await db.execute(count_sql, params[:-2])  # exclude limit/offset
        total = (await cur.fetchone())["c"]

        return {"total": total, "offset": offset, "limit": limit, "items": [dict(r) for r in rows]}
    finally:
        await db.close()


@router.patch("/{track_id}")
async def update_track(track_id: int, body: dict):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id FROM monitored_tracks WHERE id = ?", (track_id,)
        )
        if not await cur.fetchone():
            raise HTTPException(404, "Track not found")

        allowed = {"monitored", "status"}
        updates = {k: v for k, v in body.items() if k in allowed}
        if not updates:
            raise HTTPException(400, "No valid fields to update")

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [track_id]
        await db.execute(
            f"UPDATE monitored_tracks SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            params,
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.delete("/{track_id}")
async def delete_track(track_id: int):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id FROM monitored_tracks WHERE id = ?", (track_id,)
        )
        if not await cur.fetchone():
            raise HTTPException(404, "Track not found")
        await db.execute("DELETE FROM monitored_tracks WHERE id = ?", (track_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


# ── Import Tracks (from Spotify library) ─────────────────────────

@router.post("/import")
async def import_tracks(body: dict):
    """Bulk import tracks from Spotify. Creates artist/album entries if missing."""
    tracks = body.get("tracks", [])
    if not tracks:
        raise HTTPException(400, "tracks list required")

    db = await get_db()
    try:
        added, skipped, already_monitored = 0, 0, 0

        for t in tracks:
            spotify_id = t.get("spotify_id") or t.get("id")
            if not spotify_id:
                skipped += 1
                continue

            # Check already monitored
            cur = await db.execute(
                "SELECT id FROM monitored_tracks WHERE spotify_id = ?", (spotify_id,)
            )
            if await cur.fetchone():
                already_monitored += 1
                continue

            # Ensure artist exists
            artist_id = None
            artist_spotify_id = t.get("artist_spotify_id")
            if artist_spotify_id:
                cur = await db.execute(
                    "SELECT id FROM monitored_artists WHERE spotify_id = ?",
                    (artist_spotify_id,),
                )
                row = await cur.fetchone()
                if row:
                    artist_id = row["id"]
                elif t.get("artist_name"):
                    await db.execute(
                        """INSERT OR IGNORE INTO monitored_artists
                           (spotify_id, name, image_url, monitored, monitor_new_releases)
                           VALUES (?, ?, ?, 1, 0)""",
                        (artist_spotify_id, t["artist_name"], t.get("artist_image")),
                    )
                    await db.commit()
                    cur = await db.execute(
                        "SELECT id FROM monitored_artists WHERE spotify_id = ?",
                        (artist_spotify_id,),
                    )
                    row = await cur.fetchone()
                    if row:
                        artist_id = row["id"]

            # Ensure album exists
            album_id = None
            album_spotify_id = t.get("album_spotify_id")
            if album_spotify_id:
                cur = await db.execute(
                    "SELECT id FROM monitored_albums WHERE spotify_id = ?",
                    (album_spotify_id,),
                )
                row = await cur.fetchone()
                if row:
                    album_id = row["id"]
                elif t.get("album_name"):
                    await db.execute(
                        """INSERT OR IGNORE INTO monitored_albums
                           (spotify_id, artist_id, artist_spotify_id, name, image_url, monitored)
                           VALUES (?, ?, ?, ?, ?, 1)""",
                        (album_spotify_id, artist_id, artist_spotify_id or "",
                         t["album_name"], t.get("album_image")),
                    )
                    await db.commit()
                    cur = await db.execute(
                        "SELECT id FROM monitored_albums WHERE spotify_id = ?",
                        (album_spotify_id,),
                    )
                    row = await cur.fetchone()
                    if row:
                        album_id = row["id"]

            await db.execute(
                """INSERT OR IGNORE INTO monitored_tracks
                   (spotify_id, album_id, artist_id, album_spotify_id, artist_spotify_id,
                    name, artist_name, album_name, track_number, disc_number, duration_ms, image_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    spotify_id, album_id, artist_id,
                    t.get("album_spotify_id"), t.get("artist_spotify_id"),
                    t.get("name", "Unknown"), t.get("artist_name"), t.get("album_name"),
                    t.get("track_number"), t.get("disc_number", 1), t.get("duration_ms"),
                    t.get("image_url"),
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
