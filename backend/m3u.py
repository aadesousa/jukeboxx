import os
import logging
from pathlib import Path

from rapidfuzz import fuzz
from database import get_db, get_setting
from spotify_client import get_client, get_all_playlist_tracks

log = logging.getLogger("jukeboxx.m3u")

MUSIC_PATH = os.environ.get("MUSIC_PATH", "/music")
PLAYLIST_PATH = os.environ.get("PLAYLIST_PATH", "/music/Playlists")


async def _find_local_path(db, spotify_id: str, artist: str, title: str,
                            fuzzy_threshold: int, album: str = "") -> dict | None:
    """Find a local track by spotify_id first, then fuzzy artist+title match."""
    from matcher import version_penalty

    spotify_ref = f"{artist} {title} {album}".strip()

    # Step 0: check monitored_tracks.local_path — set immediately when download completes
    if spotify_id:
        cur = await db.execute(
            """SELECT mt.local_path AS path, t.artist, t.title, t.duration, t.album
               FROM monitored_tracks mt
               LEFT JOIN tracks t ON t.path = mt.local_path
               WHERE mt.spotify_id = ? AND mt.local_path IS NOT NULL AND mt.status = 'have'
               LIMIT 1""",
            (spotify_id,),
        )
        row = await cur.fetchone()
        if row and row["path"]:
            return dict(row)

    # Step 1: exact spotify_id match in tracks table
    if spotify_id:
        cur = await db.execute(
            "SELECT path, artist, title, duration, album FROM tracks WHERE spotify_id = ? LIMIT 1",
            (spotify_id,),
        )
        row = await cur.fetchone()
        if row:
            return dict(row)

    # Fuzzy match by artist + title
    if not artist or not title:
        return None

    def _effective_score(c) -> int:
        candidate_str = f"{c['artist'] or ''} {c['title'] or ''}".lower()
        base = fuzz.token_sort_ratio(query, candidate_str)
        local_text = f"{c['title'] or ''} {c['album'] or ''}"
        penalty = version_penalty(local_text, spotify_ref)
        return base - penalty

    query = f"{artist} {title}".lower()

    # Get candidates with a rough artist prefix filter
    cur = await db.execute(
        "SELECT path, artist, title, duration, album FROM tracks WHERE artist LIKE ? LIMIT 50",
        (f"%{artist[:4]}%",),
    )
    candidates = await cur.fetchall()

    best_score = 0
    best_row = None

    for c in candidates:
        score = _effective_score(c)
        if score > best_score:
            best_score = score
            best_row = c

    if best_score >= fuzzy_threshold:
        return dict(best_row)

    # Broader search: try title-only candidates if artist prefix missed
    cur = await db.execute(
        "SELECT path, artist, title, duration, album FROM tracks WHERE title LIKE ? LIMIT 50",
        (f"%{title[:6]}%",),
    )
    candidates = await cur.fetchall()

    for c in candidates:
        score = _effective_score(c)
        if score > best_score:
            best_score = score
            best_row = c

    if best_score >= fuzzy_threshold:
        return dict(best_row)

    return None


async def generate_m3u_for_playlist(playlist_id: str, playlist_name: str) -> tuple[str | None, int, int]:
    """Generate M3U8 file for a Spotify playlist, mapping tracks to local files.
    Returns (path, matched, total). path is None if no tracks matched.
    Uses cached track data when available to avoid Spotify API calls.
    """
    from spotify_cache import cache_get

    # Try cache first — sync already caches all playlist tracks
    tracks = await cache_get(f"playlist_tracks:{playlist_id}")
    if tracks is None:
        sp = await get_client()
        if not sp:
            log.warning("Cannot generate M3U: Spotify not connected and no cache")
            return None
        tracks = await get_all_playlist_tracks(sp, playlist_id)
        if tracks:
            from spotify_cache import cache_set
            await cache_set(f"playlist_tracks:{playlist_id}", tracks)
    if not tracks:
        return None, 0, 0

    path_prefix = await get_setting("m3u_path_prefix", "/mnt/storage/MUSIC")
    fuzzy_threshold = int(await get_setting("fuzzy_threshold", "85"))
    db = await get_db()
    entries = []
    matched = 0
    total = 0

    try:
        for t in tracks:
            spotify_id = t.get("id")
            if not spotify_id:
                continue
            total += 1

            artist = t.get("artists", [{}])[0].get("name", "") if t.get("artists") else ""
            title = t.get("name", "")
            album = t.get("album", {}).get("name", "") if t.get("album") else ""

            row = await _find_local_path(db, spotify_id, artist, title, fuzzy_threshold, album)

            if row:
                matched += 1
                local_path = row["path"]
                relative = os.path.relpath(local_path, MUSIC_PATH)
                jellyfin_path = os.path.join(path_prefix, relative)

                duration = row["duration"] if row["duration"] is not None else -1
                display = f"{row['artist'] or 'Unknown'} - {row['title'] or 'Unknown'}"
                entries.append(f"#EXTINF:{duration},{display}\n{jellyfin_path}")
    finally:
        await db.close()

    if not entries:
        return None, matched, total

    # Write M3U8 file
    os.makedirs(PLAYLIST_PATH, exist_ok=True)
    safe_name = "".join(c for c in playlist_name if c.isalnum() or c in " -_").strip()
    m3u_path = os.path.join(PLAYLIST_PATH, f"{safe_name}.m3u8")

    content = "#EXTM3U\n" + "\n".join(entries) + "\n"
    with open(m3u_path, "w", encoding="utf-8") as f:
        f.write(content)

    log.info(f"Generated M3U: {m3u_path} ({matched}/{total} tracks matched)")
    return m3u_path, matched, total


