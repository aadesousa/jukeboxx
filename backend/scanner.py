import os
import re
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import mutagen
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis
from rapidfuzz import fuzz

from database import get_db, get_setting, set_setting, add_notification, add_activity

log = logging.getLogger("jukeboxx.scanner")

FEAT_PATTERN = re.compile(r'\s*[\(\[]?(?:feat\.?|ft\.?|featuring|with)\s+[^\)\]]+[\)\]]?', re.IGNORECASE)


def normalize_title(title: str) -> str:
    """Strip featured artist annotations from track title."""
    if not title:
        return title
    return FEAT_PATTERN.sub('', title).strip()


def normalize_artist(artist: str) -> str:
    """Get primary artist (before feat./ft.)."""
    if not artist:
        return artist
    m = re.split(r'\s+(?:feat\.?|ft\.?|featuring|with)\s+', artist, maxsplit=1, flags=re.IGNORECASE)
    return m[0].strip()

DEFAULT_MUSIC_PATH = os.environ.get("MUSIC_PATH", "/music")
SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav", ".wma", ".aac"}
SKIP_DIRS = {"Playlists", "failed_imports"}
BATCH_SIZE = 100

# Module-level progress tracking
scan_progress = {
    "total_files": 0, "processed": 0,
    "phase": "idle",  # idle|walking|indexing|dedup|complete
    "started_at": None,
}


def read_tags(filepath: str) -> dict:
    """Read audio tags from a file using mutagen."""
    tags = {
        "artist": None, "album_artist": None, "title": None, "album": None,
        "track_number": None, "disc_number": None, "year": None, "genre": None,
        "format": None, "bitrate": None, "duration": None, "mbid": None,
    }

    ext = Path(filepath).suffix.lower()
    try:
        audio = mutagen.File(filepath)
        if audio is None:
            return tags

        tags["duration"] = int(audio.info.length) if audio.info and hasattr(audio.info, "length") else None
        tags["bitrate"] = int(audio.info.bitrate / 1000) if audio.info and hasattr(audio.info, "bitrate") else None

        if ext == ".mp3":
            tags["format"] = "MP3"
            try:
                id3 = EasyID3(filepath)
                tags["artist"] = id3.get("artist", [None])[0]
                tags["album_artist"] = id3.get("albumartist", [None])[0]
                tags["title"] = id3.get("title", [None])[0]
                tags["album"] = id3.get("album", [None])[0]
                tags["genre"] = id3.get("genre", [None])[0]
                tn = id3.get("tracknumber", [None])[0]
                if tn:
                    tags["track_number"] = int(tn.split("/")[0])
                dn = id3.get("discnumber", [None])[0]
                if dn:
                    tags["disc_number"] = int(dn.split("/")[0])
                date = id3.get("date", [None])[0]
                if date:
                    tags["year"] = int(date[:4])
                tags["mbid"] = id3.get("musicbrainz_trackid", [None])[0]
            except Exception:
                pass

        elif ext == ".flac":
            tags["format"] = "FLAC"
            try:
                flac = FLAC(filepath)
                tags["artist"] = flac.get("artist", [None])[0]
                tags["album_artist"] = flac.get("albumartist", [None])[0]
                tags["title"] = flac.get("title", [None])[0]
                tags["album"] = flac.get("album", [None])[0]
                tags["genre"] = flac.get("genre", [None])[0]
                tn = flac.get("tracknumber", [None])[0]
                if tn:
                    tags["track_number"] = int(tn.split("/")[0])
                dn = flac.get("discnumber", [None])[0]
                if dn:
                    tags["disc_number"] = int(dn.split("/")[0])
                date = flac.get("date", [None])[0]
                if date:
                    tags["year"] = int(date[:4])
                tags["mbid"] = flac.get("musicbrainz_trackid", [None])[0]
            except Exception:
                pass
            tags["bitrate"] = None  # FLAC is lossless

        elif ext in (".m4a", ".aac"):
            tags["format"] = "M4A" if ext == ".m4a" else "AAC"
            try:
                m4 = MP4(filepath)
                tags["artist"] = m4.get("\xa9ART", [None])[0]
                tags["album_artist"] = m4.get("aART", [None])[0]
                tags["title"] = m4.get("\xa9nam", [None])[0]
                tags["album"] = m4.get("\xa9alb", [None])[0]
                tags["genre"] = m4.get("\xa9gen", [None])[0]
                trkn = m4.get("trkn", [(None, None)])[0]
                if trkn and isinstance(trkn, tuple):
                    tags["track_number"] = trkn[0]
                disk = m4.get("disk", [(None, None)])[0]
                if disk and isinstance(disk, tuple):
                    tags["disc_number"] = disk[0]
                date = m4.get("\xa9day", [None])[0]
                if date:
                    tags["year"] = int(str(date)[:4])
                mbid_raw = m4.get("----:com.apple.iTunes:MusicBrainz Track Id", [None])[0]
                if mbid_raw:
                    tags["mbid"] = mbid_raw.decode("utf-8") if isinstance(mbid_raw, bytes) else str(mbid_raw)
            except Exception:
                pass

        elif ext in (".ogg", ".opus"):
            tags["format"] = "OGG" if ext == ".ogg" else "OPUS"
            try:
                ogg = OggVorbis(filepath) if ext == ".ogg" else mutagen.File(filepath)
                if ogg:
                    tags["artist"] = ogg.get("artist", [None])[0]
                    tags["album_artist"] = ogg.get("albumartist", [None])[0]
                    tags["title"] = ogg.get("title", [None])[0]
                    tags["album"] = ogg.get("album", [None])[0]
                    tags["genre"] = ogg.get("genre", [None])[0]
                    tn = ogg.get("tracknumber", [None])[0]
                    if tn:
                        tags["track_number"] = int(tn.split("/")[0])
            except Exception:
                pass

        elif ext == ".wav":
            tags["format"] = "WAV"
            tags["bitrate"] = None

    except Exception as e:
        log.warning(f"Could not read tags from {filepath}: {e}")

    return tags


