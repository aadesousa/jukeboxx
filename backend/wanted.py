"""
Wanted system — track artists and albums you want to collect.
Provides routes for managing wanted artists/albums and checking coverage.
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db, add_activity, add_notification

log = logging.getLogger("jukeboxx.wanted")
router = APIRouter(prefix="/wanted", tags=["wanted"])


# ─── Models ────────────────────────────────────────────────────────────────────

class WantedArtistIn(BaseModel):
    spotify_id: str
    name: str
    image_url: Optional[str] = None
    genres: Optional[list[str]] = None
    monitor_new_albums: bool = True


class WantedAlbumIn(BaseModel):
    spotify_id: str
    artist_spotify_id: str
    name: str
    album_type: Optional[str] = None
    release_date: Optional[str] = None
    track_count: int = 0
    image_url: Optional[str] = None


class WantedAlbumStatusUpdate(BaseModel):
    status: str  # wanted | ignored


class WantedArtistUpdate(BaseModel):
    monitor_new_albums: Optional[bool] = None


# ─── Artists ───────────────────────────────────────────────────────────────────

@router.get("/artists")
async def list_wanted_artists():
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM wanted_artists ORDER BY name ASC"
        )
        artists = [dict(r) for r in await cur.fetchall()]
        # Attach album stats per artist
        for a in artists:
            cur2 = await db.execute(
                "SELECT status, COUNT(*) as cnt FROM wanted_albums WHERE artist_spotify_id=? GROUP BY status",
                (a["spotify_id"],)
            )
            stats = {r["status"]: r["cnt"] for r in await cur2.fetchall()}
            a["album_stats"] = stats
            a["genres"] = json.loads(a["genres"]) if a.get("genres") else []
        return artists
    finally:
        await db.close()


@router.post("/artists")
async def add_wanted_artist(body: WantedArtistIn):
    db = await get_db()
    try:
        genres_json = json.dumps(body.genres or [])
        await db.execute(
            """INSERT INTO wanted_artists (spotify_id, name, image_url, genres, monitor_new_albums)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(spotify_id) DO UPDATE SET
                 name=excluded.name, image_url=excluded.image_url,
                 genres=excluded.genres, monitor_new_albums=excluded.monitor_new_albums""",
            (body.spotify_id, body.name, body.image_url, genres_json, int(body.monitor_new_albums))
        )
        await db.commit()
        await add_activity("wanted_artist_added", f"Added {body.name} to Wanted")
        return {"ok": True}
    finally:
        await db.close()


@router.patch("/artists/{spotify_id}")
async def update_wanted_artist(spotify_id: str, body: WantedArtistUpdate):
    db = await get_db()
    try:
        if body.monitor_new_albums is not None:
            await db.execute(
                "UPDATE wanted_artists SET monitor_new_albums=? WHERE spotify_id=?",
                (int(body.monitor_new_albums), spotify_id)
            )
            await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.delete("/artists/{spotify_id}")
async def remove_wanted_artist(spotify_id: str):
    db = await get_db()
    try:
        await db.execute("DELETE FROM wanted_artists WHERE spotify_id=?", (spotify_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.get("/artists/{spotify_id}/coverage")
async def artist_coverage(spotify_id: str):
    """Returns per-album coverage: how many tracks are local vs total."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM wanted_albums WHERE artist_spotify_id=? ORDER BY release_date DESC",
            (spotify_id,)
        )
        albums = [dict(r) for r in await cur.fetchall()]
        result = []
        for alb in albums:
            # Count tracks in local library matching this album spotify_id
            # We key on album name since we don't store album_spotify_id on tracks
            cur2 = await db.execute(
                "SELECT COUNT(*) as cnt FROM tracks WHERE album=? COLLATE NOCASE",
                (alb["name"],)
            )
            row = await cur2.fetchone()
            local_count = row["cnt"] if row else 0
            result.append({
                **alb,
                "local_count": local_count,
                "coverage_pct": round(local_count / alb["track_count"] * 100, 1) if alb["track_count"] else 0,
            })
        return result
    finally:
        await db.close()


