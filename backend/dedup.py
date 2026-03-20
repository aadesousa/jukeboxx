import logging
from database import get_db, get_setting
from rapidfuzz import fuzz

log = logging.getLogger("jukeboxx.dedup")


async def check_track_dedup(spotify_id: str, artist: str = "", title: str = "") -> tuple[bool, str]:
    """Check if a track should be skipped before downloading.
    Returns (should_skip, reason)."""
    db = await get_db()
    try:
        # 1. Check by spotify_id in tracks
        cur = await db.execute("SELECT id FROM tracks WHERE spotify_id = ? LIMIT 1", (spotify_id,))
        if await cur.fetchone():
            return True, "Already in local library (spotify_id match)"

        # 2. Check pending/active downloads
        cur = await db.execute(
            "SELECT id FROM downloads WHERE spotify_id = ? AND status IN ('pending', 'downloading') LIMIT 1",
            (spotify_id,),
        )
        if await cur.fetchone():
            return True, "Already queued for download"

        # 3. Fuzzy match artist + title
        if artist and title:
            threshold = int(await get_setting("fuzzy_threshold", "85"))
            # Try exact artist match first (fast), then broaden to title-based candidates
            cur = await db.execute(
                "SELECT artist, title FROM tracks WHERE artist = ? LIMIT 100",
                (artist,),
            )
            rows = await cur.fetchall()
            if not rows:
                # Fall back to prefix scan when no exact artist match
                cur = await db.execute(
                    """SELECT artist, title FROM tracks
                       WHERE artist LIKE ? OR title LIKE ?
                       LIMIT 200""",
                    (f"%{artist[:5]}%", f"%{title[:5]}%"),
                )
                rows = await cur.fetchall()
            query = f"{artist} {title}".lower()
            for row in rows:
                candidate = f"{row['artist'] or ''} {row['title'] or ''}".lower()
                score = fuzz.token_sort_ratio(query, candidate)
                if score >= threshold:
                    return True, f"Fuzzy match ({score}%): {row['artist']} - {row['title']}"

        return False, ""
    finally:
        await db.close()


async def bulk_dedup_check(tracks: list) -> dict:
    """Check multiple tracks for dedup. Returns categorized results."""
    to_download = []
    already_local = []
    already_queued = []
    fuzzy_matched = []

    for t in tracks:
        spotify_id = t.get("id", "")
        artist = ""
        if t.get("artists"):
            artist = t["artists"][0].get("name", "")
        title = t.get("name", "")

        skip, reason = await check_track_dedup(spotify_id, artist, title)
        if skip:
            if "local library" in reason:
                already_local.append(t)
            elif "queued" in reason:
                already_queued.append(t)
            else:
                fuzzy_matched.append(t)
        else:
            to_download.append(t)

    return {
        "to_download": len(to_download),
        "already_local": len(already_local),
        "already_queued": len(already_queued),
        "fuzzy_matched": len(fuzzy_matched),
        "tracks": to_download,
    }
