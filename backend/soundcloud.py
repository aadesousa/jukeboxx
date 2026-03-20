"""
SoundCloud integration — profile scan + direct yt-dlp download to music library.
"""
import asyncio
import json
import logging
import os
import re
from datetime import datetime

from database import get_db, get_setting

log = logging.getLogger("jukeboxx.soundcloud")

# In-memory download status per sync_id
_sc_active: dict = {}


def get_sc_downloads() -> dict:
    return dict(_sc_active)


async def scan_profile_playlists(profile_url: str) -> list[dict]:
    """
    Fetch all playlists from soundcloud.com/{username}/sets.
    Returns [{"name", "url", "track_count"}]
    """
    url = profile_url.rstrip("/")
    if not url.endswith("/sets"):
        url += "/sets"

    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp", "--flat-playlist", "--dump-json", "--no-warnings", url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        raise ValueError("Timed out scanning SoundCloud profile")

    playlists = []
    for line in stdout.decode(errors="replace").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        item_url = item.get("url") or item.get("webpage_url") or ""
        name = item.get("title") or ""
        if item_url and name and "/sets/" in item_url:
            playlists.append({
                "name": name,
                "url": item_url,
                "track_count": item.get("n_entries") or 0,
            })

    if not playlists:
        err = stderr.decode(errors="replace").strip()
        raise ValueError(f"No playlists found — check the profile URL. {err[:200] if err else ''}")

    return playlists


def _name_from_url(url: str) -> str:
    """Extract a human-readable playlist name from a SoundCloud URL."""
    try:
        from urllib.parse import urlparse
        parts = urlparse(url).path.strip("/").split("/")
        # soundcloud.com/user/sets/playlist-name → take last segment, title-case
        name = parts[-1] if parts else url
        return name.replace("-", " ").replace("_", " ").title()
    except Exception:
        return url


async def fetch_soundcloud_playlist(url: str) -> dict:
    """Fetch metadata (title + track list) for a single playlist URL."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp", "--flat-playlist", "--dump-json", "--no-warnings", url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        raise ValueError("yt-dlp timed out")

    tracks = []
    playlist_name = None
    for line in stdout.decode(errors="replace").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("_type") == "playlist":
            playlist_name = item.get("title") or item.get("uploader") or None
            continue
        track_url = item.get("url") or item.get("webpage_url") or ""
        if not track_url and item.get("id"):
            track_url = f"https://soundcloud.com/{item['id']}"
        if track_url:
            tracks.append({
                "title": item.get("title", "Unknown"),
                "artist": item.get("uploader") or item.get("artist") or "",
                "url": track_url,
            })

    if not tracks:
        raise ValueError(f"No tracks found for: {url}")

    # Fall back to URL slug if yt-dlp didn't provide a title
    if not playlist_name:
        playlist_name = _name_from_url(url)

    return {"name": playlist_name, "url": url, "track_count": len(tracks), "tracks": tracks}


async def download_soundcloud_playlist(sync_id: int) -> None:
    """
    Background task: download all tracks from a SoundCloud playlist
    via yt-dlp directly to {music_path}/SoundCloud/{playlist_name}/.
    Updates _sc_active[sync_id] with live progress.
    """
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM sync_items WHERE id=? AND item_type='soundcloud'", (sync_id,)
        )
        row = await cur.fetchone()
        if not row:
            raise ValueError(f"SoundCloud sync item {sync_id} not found")
        row = dict(row)
    finally:
        await db.close()

    playlist_url = row["spotify_id"]
    playlist_name = row["name"] or "SoundCloud"
    music_path = await get_setting("music_path", "/music")
    audio_format = await get_setting("youtube_audio_format", "mp3")

    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", playlist_name).strip()
    output_dir = os.path.join(music_path, "SoundCloud", safe_name)
    os.makedirs(output_dir, exist_ok=True)

    _sc_active[sync_id] = {
        "sync_id": sync_id,
        "name": playlist_name,
        "status": "downloading",
        "done": 0,
        "total": row.get("track_count") or 0,
        "started_at": datetime.utcnow().isoformat(),
        "error": None,
    }

    log.info(f"SoundCloud: starting download of '{playlist_name}' → {output_dir}")

    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--extract-audio",
            "--audio-format", audio_format,
            "--audio-quality", "0",
            "--no-warnings",
            "--newline",
            "--output", os.path.join(output_dir, "%(uploader)s - %(title)s.%(ext)s"),
            "--output", "thumbnail:%(uploader)s - %(title)s.%(ext)s",
            "--write-thumbnail",
            "--embed-thumbnail",
            playlist_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        done = 0
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").strip()
            # yt-dlp prints "[download] 100% of ..." once per completed file
            if line.startswith("[download]") and "100%" in line and "of " in line:
                done += 1
                _sc_active[sync_id]["done"] = done

        await proc.wait()
        rc = proc.returncode

        db = await get_db()
        try:
            await db.execute(
                "UPDATE sync_items SET last_synced_at=CURRENT_TIMESTAMP, track_count=? WHERE id=?",
                (done or row.get("track_count") or 0, sync_id),
            )
            await db.commit()
        finally:
            await db.close()

        if rc != 0 and done == 0:
            _sc_active[sync_id]["status"] = "error"
            _sc_active[sync_id]["error"] = f"yt-dlp exited with code {rc}"
            log.warning(f"SoundCloud: '{playlist_name}' exited {rc}")
        else:
            _sc_active[sync_id]["status"] = "done"
            _sc_active[sync_id]["done"] = done
            log.info(f"SoundCloud: '{playlist_name}' complete — {done} tracks downloaded")

    except Exception as e:
        log.error(f"SoundCloud download error for '{playlist_name}': {e}")
        _sc_active[sync_id]["status"] = "error"
        _sc_active[sync_id]["error"] = str(e)
