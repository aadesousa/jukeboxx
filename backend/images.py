"""
Non-Spotify image fetching using Deezer public API.
Deezer requires no API key and provides high-quality images.
"""
import httpx
import asyncio
import logging

log = logging.getLogger("jukeboxx.images")

DEEZER_BASE = "https://api.deezer.com"


async def get_artist_image(artist_name: str) -> str | None:
    """Fetch artist image URL from Deezer. Returns picture_xl URL or None."""
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{DEEZER_BASE}/search/artist",
                            params={"q": artist_name, "limit": 3})
            if r.status_code == 200:
                data = r.json().get("data", [])
                for item in data:
                    url = item.get("picture_xl") or item.get("picture_big") or item.get("picture")
                    if url and "default" not in url:  # skip placeholder images
                        return url
    except Exception as e:
        log.debug(f"Deezer artist image error for '{artist_name}': {e}")
    return None


async def get_album_cover(artist_name: str, album_name: str) -> str | None:
    """Fetch album cover URL from Deezer. Returns cover_xl URL or None."""
    try:
        query = f"{artist_name} {album_name}"
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{DEEZER_BASE}/search/album",
                            params={"q": query, "limit": 3})
            if r.status_code == 200:
                data = r.json().get("data", [])
                for item in data:
                    url = item.get("cover_xl") or item.get("cover_big") or item.get("cover")
                    if url and "default" not in url:
                        return url
    except Exception as e:
        log.debug(f"Deezer album cover error for '{artist_name} - {album_name}': {e}")
    return None


async def get_track_cover(artist_name: str, track_name: str) -> str | None:
    """Fetch track/album art from Deezer track search."""
    try:
        query = f"{artist_name} {track_name}"
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{DEEZER_BASE}/search",
                            params={"q": query, "limit": 3})
            if r.status_code == 200:
                data = r.json().get("data", [])
                for item in data:
                    album = item.get("album", {})
                    url = album.get("cover_xl") or album.get("cover_big") or album.get("cover")
                    if url and "default" not in url:
                        return url
    except Exception as e:
        log.debug(f"Deezer track cover error: {e}")
    return None


async def backfill_artist_images(batch_size: int = 10) -> int:
    """Fetch Deezer images for all monitored_artists missing image_url.
    Rate-limited to avoid hammering Deezer. Returns count updated."""
    from database import get_db
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, name FROM monitored_artists WHERE (image_url IS NULL OR image_url = '') LIMIT ?",
            (batch_size,)
        )
        artists = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()

    if not artists:
        return 0

    updated = 0
    for artist in artists:
        img = await get_artist_image(artist["name"])
        if img:
            db = await get_db()
            try:
                await db.execute(
                    "UPDATE monitored_artists SET image_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (img, artist["id"])
                )
                await db.commit()
                updated += 1
            finally:
                await db.close()
        await asyncio.sleep(0.5)  # gentle rate limit

    return updated


async def backfill_album_covers(batch_size: int = 20) -> int:
    """Fetch Deezer covers for all monitored_albums missing image_url."""
    from database import get_db
    db = await get_db()
    try:
        cur = await db.execute("""
            SELECT ma.id, ma.name, ar.name as artist_name
            FROM monitored_albums ma
            LEFT JOIN monitored_artists ar ON ma.artist_id = ar.id
            WHERE (ma.image_url IS NULL OR ma.image_url = '')
            LIMIT ?
        """, (batch_size,))
        albums = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()

    if not albums:
        return 0

    updated = 0
    for album in albums:
        img = await get_album_cover(album.get("artist_name", ""), album["name"])
        if img:
            db = await get_db()
            try:
                await db.execute(
                    "UPDATE monitored_albums SET image_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (img, album["id"])
                )
                await db.commit()
                updated += 1
            finally:
                await db.close()
        await asyncio.sleep(0.3)

    return updated