@router.get("/missing")
async def get_missing_summary():
    """Badge counts: missing albums + wanted tracks from monitored tables."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COUNT(*) as cnt FROM monitored_albums WHERE status != 'have' AND status != 'ignored' AND monitored = 1"
        )
        missing_albums = (await cur.fetchone())["cnt"] or 0

        cur = await db.execute(
            "SELECT COUNT(*) as cnt FROM monitored_tracks WHERE status = 'wanted' AND monitored = 1"
        )
        missing_tracks = (await cur.fetchone())["cnt"] or 0

        return {"missing_albums": missing_albums, "missing_tracks": missing_tracks}
    finally:
        await db.close()


@router.get("/summary")
async def get_wanted_summary():
    """Full summary for Wanted page header."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COUNT(*) as cnt FROM monitored_albums WHERE status != 'have' AND status != 'ignored' AND monitored = 1"
        )
        missing_albums = (await cur.fetchone())["cnt"] or 0

        cur = await db.execute(
            "SELECT COUNT(*) as cnt FROM monitored_tracks WHERE status = 'wanted' AND monitored = 1"
        )
        missing_tracks = (await cur.fetchone())["cnt"] or 0

        cur = await db.execute(
            "SELECT COUNT(*) as cnt FROM monitored_tracks WHERE status = 'downloading' AND monitored = 1"
        )
        downloading = (await cur.fetchone())["cnt"] or 0

        cur = await db.execute(
            "SELECT COUNT(*) as cnt FROM unified_downloads WHERE status = 'failed'"
        )
        failed = (await cur.fetchone())["cnt"] or 0

        return {
            "missing_albums": missing_albums,
            "missing_tracks": missing_tracks,
            "downloading":    downloading,
            "failed":         failed,
        }
    finally:
        await db.close()


@router.get("/missing-albums")
async def list_missing_albums(
    artist_id: Optional[int] = None,
    album_type: Optional[str] = None,
    sort: str = "release_date",
    offset: int = 0,
    limit: int = 100,
):
    """All monitored albums that aren't fully in the library."""
    db = await get_db()
    try:
        sql = """
            SELECT alb.*,
                   a.name  AS artist_name,
                   a.id    AS artist_db_id,
                   a.image_url AS artist_image
            FROM monitored_albums alb
            LEFT JOIN monitored_artists a ON a.id = alb.artist_id
            WHERE alb.status != 'have'
              AND alb.status != 'ignored'
              AND alb.monitored = 1
        """
        params = []
        if artist_id:
            sql += " AND alb.artist_id = ?"
            params.append(artist_id)
        if album_type:
            sql += " AND alb.album_type = ?"
            params.append(album_type)

        order_map = {
            "release_date": "ORDER BY alb.release_date DESC",
            "artist":       "ORDER BY a.name COLLATE NOCASE, alb.release_date DESC",
            "added":        "ORDER BY alb.added_at DESC",
        }
        sql += " " + order_map.get(sort, order_map["release_date"])
        sql += " LIMIT ? OFFSET ?"
        params += [limit, offset]

        cur = await db.execute(sql, params)
        rows = await cur.fetchall()

        count_sql = """
            SELECT COUNT(*) as cnt FROM monitored_albums alb
            WHERE alb.status != 'have' AND alb.status != 'ignored' AND alb.monitored = 1
        """
        count_params = []
        if artist_id:
            count_sql += " AND alb.artist_id = ?"; count_params.append(artist_id)
        if album_type:
            count_sql += " AND alb.album_type = ?"; count_params.append(album_type)
        cur = await db.execute(count_sql, count_params)
        total = (await cur.fetchone())["cnt"] or 0

        return {"items": [dict(r) for r in rows], "total": total, "offset": offset, "limit": limit}
    finally:
        await db.close()