async def cleanup_stale_scans():
    """Mark any 'running' scans as 'interrupted' (from previous crashes/restarts)."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE scan_history SET status='interrupted', completed_at=? WHERE status='running'",
            (datetime.utcnow().isoformat(),),
        )
        await db.commit()
    finally:
        await db.close()


async def scan_library() -> dict:
    """Walk music path, read tags, index into DB. Resumes if interrupted.

    Optimizations:
    - Uses size+mtime for change detection
    - Single DB connection for entire scan
    - Batched commits every BATCH_SIZE tracks
    - Fuzzy-only duplicate detection (no hashing)
    """
    global scan_progress
    music_path = await get_setting("music_path", DEFAULT_MUSIC_PATH)
    if not os.path.isdir(music_path):
        raise ValueError(f"Music path does not exist: {music_path}")
    log.info(f"Scanning music library at: {music_path}")

    stats = {
        "tracks_found": 0, "tracks_added": 0, "tracks_updated": 0,
        "tracks_removed": 0, "duplicates_found": 0,
    }

    scan_progress = {
        "total_files": 0, "processed": 0,
        "phase": "walking", "started_at": datetime.utcnow().isoformat(),
    }
    await add_activity("scan_started", "Library scan started")

    db = await get_db()
    try:
        # Create scan record
        cur = await db.execute(
            "INSERT INTO scan_history (started_at, status) VALUES (?, 'running')",
            (datetime.utcnow().isoformat(),),
        )
        scan_id = cur.lastrowid
        await db.commit()

        # Phase 1: Walk — count total files first (fast, run in thread to avoid blocking)
        def _walk_files():
            result = []
            for root, dirs, files in os.walk(music_path):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for fname in files:
                    ext = Path(fname).suffix.lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        result.append(os.path.join(root, fname))
            return result

        all_files = await asyncio.to_thread(_walk_files)
        scan_progress["total_files"] = len(all_files)
        scan_progress["phase"] = "indexing"

        # Load all existing tracks into memory for fast lookup
        cur = await db.execute("SELECT id, path, size, mtime FROM tracks")
        rows = await cur.fetchall()
        existing_tracks = {row["path"]: dict(row) for row in rows}

        found_paths = set()
        pending_ops = 0

        for filepath in all_files:
            found_paths.add(filepath)
            stats["tracks_found"] += 1
            scan_progress["processed"] += 1

            try:
                st = await asyncio.to_thread(os.stat, filepath)
                file_size = st.st_size
                file_mtime = st.st_mtime
            except OSError:
                continue

            existing = existing_tracks.get(filepath)

            if existing:
                if existing["size"] == file_size and existing["mtime"] == file_mtime:
                    continue
                tag_data = await asyncio.to_thread(read_tags, filepath)
                await db.execute(
                    """UPDATE tracks SET artist=?, album_artist=?, title=?, album=?,
                       track_number=?, disc_number=?, year=?, genre=?, format=?, bitrate=?,
                       duration=?, size=?, mtime=?, mbid=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (tag_data["artist"], tag_data["album_artist"], tag_data["title"],
                     tag_data["album"], tag_data["track_number"], tag_data["disc_number"],
                     tag_data["year"], tag_data["genre"], tag_data["format"],
                     tag_data["bitrate"], tag_data["duration"], file_size, file_mtime,
                     tag_data.get("mbid"), existing["id"]),
                )
                stats["tracks_updated"] += 1
            else:
                tag_data = await asyncio.to_thread(read_tags, filepath)
                await db.execute(
                    """INSERT INTO tracks (path, artist, album_artist, title, album,
                       track_number, disc_number, year, genre, format, bitrate, duration,
                       size, mtime, mbid)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (filepath, tag_data["artist"], tag_data["album_artist"],
                     tag_data["title"], tag_data["album"], tag_data["track_number"],
                     tag_data["disc_number"], tag_data["year"], tag_data["genre"],
                     tag_data["format"], tag_data["bitrate"], tag_data["duration"],
                     file_size, file_mtime, tag_data.get("mbid")),
                )
                stats["tracks_added"] += 1

            pending_ops += 1
            if pending_ops >= BATCH_SIZE:
                await db.commit()
                pending_ops = 0

        if pending_ops > 0:
            await db.commit()

        # Remove tracks whose files no longer exist
        for path, track in existing_tracks.items():
            if path not in found_paths:
                await db.execute("DELETE FROM tracks WHERE id = ?", (track["id"],))
                stats["tracks_removed"] += 1
        await db.commit()

        # Phase: dedup (fuzzy artist+title matching only, no hashing)
        scan_progress["phase"] = "dedup"
        dup_count = await _detect_duplicates(db)
        stats["duplicates_found"] = dup_count

        scan_progress["phase"] = "complete"

        # Update scan record
        await db.execute(
            """UPDATE scan_history SET completed_at=?, tracks_found=?, tracks_added=?,
               tracks_updated=?, tracks_removed=?, duplicates_found=?, status='completed'
               WHERE id=?""",
            (datetime.utcnow().isoformat(), stats["tracks_found"], stats["tracks_added"],
             stats["tracks_updated"], stats["tracks_removed"], stats["duplicates_found"], scan_id),
        )
        await db.commit()

        # Mark library as ready after successful scan
        await set_setting("library_ready", "1")

        # Auto-match new local tracks against monitored_tracks (no API calls)
        if stats['tracks_added'] > 0 or stats['tracks_updated'] > 0:
            try:
                from matcher import match_local_to_monitored
                new_matches = await match_local_to_monitored()
                if new_matches:
                    log.info(f"Post-scan matcher: {new_matches} local tracks matched to monitored")
            except Exception as _me:
                log.warning(f"Post-scan matcher error: {_me}")

        await add_notification("scan_complete", "Library scan complete",
            f"Found {stats['tracks_found']} tracks, added {stats['tracks_added']}, {stats['duplicates_found']} duplicates")
        await add_activity("scan_completed",
            f"Found {stats['tracks_found']}, added {stats['tracks_added']}, removed {stats['tracks_removed']}, dupes {stats['duplicates_found']}")

    except Exception as e:
        log.error(f"Scan error: {e}")
        scan_progress["phase"] = "idle"
        await db.execute(
            "UPDATE scan_history SET status='failed', error_message=?, completed_at=? WHERE id=?",
            (str(e), datetime.utcnow().isoformat(), scan_id),
        )
        await db.commit()
        await add_activity("scan_failed", str(e))
    finally:
        await db.close()

    log.info(f"Scan complete: {stats}")
    return stats


async def _detect_duplicates(db) -> int:
    """Detect duplicate tracks by fuzzy artist+title match.

    Uses rapidfuzz for ~100x speedup over thefuzz, and buckets tracks by
    normalized artist name to avoid O(n²) full-library comparisons.
    """
    count = 0

    # Fuzzy duplicates by artist + title, bucketed by normalized artist first char
    threshold = int(await get_setting("fuzzy_threshold", "85"))
    cur = await db.execute(
        "SELECT id, artist, title FROM tracks WHERE artist IS NOT NULL AND title IS NOT NULL"
    )
    tracks = [dict(t) for t in await cur.fetchall()]

    # Bucket by first character of normalized artist name
    buckets = defaultdict(list)
    for t in tracks:
        key = t["artist"].strip().lower()[:1] if t["artist"] else ""
        buckets[key].append(t)

    for bucket_tracks in buckets.values():
        for i in range(len(bucket_tracks)):
            for j in range(i + 1, len(bucket_tracks)):
                a = bucket_tracks[i]
                b = bucket_tracks[j]
                a_str = f"{a['artist']} {a['title']}".lower()
                b_str = f"{b['artist']} {b['title']}".lower()
                score = fuzz.token_sort_ratio(a_str, b_str)
                if score >= threshold:
                    a_id, b_id = min(a["id"], b["id"]), max(a["id"], b["id"])
                    cur2 = await db.execute(
                        "SELECT id FROM duplicate_pairs WHERE track_a_id = ? AND track_b_id = ?",
                        (a_id, b_id),
                    )
                    if not await cur2.fetchone():
                        await db.execute(
                            "INSERT INTO duplicate_pairs (track_a_id, track_b_id, match_type, similarity_score) VALUES (?, ?, 'fuzzy', ?)",
                            (a_id, b_id, score),
                        )
                        count += 1

    await db.commit()
    log.info(f"Duplicate detection found {count} new pairs")
    return count


# Keep module-level function for backward compat (called from main.py)
async def detect_duplicates() -> int:
    db = await get_db()
    try:
        return await _detect_duplicates(db)
    finally:
        await db.close()