async def generate_m3u_for_soundcloud(sync_id: int) -> tuple[str | None, int, int]:
    """Generate M3U8 for a SoundCloud playlist by scanning its local download folder.
    Returns (path, file_count, file_count). path is None if folder not found or empty.
    """
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT name, spotify_id FROM sync_items WHERE id = ? AND item_type = 'soundcloud'",
            (sync_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None, 0, 0
        playlist_name = row["name"]
        playlist_url  = row["spotify_id"]
    finally:
        await db.close()

    # Derive the download folder the same way soundcloud.py does
    import re as _re
    safe_name = _re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", playlist_name).strip()
    sc_dir = os.path.join(MUSIC_PATH, "SoundCloud", safe_name)

    if not os.path.isdir(sc_dir):
        log.warning(f"SoundCloud folder not found: {sc_dir}")
        return None, 0, 0

    audio_exts = {".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".wav"}
    audio_files = sorted(
        p for p in Path(sc_dir).iterdir()
        if p.is_file() and p.suffix.lower() in audio_exts
    )

    if not audio_files:
        log.warning(f"No audio files in SoundCloud folder: {sc_dir}")
        return None, 0, 0

    path_prefix = await get_setting("m3u_path_prefix", "/mnt/storage/MUSIC")
    entries = []
    for p in audio_files:
        relative = os.path.relpath(str(p), MUSIC_PATH)
        jellyfin_path = os.path.join(path_prefix, relative)
        display = p.stem
        entries.append(f"#EXTINF:-1,{display}\n{jellyfin_path}")

    os.makedirs(PLAYLIST_PATH, exist_ok=True)
    safe_playlist = "".join(c for c in playlist_name if c.isalnum() or c in " -_").strip()
    m3u_path = os.path.join(PLAYLIST_PATH, f"SC - {safe_playlist}.m3u8")

    content = "#EXTM3U\n" + "\n".join(entries) + "\n"
    with open(m3u_path, "w", encoding="utf-8") as f:
        f.write(content)

    count = len(audio_files)
    log.info(f"Generated SoundCloud M3U: {m3u_path} ({count} tracks)")
    return m3u_path, count, count


async def generate_all_m3u():
    """Generate M3U files for all enabled sync playlists."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT spotify_id, name FROM sync_items WHERE item_type = 'playlist' AND enabled = 1"
        )
        rows = await cur.fetchall()
    finally:
        await db.close()

    generated = 0
    for row in rows:
        path, _matched, _total = await generate_m3u_for_playlist(row["spotify_id"], row["name"])
        if path:
            generated += 1

    log.info(f"Generated {generated} M3U playlists")

    # Trigger Jellyfin library scan if configured
    if generated > 0:
        await _trigger_jellyfin_scan()

    return generated


async def _trigger_jellyfin_scan():
    """Tell Jellyfin to rescan its music library so new M3U playlists are picked up."""
    jellyfin_url = await get_setting("jellyfin_url", "")
    jellyfin_api_key = await get_setting("jellyfin_api_key", "")
    if not jellyfin_url or not jellyfin_api_key:
        return

    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{jellyfin_url}/Library/Refresh",
                headers={"Authorization": f'MediaBrowser Token="{jellyfin_api_key}"'},
            )
            if r.status_code < 300:
                log.info("Triggered Jellyfin library scan")
            else:
                log.warning(f"Jellyfin scan trigger returned {r.status_code}: {r.text}")
    except Exception as e:
        log.warning(f"Failed to trigger Jellyfin scan: {e}")