@router.get("/missing-tracks")
async def list_missing_tracks(
    artist_id:           Optional[int] = None,
    album_id:            Optional[int] = None,
    sort:                str = "artist",
    offset:              int = 0,
    limit:               int = 200,
):
    """All individually monitored tracks with status 'wanted'."""
    db = await get_db()
    try:
        sql = """
            SELECT mt.*,
                   a.name    AS artist_display,
                   alb.name  AS album_display,
                   alb.image_url AS album_image
            FROM monitored_tracks mt
            LEFT JOIN monitored_artists a   ON a.id   = mt.artist_id
            LEFT JOIN monitored_albums  alb ON alb.id = mt.album_id
            WHERE mt.status = 'wanted' AND mt.monitored = 1
              AND TRIM(COALESCE(mt.name,'')) != ''
        """
        params = []
        if artist_id:
            sql += " AND mt.artist_id = ?"; params.append(artist_id)
        if album_id:
            sql += " AND mt.album_id = ?"; params.append(album_id)

        order_map = {
            "artist": "ORDER BY mt.status ASC, a.name COLLATE NOCASE, alb.name, mt.disc_number, mt.track_number",
            "added":  "ORDER BY mt.status ASC, mt.added_at DESC",
            "name":   "ORDER BY mt.status ASC, mt.name COLLATE NOCASE",
        }
        sql += " " + order_map.get(sort, order_map["artist"])
        sql += " LIMIT ? OFFSET ?"
        params += [limit, offset]

        cur = await db.execute(sql, params)
        rows = await cur.fetchall()

        count_sql = "SELECT COUNT(*) as cnt FROM monitored_tracks mt WHERE mt.status='wanted' AND mt.monitored=1 AND TRIM(COALESCE(mt.name,''))!=''"
        count_params = []
        if artist_id:
            count_sql += " AND mt.artist_id = ?"; count_params.append(artist_id)
        if album_id:
            count_sql += " AND mt.album_id = ?"; count_params.append(album_id)
        cur = await db.execute(count_sql, count_params)
        total = (await cur.fetchone())["cnt"] or 0

        return {"items": [dict(r) for r in rows], "total": total, "offset": offset, "limit": limit}
    finally:
        await db.close()


@router.patch("/missing-albums/{album_id}")
async def update_missing_album(album_id: int, body: dict):
    status = body.get("status")
    if status not in ("wanted", "ignored", "have"):
        raise HTTPException(400, "status must be: wanted, ignored, or have")
    db = await get_db()
    try:
        await db.execute(
            "UPDATE monitored_albums SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, album_id)
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.patch("/missing-tracks/{track_id}")
async def update_missing_track(track_id: int, body: dict):
    status = body.get("status")
    if status not in ("wanted", "ignored", "have", "downloading"):
        raise HTTPException(400, "invalid status")
    db = await get_db()
    try:
        await db.execute(
            "UPDATE monitored_tracks SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, track_id)
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


# ─── Albums ────────────────────────────────────────────────────────────────────

@router.get("/albums")
async def list_wanted_albums(
    artist_spotify_id: Optional[str] = None,
    status: Optional[str] = None
):
    db = await get_db()
    try:
        conditions = []
        params = []
        if artist_spotify_id:
            conditions.append("artist_spotify_id=?")
            params.append(artist_spotify_id)
        if status:
            conditions.append("status=?")
            params.append(status)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        cur = await db.execute(
            f"SELECT * FROM wanted_albums {where} ORDER BY release_date DESC",
            params
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


@router.post("/albums")
async def add_wanted_album(body: WantedAlbumIn):
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO wanted_albums
               (spotify_id, artist_spotify_id, name, album_type, release_date, track_count, image_url)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(spotify_id) DO UPDATE SET
                 name=excluded.name, album_type=excluded.album_type,
                 release_date=excluded.release_date, track_count=excluded.track_count,
                 image_url=excluded.image_url""",
            (body.spotify_id, body.artist_spotify_id, body.name, body.album_type,
             body.release_date, body.track_count, body.image_url)
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.patch("/albums/{spotify_id}")
async def update_album_status(spotify_id: str, body: WantedAlbumStatusUpdate):
    if body.status not in ("wanted", "ignored", "have"):
        raise HTTPException(400, "status must be: wanted, ignored, or have")
    db = await get_db()
    try:
        await db.execute(
            "UPDATE wanted_albums SET status=? WHERE spotify_id=?",
            (body.status, spotify_id)
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.delete("/albums/{spotify_id}")
async def remove_wanted_album(spotify_id: str):
    db = await get_db()
    try:
        await db.execute("DELETE FROM wanted_albums WHERE spotify_id=?", (spotify_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.post("/albums/bulk")
async def bulk_add_albums(albums: list[WantedAlbumIn]):
    """Add multiple albums at once (used when adding an artist)."""
    db = await get_db()
    try:
        for body in albums:
            await db.execute(
                """INSERT INTO wanted_albums
                   (spotify_id, artist_spotify_id, name, album_type, release_date, track_count, image_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(spotify_id) DO UPDATE SET
                     name=excluded.name, release_date=excluded.release_date,
                     track_count=excluded.track_count, image_url=excluded.image_url""",
                (body.spotify_id, body.artist_spotify_id, body.name, body.album_type,
                 body.release_date, body.track_count, body.image_url)
            )
        await db.commit()
        return {"ok": True, "count": len(albums)}
    finally:
        await db.close()
