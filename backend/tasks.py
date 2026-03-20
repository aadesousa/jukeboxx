import os
import asyncio
import shutil
import logging
from datetime import datetime, timedelta
from pathlib import Path

from database import get_db, get_setting, set_setting, add_notification, add_activity
from spotify_client import get_client, get_all_playlist_tracks
from spotify_auth import record_successful_call
from spotizerr_client import (
    dispatch_download, poll_spotizerr_status, redispatch_pending,
    get_spotizerr_queue_status, get_spotizerr_history_ids,
)
from dedup import check_track_dedup
from scanner import scan_library, DEFAULT_MUSIC_PATH
from m3u import generate_all_m3u, _find_local_path
from spotify_auth import refresh_token_if_needed

log = logging.getLogger("jukeboxx.tasks")

# Max retries before entering long cooling-off period
ACTIVE_RETRY_LIMIT = 20


async def _update_album_completion(db, monitored_album_id):
    """After any track flips to 'have', roll up album status."""
    if not monitored_album_id:
        return
    cur = await db.execute(
        "SELECT status FROM monitored_tracks WHERE album_id=?",
        (monitored_album_id,)
    )
    rows = await cur.fetchall()
    if not rows:
        return
    statuses = [r["status"] for r in rows]
    if all(s in ("have", "ignored") for s in statuses):
        new_status = "have"
    elif any(s == "have" for s in statuses):
        new_status = "partial"
    else:
        new_status = "wanted"
    await db.execute(
        "UPDATE monitored_albums SET status=? WHERE id=?",
        (new_status, monitored_album_id)
    )
    await db.commit()

# ─── Sync progress (in-memory, polled by frontend) ────────────────────────────
_sync_progress: dict = {
    "running": False,
    "phase": "",
    "playlist_name": "",
    "playlist_index": 0,
    "playlist_total": 0,
    "track_index": 0,
    "track_total": 0,
    "matched": 0,
    "results": [],
    "error": "",
}

def get_sync_progress() -> dict:
    return dict(_sync_progress)

def _sp(phase: str = "", playlist_name: str = "", playlist_index: int | None = None,
         playlist_total: int | None = None, track_index: int | None = None,
         track_total: int | None = None, matched: int | None = None,
         running: bool | None = None, error: str = ""):
    """Update sync progress in-place."""
    global _sync_progress
    if running is not None:
        _sync_progress["running"] = running
    if phase:
        _sync_progress["phase"] = phase
    if playlist_name:
        _sync_progress["playlist_name"] = playlist_name
    if playlist_index is not None:
        _sync_progress["playlist_index"] = playlist_index
    if playlist_total is not None:
        _sync_progress["playlist_total"] = playlist_total
    if track_index is not None:
        _sync_progress["track_index"] = track_index
    if track_total is not None:
        _sync_progress["track_total"] = track_total
    if matched is not None:
        _sync_progress["matched"] = matched
    if error:
        _sync_progress["error"] = error


# ─── Dispatch progress (in-memory, polled by frontend) ─────────────────────────
_dispatch_progress: dict = {
    "running": False,
    "phase": "",          # "searching", "done"
    "track_index": 0,
    "track_total": 0,
    "track_name": "",
    "track_artist": "",
    "source": "",
    "dispatched": 0,
    "breakdown": {},
    "error": "",
}
_dispatch_lock = False  # simple flag — asyncio is single-threaded

def get_dispatch_progress() -> dict:
    return dict(_dispatch_progress)

def _dp(**kwargs):
    """Update dispatch progress in-place."""
    global _dispatch_progress
    for k, v in kwargs.items():
        if v is not None:
            _dispatch_progress[k] = v


# How long cooling-off downloads wait before trying again (hours)
COOLING_HOURS = 6


async def refresh_sync_items_from_spotify(sp) -> int:
    """Populate sync_items from the user's Spotify playlists."""
    from spotify_cache import cache_get, cache_set
    from spotify_auth import is_rate_limited

    if is_rate_limited():
        log.warning("refresh_sync_items skipped: rate limited")
        return 0

    cached = await cache_get("playlists")
    if cached is not None:
        all_items = cached.get("items", [])
    else:
        all_items = []
        offset = 0
        while True:
            results = await asyncio.to_thread(sp.current_user_playlists, 50, offset)
            record_successful_call()
            items = results.get("items", [])
            if not items:
                break
            all_items.extend(items)
            offset += len(items)
            if not results.get("next"):
                break
            await asyncio.sleep(0.5)
        await cache_set("playlists", {"items": all_items, "total": len(all_items)})

    db = await get_db()
    added = 0
    try:
        for pl in all_items:
            cur = await db.execute(
                "INSERT OR IGNORE INTO sync_items (spotify_id, item_type, name) VALUES (?, 'playlist', ?)",
                (pl["id"], pl.get("name", "")),
            )
            if cur.rowcount > 0:
                added += 1
        await db.commit()
    finally:
        await db.close()

    log.info(f"Account sync: {added} new playlists added to sync_items")
    return added


async def run_playlist_sync():
    """Sync playlists: match Spotify tracks against local library and generate M3U.
    Does NOT download anything."""
    global _sync_progress
    log.info("Starting playlist sync...")

    _sync_progress = {
        "running": True, "phase": "starting", "playlist_name": "",
        "playlist_index": 0, "playlist_total": 0,
        "track_index": 0, "track_total": 0, "matched": 0,
        "results": [], "error": "",
    }

    try:
        library_ready = await get_setting("library_ready", "0")
        if library_ready != "1":
            _sp(running=False, phase="skipped", error="Library not ready yet")
            log.info("Playlist sync skipped: library not ready yet")
            return

        sp = await get_client()
        if not sp:
            _sp(running=False, phase="skipped", error="Spotify not connected")
            log.warning("Playlist sync skipped: Spotify not connected")
            return

        account_sync = await get_setting("account_sync_enabled", "0")
        if account_sync == "1":
            _sp(phase="refreshing_account")
            try:
                await refresh_sync_items_from_spotify(sp)
            except Exception as e:
                log.error(f"Account sync refresh failed: {e}")

        db = await get_db()
        try:
            cur = await db.execute("SELECT * FROM sync_items WHERE enabled = 1 AND item_type = 'playlist'")
            items = [dict(r) for r in await cur.fetchall()]
        finally:
            await db.close()

        _sp(playlist_total=len(items))
        fuzzy_threshold = int(await get_setting("fuzzy_threshold", "85"))

        from spotify_cache import cache_get, cache_set
        from spotify_auth import is_rate_limited, set_rate_limited

        for idx, item in enumerate(items, 1):
            if is_rate_limited():
                _sp(running=False, phase="aborted", error="Spotify rate limited")
                log.warning("Playlist sync aborted: Spotify rate limited")
                break

            _sp(phase="fetching_tracks", playlist_name=item["name"],
                playlist_index=idx, track_index=0, track_total=0, matched=0)

            try:
                cache_key = f"playlist_tracks:{item['spotify_id']}"
                tracks = await cache_get(cache_key)
                if tracks is None:
                    try:
                        tracks = await get_all_playlist_tracks(sp, item["spotify_id"])
                    except Exception as e:
                        if "429" in str(e) or "too many" in str(e).lower():
                            ra = 1800
                            headers = getattr(e, 'headers', None)
                            if headers:
                                try: ra = max(int(headers.get('Retry-After', ra)), 60)
                                except (ValueError, TypeError): pass
                            set_rate_limited(ra)
                            _sp(running=False, phase="aborted", error=f"Rate limited — retry in {ra}s")
                            log.warning(f"Rate limited during sync (backoff {ra}s)")
                            break
                        raise
                    await cache_set(cache_key, tracks)
                    await asyncio.sleep(1)

                eligible = [t for t in tracks if t.get("id") and not t.get("unavailable")]
                unavailable_count = len(tracks) - len(eligible)
                _sp(phase="matching", track_total=len(eligible), track_index=0, matched=0)

                db = await get_db()
                try:
                    local_count = 0
                    for ti, t in enumerate(eligible, 1):
                        spotify_id = t["id"]
                        artist = t.get("artists", [{}])[0].get("name", "") if t.get("artists") else ""
                        title = t.get("name", "")
                        album = t.get("album", {}).get("name", "") if t.get("album") else ""

                        row = await _find_local_path(db, spotify_id, artist, title, fuzzy_threshold, album)
                        if row:
                            local_count += 1
                            if row.get("path"):
                                await db.execute(
                                    "UPDATE tracks SET spotify_id = ? WHERE path = ? AND (spotify_id IS NULL OR spotify_id = '')",
                                    (spotify_id, row["path"]),
                                )

                        # Update progress every 5 tracks to avoid thrashing
                        if ti % 5 == 0 or ti == len(eligible):
                            _sp(track_index=ti, matched=local_count)

                    await db.execute(
                        "UPDATE sync_items SET last_synced_at = CURRENT_TIMESTAMP, track_count = ?, local_count = ?, unavailable_count = ? WHERE id = ?",
                        (len(tracks), local_count, unavailable_count, item["id"]),
                    )
                    await db.commit()
                finally:
                    await db.close()

                _sync_progress["results"].append({
                    "name": item["name"],
                    "matched": local_count,
                    "total": len(eligible),
                    "unavailable": unavailable_count,
                })
                log.info(f"Synced '{item['name']}': {local_count}/{len(eligible)} matched, {unavailable_count} unavailable")

            except Exception as e:
                log.error(f"Error syncing '{item.get('name', item['spotify_id'])}': {e}")
                _sync_progress["results"].append({"name": item["name"], "error": str(e)})

        _sp(phase="generating_m3u", playlist_name="", track_index=0, track_total=0)
        await generate_all_m3u()
        _sp(running=False, phase="done")
        await add_activity("sync_completed", "Playlist sync complete")
        log.info("Playlist sync complete")

    except Exception as e:
        _sp(running=False, phase="error", error=str(e))
        log.error(f"run_playlist_sync fatal error: {e}")


async def queue_missing_for_playlist(playlist_id: str) -> int:
    """Queue tracks from a playlist that aren't in the local library as 'pending'.
    Does NOT dispatch to Spotizerr directly — steady dispatch handles that.
    Returns number of tracks queued.
    """
    from spotify_cache import cache_get, cache_set
    from spotify_auth import is_rate_limited, set_rate_limited

    if is_rate_limited():
        log.warning(f"queue_missing skipped for {playlist_id}: rate limited")
        return 0

    sp = await get_client()
    if not sp:
        return 0

    cache_key = f"playlist_tracks:{playlist_id}"
    tracks = await cache_get(cache_key)
    if tracks is None:
        try:
            tracks = await get_all_playlist_tracks(sp, playlist_id)
        except Exception as e:
            if "429" in str(e) or "too many" in str(e).lower():
                ra = 1800
                headers = getattr(e, 'headers', None)
                if headers:
                    try: ra = max(int(headers.get('Retry-After', ra)), 60)
                    except (ValueError, TypeError): pass
                set_rate_limited(ra)
                return 0
            raise
        await cache_set(cache_key, tracks)

    queued = 0
    db = await get_db()
    try:
        for t in tracks:
            if t.get("unavailable"):
                continue
            spotify_id = t.get("id")
            if not spotify_id:
                continue
            artist = t.get("artists", [{}])[0].get("name", "") if t.get("artists") else ""
            title = t.get("name", "")

            skip, reason = await check_track_dedup(spotify_id, artist, title)
            if skip:
                continue

            # Insert as 'pending' — steady dispatch will pick it up
            cur = await db.execute(
                "SELECT id FROM downloads WHERE spotify_id = ? AND status IN ('pending','downloading','completed') LIMIT 1",
                (spotify_id,),
            )
            if await cur.fetchone():
                continue

            await db.execute(
                """INSERT OR IGNORE INTO downloads (spotify_id, title, artist, album, item_type, status, source, updated_at)
                   VALUES (?, ?, ?, ?, 'track', 'pending', 'auto_sync', CURRENT_TIMESTAMP)""",
                (spotify_id, title, artist, t.get("album", {}).get("name", "")),
            )
            queued += 1

        await db.commit()
    finally:
        await db.close()

    return queued


async def queue_missing_all() -> int:
    """Queue missing tracks for all enabled sync playlists."""
    library_ready = await get_setting("library_ready", "0")
    if library_ready != "1":
        log.info("Queue skipped: library not ready yet")
        return 0

    sp = await get_client()
    if not sp:
        log.warning("Queue skipped: Spotify not connected")
        return 0

    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM sync_items WHERE enabled = 1 AND item_type = 'playlist'")
        items = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()

    total_queued = 0
    for item in items:
        try:
            queued = await queue_missing_for_playlist(item["spotify_id"])
            total_queued += queued
            if queued:
                log.info(f"Queued {queued} tracks for '{item['name']}'")
        except Exception as e:
            log.error(f"Error queuing for '{item.get('name', item['spotify_id'])}': {e}")

    if total_queued > 0:
        await add_notification("downloads_queued", "Downloads queued",
            f"Queued {total_queued} tracks for download")
        await add_activity("downloads_queued", f"{total_queued} tracks added to queue")
    log.info(f"Queue complete: {total_queued} new tracks queued")
    return total_queued


# Backward compat
async def download_missing_for_playlist(playlist_id: str) -> int:
    return await queue_missing_for_playlist(playlist_id)

async def download_missing_all() -> int:
    return await queue_missing_all()


async def run_auto_sync():
    await run_playlist_sync()


async def run_steady_dispatch():
    """Capacity-aware dispatch: check Spotizerr queue depth, send what fits.
    This is the main dispatch engine — called every 5 minutes.
    Replaces the burst dispatch pattern.
    """
    library_ready = await get_setting("library_ready", "0")
    if library_ready != "1":
        return

    if await get_setting("queue_paused", "0") == "1":
        log.info("Steady dispatch skipped: queue paused")
        return

    # 1. Poll current Spotizerr status (for any manual dispatches)
    await poll_spotizerr_status()

    available = 0  # Spotizerr capacity no longer gates auto-dispatch

    # 3. Recover stale 'downloading' downloads (stuck >2 hours, not in Spotizerr)
    stale_hours = float(await get_setting("stale_hours", "2"))
    stale_cutoff = datetime.utcnow() - timedelta(hours=stale_hours)
    spotizerr_ids = await get_spotizerr_history_ids()

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, spotify_id FROM downloads WHERE status = 'downloading' AND updated_at < ?",
            (stale_cutoff.isoformat(),),
        )
        stale = [dict(r) for r in await cur.fetchall()]
        recovered = 0
        for row in stale:
            if row["spotify_id"] not in spotizerr_ids:
                # Spotizerr has no record of this — it was never actually received
                await db.execute(
                    "UPDATE downloads SET status = 'pending', error_message = 'Connection interrupted, will retry', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (row["id"],),
                )
                recovered += 1
        if recovered:
            log.info(f"Recovered {recovered} stale 'downloading' → 'pending'")
        await db.commit()
    finally:
        await db.close()

    # 4. Move cooled-off downloads back to pending
    cooling_cutoff = datetime.utcnow() - timedelta(hours=COOLING_HOURS)
    db = await get_db()
    try:
        cur = await db.execute(
            """UPDATE downloads SET status = 'pending', error_message = NULL, updated_at = CURRENT_TIMESTAMP
               WHERE status = 'cooling'
               AND updated_at < ?
               AND (error_message IS NULL OR error_message NOT LIKE '%Not found%')""",
            (cooling_cutoff.isoformat(),),
        )
        cooled = cur.rowcount
        if cooled:
            log.info(f"Moved {cooled} cooled-off downloads back to pending")
        await db.commit()
    finally:
        await db.close()

    # 5. Handle downloads that have exceeded active retry limit → cooling
    db = await get_db()
    try:
        cur = await db.execute(
            """UPDATE downloads SET status = 'cooling', updated_at = CURRENT_TIMESTAMP
               WHERE status = 'failed'
               AND retry_count >= ?
               AND (error_message IS NULL OR error_message NOT LIKE '%Not found%')""",
            (ACTIVE_RETRY_LIMIT,),
        )
        moved_to_cooling = cur.rowcount
        if moved_to_cooling:
            log.info(f"Moved {moved_to_cooling} exhausted downloads to cooling (retry after {COOLING_HOURS}h)")
        await db.commit()
    finally:
        await db.close()

    # 6. Auto-retry failed downloads with backoff (only up to ACTIVE_RETRY_LIMIT)
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT id, retry_count, updated_at, artist, title FROM downloads
               WHERE status = 'failed'
               AND retry_count < ?
               AND (error_message IS NULL OR (error_message NOT LIKE '%Not found%'))
               ORDER BY updated_at ASC""",
            (ACTIVE_RETRY_LIMIT,),
        )
        rows = [dict(r) for r in await cur.fetchall()]

        retried = 0
        now = datetime.utcnow()
        for row in rows:
            rc = row["retry_count"]
            if rc < 3:
                wait_minutes = 5
            elif rc < 6:
                wait_minutes = 15
            elif rc < 10:
                wait_minutes = 30
            else:
                wait_minutes = 60

            try:
                updated = datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00").replace("+00:00", ""))
            except (ValueError, AttributeError):
                updated = now - timedelta(hours=1)

            elapsed = (now - updated).total_seconds() / 60
            if elapsed < wait_minutes:
                continue

            await db.execute(
                "UPDATE downloads SET status = 'pending', retry_count = retry_count + 1, error_message = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (row["id"],),
            )
            retried += 1

        if retried:
            log.info(f"Queued {retried} failed downloads for retry")
        await db.commit()
    finally:
        await db.close()

    # 7. [Spotizerr auto-dispatch removed — Spotizerr is now manual-only]
    # Users trigger Spotizerr sends from the Activity > Spotizerr tab.

    # 8. Multi-source dispatch for monitored_tracks not yet queued
    try:
        result = await run_multi_source_dispatch()
        if result.get("dispatched", 0) > 0:
            log.info(f"Multi-source dispatch: {result['dispatched']} tracks. Breakdown: {result.get('breakdown', {})}")
    except Exception as e:
        log.error(f"Multi-source dispatch error: {e}")


async def run_download_monitor():
    """Light monitor: poll status, reconcile completed downloads.
    Heavy dispatch is handled by run_steady_dispatch().
    """
    library_ready = await get_setting("library_ready", "0")

    await poll_spotizerr_status()

    if library_ready != "1":
        log.debug("Skipping reconcile: library not ready")
        return

    # Reconcile: mark 'downloading'/'pending' entries as completed if found locally
    fuzzy_threshold = int(await get_setting("fuzzy_threshold", "85"))
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, spotify_id, artist, title FROM downloads WHERE status IN ('pending', 'downloading')"
        )
        stuck = [dict(r) for r in await cur.fetchall()]
        reconciled = 0
        for dl in stuck:
            row = await _find_local_path(db, dl["spotify_id"], dl["artist"] or "", dl["title"] or "", fuzzy_threshold)
            if row:
                await db.execute(
                    "UPDATE downloads SET status = 'completed', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (dl["id"],),
                )
                reconciled += 1
        if reconciled:
            log.info(f"Reconciled {reconciled} downloads as completed (found locally)")
            try:
                await generate_all_m3u()
            except Exception as _m3u_e:
                log.debug(f"M3U regeneration after reconcile error: {_m3u_e}")

        # Backfill spotify_id on local tracks
        BACKFILL_BATCH = 30
        cur = await db.execute(
            """SELECT d.spotify_id, d.artist, d.title FROM downloads d
               LEFT JOIN tracks t ON t.spotify_id = d.spotify_id
               WHERE d.status = 'completed' AND d.spotify_id IS NOT NULL AND t.id IS NULL
               LIMIT ?""",
            (BACKFILL_BATCH,),
        )
        to_backfill = [dict(r) for r in await cur.fetchall()]
        backfilled = 0
        for dl in to_backfill:
            row = await _find_local_path(db, None, dl["artist"] or "", dl["title"] or "", fuzzy_threshold)
            if row:
                await db.execute(
                    "UPDATE tracks SET spotify_id = ? WHERE path = ? AND (spotify_id IS NULL OR spotify_id = '')",
                    (dl["spotify_id"], row["path"]),
                )
                backfilled += 1
        if backfilled:
            log.info(f"Backfilled spotify_id on {backfilled} local tracks")

        await db.commit()
    finally:
        await db.close()

    # Local matcher: match unmatched local tracks against monitored_tracks (no API)
    try:
        from matcher import match_local_to_monitored
        await match_local_to_monitored(batch_size=200)
    except Exception as _e:
        log.warning(f"Local matcher error: {_e}")

    # Poll unified_downloads — complete/age-out multi-source dispatches
    try:
        await poll_unified_downloads()
    except Exception as _e:
        log.warning(f"poll_unified_downloads error: {_e}")


async def run_scan():
    """Run a full library scan."""
    log.info("Starting library scan...")
    await scan_library()


async def run_token_refresh():
    """Refresh Spotify OAuth token if expiring soon."""
    await refresh_token_if_needed()


async def run_failed_imports_cleanup():
    """Monitor and auto-clean the failed_imports folder."""
    music_path = await get_setting("music_path", DEFAULT_MUSIC_PATH)
    failed_dir = os.path.join(music_path, "failed_imports")

    if not os.path.isdir(failed_dir):
        return

    cutoff = datetime.utcnow() - timedelta(hours=24)
    cleaned_files = 0
    cleaned_bytes = 0

    def _cleanup():
        nonlocal cleaned_files, cleaned_bytes
        for entry in os.scandir(failed_dir):
            if not entry.is_dir():
                st = entry.stat()
                if datetime.utcfromtimestamp(st.st_mtime) < cutoff:
                    cleaned_bytes += st.st_size
                    cleaned_files += 1
                    os.remove(entry.path)
                continue
            st = entry.stat()
            if datetime.utcfromtimestamp(st.st_mtime) < cutoff:
                for root, dirs, files in os.walk(entry.path):
                    for f in files:
                        try:
                            cleaned_bytes += os.path.getsize(os.path.join(root, f))
                            cleaned_files += 1
                        except OSError:
                            pass
                shutil.rmtree(entry.path, ignore_errors=True)

    try:
        await asyncio.to_thread(_cleanup)
        if cleaned_files > 0:
            gb = round(cleaned_bytes / (1024**3), 2)
            log.info(f"Cleaned {cleaned_files} failed imports ({gb} GB)")
            await add_notification("cleanup", "Failed imports cleaned",
                f"Removed {cleaned_files} files ({gb} GB) from failed_imports")
            await add_activity("failed_imports_cleaned", f"Removed {cleaned_files} files ({gb} GB)")
    except Exception as e:
        log.error(f"Failed imports cleanup error: {e}")


async def run_release_check():
    """
    Weekly job: check monitored artists for new album releases.
    For each artist with monitor_new_releases=1, fetch their albums from Spotify
    and insert any new ones into monitored_albums with status='wanted'.
    Sends a notification when new releases are found.
    """
    from spotify_auth import is_rate_limited
    from spotify_client import get_client
    from spotify_auth import record_successful_call

    if is_rate_limited():
        log.info("release_check skipped: rate limited")
        return

    sp = await get_client()
    if not sp:
        log.info("release_check skipped: Spotify not connected")
        return

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM monitored_artists WHERE monitor_new_releases=1 AND monitored=1"
        )
        artists = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()

    if not artists:
        log.debug("release_check: no artists to check")
        return

    log.info(f"release_check: checking {len(artists)} artists")
    new_releases = []

    for artist in artists:
        try:
            results = await asyncio.to_thread(
                sp.artist_albums,
                artist["spotify_id"],
                album_type="album,single,ep",
                limit=20,
            )
            record_successful_call()
            albums = results.get("items", [])

            db = await get_db()
            try:
                for alb in albums:
                    # Check if already in monitored_albums
                    cur = await db.execute(
                        "SELECT id FROM monitored_albums WHERE spotify_id=?",
                        (alb["id"],)
                    )
                    existing = await cur.fetchone()
                    if not existing:
                        await db.execute(
                            """INSERT OR IGNORE INTO monitored_albums
                               (spotify_id, artist_id, artist_spotify_id, name, album_type,
                                release_date, track_count, image_url, status, monitored)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'wanted', 1)""",
                            (alb["id"], artist["id"], artist["spotify_id"],
                             alb["name"], alb["album_type"],
                             alb.get("release_date", ""), alb.get("total_tracks", 0),
                             (alb.get("images") or [{}])[0].get("url", ""))
                        )
                        new_releases.append({
                            "artist": artist["name"],
                            "album":  alb["name"],
                            "type":   alb["album_type"],
                        })
                await db.commit()
            finally:
                await db.close()

            await asyncio.sleep(0.3)  # Rate limit courtesy delay
        except Exception as e:
            log.warning(f"release_check error for {artist['name']}: {e}")

    if new_releases:
        count = len(new_releases)
        summary = ", ".join(f"{r['artist']} — {r['album']}" for r in new_releases[:3])
        if count > 3:
            summary += f" (+{count - 3} more)"
        await add_notification("new_releases", f"{count} new release{'s' if count > 1 else ''} found", summary)
        await add_activity("new_releases_found", f"Found {count} new releases: {summary}")
        log.info(f"release_check: found {count} new releases")
        try:
            from discord import notify_new_releases
            await notify_new_releases(new_releases)
        except Exception as _e:
            log.debug(f"Discord notify_new_releases error: {_e}")
    else:
        log.debug("release_check: no new releases found")


async def get_failed_imports_stats():
    """Return size and count of the failed_imports folder."""
    music_path = await get_setting("music_path", DEFAULT_MUSIC_PATH)
    failed_dir = os.path.join(music_path, "failed_imports")

    def _calc():
        if not os.path.isdir(failed_dir):
            return {"exists": False, "file_count": 0, "size_bytes": 0, "size_gb": 0.0}
        total_size = 0
        file_count = 0
        for root, dirs, files in os.walk(failed_dir):
            for f in files:
                try:
                    total_size += os.path.getsize(os.path.join(root, f))
                    file_count += 1
                except OSError:
                    pass
        return {
            "exists": True,
            "file_count": file_count,
            "size_bytes": total_size,
            "size_gb": round(total_size / (1024**3), 2),
        }

    return await asyncio.to_thread(_calc)


# ─── Unified download polling ─────────────────────────────────────────────────

async def poll_unified_downloads():
    """
    Reconcile unified_downloads against monitored_tracks:
    - If the linked monitored_track now has status='have', mark download completed
      and fire an activity log entry.
    - Age out downloads stuck in 'queued'/'downloading' >24 hours.
    """
    db = await get_db()
    try:
        # Complete: monitored_track was matched locally by the matcher
        cur = await db.execute(
            """SELECT ud.id, ud.title, ud.artist, ud.source, ud.monitored_track_id
               FROM unified_downloads ud
               JOIN monitored_tracks mt ON mt.id = ud.monitored_track_id
               WHERE ud.status IN ('queued', 'downloading') AND mt.status = 'have'"""
        )
        rows = [dict(r) for r in await cur.fetchall()]
        completed = 0
        for row in rows:
            await db.execute(
                "UPDATE unified_downloads SET status='completed', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (row["id"],),
            )
            # Flip monitored_track to 'have' and roll up album status
            if row.get("monitored_track_id"):
                mt = await db.execute(
                    "SELECT id, album_id FROM monitored_tracks WHERE id=?",
                    (row["monitored_track_id"],)
                )
                mt_row = await mt.fetchone()
                if mt_row:
                    await db.execute(
                        "UPDATE monitored_tracks SET status='have', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (mt_row["id"],)
                    )
                    await db.commit()
                    await _update_album_completion(db, mt_row["album_id"])
            completed += 1

        if completed:
            log.info(f"poll_unified_downloads: {completed} completed (found locally)")
            await db.commit()
            for row in rows:
                try:
                    from discord import notify_download_complete
                    await notify_download_complete(
                        row.get("title", "?"), row.get("artist", ""), row.get("source", "unknown")
                    )
                except Exception:
                    pass

        # Age out stale rows (>2h still queued/downloading) and reset their tracks to 'wanted'
        # Use SQLite datetime() to avoid T-separator comparison bug with Python isoformat
        cur = await db.execute(
            """SELECT id, monitored_track_id FROM unified_downloads
               WHERE status IN ('queued','downloading')
               AND datetime(created_at) < datetime('now', '-2 hours')""",
        )
        stale_rows = [dict(r) for r in await cur.fetchall()]
        if stale_rows:
            stale_ids = [r["id"] for r in stale_rows]
            track_ids = [r["monitored_track_id"] for r in stale_rows if r.get("monitored_track_id")]
            await db.execute(
                f"""UPDATE unified_downloads SET status='failed',
                   error_message='Timed out after 2h',
                   updated_at=CURRENT_TIMESTAMP
                   WHERE id IN ({','.join('?'*len(stale_ids))})""",
                stale_ids,
            )
            for tid in track_ids:
                await db.execute(
                    "UPDATE monitored_tracks SET status='wanted', updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='downloading'",
                    (tid,),
                )
            staled = len(stale_ids)
            log.info(f"poll_unified_downloads: {staled} timed out after 2h, {len(track_ids)} tracks reset to 'wanted'")
            await db.commit()

        # Reset orphaned 'downloading' tracks — those with no active unified_download row
        cur = await db.execute(
            """UPDATE monitored_tracks SET status='wanted', updated_at=CURRENT_TIMESTAMP
               WHERE status='downloading'
               AND NOT EXISTS (
                   SELECT 1 FROM unified_downloads ud
                   WHERE ud.monitored_track_id=monitored_tracks.id
                   AND ud.status IN ('queued','downloading')
               )"""
        )
        if cur.rowcount:
            log.info(f"poll_unified_downloads: {cur.rowcount} orphaned 'downloading' tracks reset to 'wanted'")
            await db.commit()

        # Prune old failed unified_downloads — keep only the latest 3 per track, delete the rest
        cur = await db.execute(
            """DELETE FROM unified_downloads
               WHERE status = 'failed'
               AND id NOT IN (
                   SELECT id FROM unified_downloads ud2
                   WHERE ud2.monitored_track_id = unified_downloads.monitored_track_id
                     AND ud2.status = 'failed'
                   ORDER BY ud2.updated_at DESC
                   LIMIT 3
               )
               AND monitored_track_id IS NOT NULL"""
        )
        if cur.rowcount:
            log.info(f"poll_unified_downloads: pruned {cur.rowcount} old failed download records")
            await db.commit()

        # Auto-ignore blank/unimportable monitored tracks (Spotify tracks with no title)
        cur = await db.execute(
            """UPDATE monitored_tracks SET status='ignored', updated_at=CURRENT_TIMESTAMP
               WHERE monitored=1 AND status IN ('wanted','downloading')
               AND TRIM(COALESCE(name,''))=''"""
        )
        if cur.rowcount:
            log.info(f"poll_unified_downloads: auto-ignored {cur.rowcount} blank-named tracks")
            await db.commit()

    finally:
        await db.close()


# ─── Multi-source priority dispatch ──────────────────────────────────────────

async def _write_unified_download(track: dict, source: str, source_url: str = ""):
    """Record a dispatched download into unified_downloads."""
    db = await get_db()
    try:
        await db.execute(
            """INSERT OR IGNORE INTO unified_downloads
               (spotify_id, item_type, title, artist, album, image_url,
                status, source, source_url, monitored_track_id, monitored_album_id,
                created_at, updated_at)
               VALUES (?, 'track', ?, ?, ?, ?, 'queued', ?, ?, ?, ?,
                       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (
                track.get("spotify_id"),
                track.get("name", ""),
                track.get("artist_name", ""),
                track.get("album_name", ""),
                track.get("image_url", ""),
                source,
                source_url,
                track.get("id"),
                track.get("album_id"),
            ),
        )
        await db.commit()
    except Exception as e:
        log.debug(f"_write_unified_download error: {e}")
    finally:
        await db.close()


async def run_multi_source_dispatch(limit: int | None = None, concurrency: int = 1) -> dict:
    """
    For each wanted monitored_track, try download sources in user-configured
    priority order. Writes to unified_downloads and marks track as 'downloading'.
    concurrency: how many tracks to process in parallel (1 = sequential).
    Returns {"dispatched": N, "breakdown": {source: count}}.
    """
    global _dispatch_lock
    if _dispatch_lock:
        log.debug("Multi-source dispatch skipped: already running")
        return {"dispatched": 0, "breakdown": {}, "skipped": True}
    _dispatch_lock = True
    try:
        return await _run_multi_source_dispatch_inner(limit=limit, concurrency=concurrency)
    finally:
        _dispatch_lock = False


async def _run_multi_source_dispatch_inner(limit: int | None = None, concurrency: int = 1) -> dict:
    import json as _j
    from grabbers import (
        search_indexers_auto, grab_torrent, grab_usenet,
        auto_grab_soulseek, auto_grab_youtube,
    )

    library_ready = await get_setting("library_ready", "0")
    if library_ready != "1":
        return {"dispatched": 0, "breakdown": {}}

    if await get_setting("queue_paused", "0") == "1":
        log.debug("Multi-source dispatch skipped: queue paused")
        return {"dispatched": 0, "breakdown": {}, "paused": True}

    priority_str = await get_setting(
        "download_source_priority",
        '["torrent","usenet","soulseek","youtube"]',
    )
    try:
        sources = _j.loads(priority_str)
    except Exception:
        sources = ["torrent", "usenet", "soulseek", "youtube"]

    if not sources:
        return {"dispatched": 0, "breakdown": {}}

    batch_size = limit if limit is not None else int(await get_setting("dispatch_batch_size", "50"))

    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT mt.* FROM monitored_tracks mt
               WHERE mt.status = 'wanted' AND mt.monitored = 1
               AND NOT EXISTS (
                   SELECT 1 FROM unified_downloads ud
                   WHERE ud.monitored_track_id = mt.id
                   AND ud.status IN ('queued', 'downloading')
               )
               ORDER BY mt.added_at ASC
               LIMIT ?""",
            (batch_size,),
        )
        tracks = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()

    if not tracks:
        log.debug("Multi-source dispatch: no wanted tracks pending")
        _dp(running=False, phase="done", track_total=0, dispatched=0)
        return {"dispatched": 0, "breakdown": {}}

    from spotizerr_client import get_spotizerr_queue_status
    sp_status = await get_spotizerr_queue_status()
    sp_available = sp_status.get("available", 0) if sp_status.get("reachable") else 0

    # Shared mutable state — safe with asyncio (single-threaded cooperative scheduling).
    # All mutations happen synchronously (between awaits) so no locks needed.
    state = {
        "sp_used": 0,
        "dispatched": 0,
        "breakdown": {},
    }
    slsk_grabbed: set = set()           # username|folder keys grabbed this run
    slsk_grabbed_albums: set = set()    # album_ids fully dispatched via Soulseek
    slsk_pending_albums: set = set()    # album_ids currently in-flight (prevents concurrent re-grab)

    _dp(running=True, phase="searching", track_index=0, track_total=len(tracks),
        dispatched=0, breakdown={}, error="", track_name="", track_artist="", source="")

    # Semaphore limits how many tracks are dispatched concurrently.
    # Soulseek gets its own tighter semaphore to avoid flooding slskd's search queue.
    sem = asyncio.Semaphore(max(1, concurrency))
    slsk_sem = asyncio.Semaphore(max(1, min(concurrency, 3)))

    async def dispatch_one(track: dict):
        album_id = track.get("album_id")

        # Pre-check: skip if this album was already grabbed via Soulseek
        if album_id and album_id in slsk_grabbed_albums:
            log.debug(f"Soulseek album already grabbed: skipping '{track.get('name')}' (album_id={album_id})")
            return

        name = track.get("name", "?")
        artist = track.get("artist_name", "")
        album = track.get("album_name", "")
        query = f"{artist} {name}".strip()
        dispatched_source = None

        async with sem:
            for source in sources:
                try:
                    if source == "spotizerr":
                        if state["sp_used"] >= sp_available:
                            continue
                        spotify_id = track.get("spotify_id")
                        if not spotify_id:
                            continue
                        from spotizerr_client import dispatch_download
                        result = await dispatch_download(
                            spotify_id, "track", name, artist, album, source="auto"
                        )
                        if not result.get("skipped") and result.get("status") in ("downloading", "pending"):
                            dispatched_source = "spotizerr"
                            state["sp_used"] += 1
                            await _write_unified_download(track, "spotizerr")

                    elif source == "torrent":
                        results = await search_indexers_auto(query, "torrent", limit=10)
                        from grabbers import _score_result
                        qp = None
                        qp_id = track.get("quality_profile_id")
                        if qp_id:
                            db_qp = await get_db()
                            try:
                                qp_cur = await db_qp.execute("SELECT * FROM quality_profiles WHERE id=?", (qp_id,))
                                qp_row = await qp_cur.fetchone()
                                if qp_row:
                                    qp = dict(qp_row)
                            finally:
                                await db_qp.close()
                        results = sorted(results, key=lambda r: _score_result(r, qp), reverse=True)
                        results = [r for r in results if _score_result(r, qp) > -999]
                        usable = [r for r in results if r.get("download_url") and r.get("seeders", 0) >= 0]
                        if usable:
                            ok = await grab_torrent(usable[0]["download_url"])
                            if ok:
                                dispatched_source = "torrent"
                                await _write_unified_download(track, "torrent", usable[0]["download_url"])

                    elif source == "usenet":
                        results = await search_indexers_auto(query, "usenet", limit=10)
                        from grabbers import _score_result
                        qp = None
                        qp_id = track.get("quality_profile_id")
                        if qp_id:
                            db_qp = await get_db()
                            try:
                                qp_cur = await db_qp.execute("SELECT * FROM quality_profiles WHERE id=?", (qp_id,))
                                qp_row = await qp_cur.fetchone()
                                if qp_row:
                                    qp = dict(qp_row)
                            finally:
                                await db_qp.close()
                        results = sorted(results, key=lambda r: _score_result(r, qp), reverse=True)
                        results = [r for r in results if _score_result(r, qp) > -999]
                        usable = [r for r in results if r.get("download_url")]
                        if usable:
                            ok = await grab_usenet(usable[0]["download_url"])
                            if ok:
                                dispatched_source = "usenet"
                                await _write_unified_download(track, "usenet", usable[0]["download_url"])

                    elif source == "soulseek":
                        # Claim the album slot synchronously before any await to prevent
                        # concurrent tasks from also dispatching the same album.
                        if album_id:
                            if album_id in slsk_grabbed_albums or album_id in slsk_pending_albums:
                                continue
                            slsk_pending_albums.add(album_id)
                        async with slsk_sem:
                            ok, slsk_key = await auto_grab_soulseek(name, artist, album, skip_keys=slsk_grabbed)
                        if ok:
                            dispatched_source = "soulseek"
                            if slsk_key:
                                slsk_grabbed.add(slsk_key)
                            await _write_unified_download(track, "soulseek", slsk_key)
                            slsk_album_mode = await get_setting("slsk_album_download", "1") == "1"
                            if slsk_album_mode and album_id:
                                slsk_grabbed_albums.add(album_id)
                                db_bulk = await get_db()
                                try:
                                    cur_sib = await db_bulk.execute(
                                        """SELECT * FROM monitored_tracks
                                           WHERE album_id=? AND status='wanted' AND monitored=1 AND id!=?""",
                                        (album_id, track["id"]),
                                    )
                                    siblings = [dict(r) for r in await cur_sib.fetchall()]
                                    for st in siblings:
                                        await db_bulk.execute(
                                            "UPDATE monitored_tracks SET status='downloading', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                            (st["id"],),
                                        )
                                        await db_bulk.execute(
                                            """INSERT OR IGNORE INTO unified_downloads
                                               (spotify_id, item_type, title, artist, album, image_url,
                                                status, source, source_url, monitored_track_id, monitored_album_id,
                                                created_at, updated_at)
                                               VALUES (?, 'track', ?, ?, ?, ?, 'queued', ?, ?, ?, ?,
                                                       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                                            (
                                                st.get("spotify_id"), st.get("name", ""),
                                                st.get("artist_name", ""), st.get("album_name", ""),
                                                st.get("image_url", ""), "soulseek", slsk_key,
                                                st.get("id"), st.get("album_id"),
                                            ),
                                        )
                                    if siblings:
                                        await db_bulk.commit()
                                        state["dispatched"] += len(siblings)
                                        state["breakdown"]["soulseek"] = state["breakdown"].get("soulseek", 0) + len(siblings)
                                        log.info(f"Soulseek album grab: pre-dispatched {len(siblings)} sibling tracks for album_id={album_id}")
                                except Exception as _sib_err:
                                    log.debug(f"Soulseek sibling dispatch error: {_sib_err}")
                                finally:
                                    await db_bulk.close()
                        elif album_id:
                            slsk_pending_albums.discard(album_id)

                    elif source == "youtube":
                        ok = await auto_grab_youtube(name, artist, track.get("duration_ms", 0))
                        if ok:
                            dispatched_source = "youtube"
                            await _write_unified_download(track, "youtube")

                    if dispatched_source:
                        state["breakdown"][dispatched_source] = state["breakdown"].get(dispatched_source, 0) + 1
                        state["dispatched"] += 1
                        _dp(source=dispatched_source, dispatched=state["dispatched"],
                            breakdown=dict(state["breakdown"]))
                        db = await get_db()
                        try:
                            await db.execute(
                                "UPDATE monitored_tracks SET status='downloading', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                (track["id"],),
                            )
                            await db.commit()
                        finally:
                            await db.close()
                        break

                except Exception as e:
                    log.debug(f"Multi-source [{source}] failed for '{name}': {e}")
                    continue

    await asyncio.gather(*[dispatch_one(t) for t in tracks])

    dispatched = state["dispatched"]
    breakdown = state["breakdown"]
    _dp(running=False, phase="done", dispatched=dispatched, breakdown=dict(breakdown))
    log.info(f"Multi-source dispatch complete: {dispatched} dispatched — {breakdown}")
    if dispatched > 0:
        try:
            from discord import notify_dispatch_result
            await notify_dispatch_result(dispatched, breakdown)
        except Exception as _e:
            log.debug(f"Discord notify_dispatch_result error: {_e}")
    return {"dispatched": dispatched, "breakdown": breakdown}


async def run_torrent_completion_check():
    """
    Poll qBittorrent for completed music torrents (uploading/stalledUP).
    For any not yet processed, create hardlinks into the music library.
    Tracked in torrent_hardlinked_hashes setting to avoid re-processing.
    Requires torrent_save_path and music_path to be on the same filesystem.
    """
    import json as _json
    from pathlib import Path

    if await get_setting("torrent_hardlink_enabled", "0") != "1":
        return

    torrent_save_path = await get_setting("torrent_save_path", "")
    music_path = await get_setting("music_path", "/music")

    if not torrent_save_path:
        log.debug("torrent_completion_check: torrent_save_path not configured")
        return

    try:
        from download_clients import list_clients
        clients = await list_clients()
        qbit = next((c for c in clients if c.get("type") == "qbittorrent" and c.get("enabled")), None)
        if not qbit:
            return
    except Exception as e:
        log.debug(f"torrent_completion_check: no qbit client: {e}")
        return

    base = qbit.get("url_base", "").rstrip("/")
    if not base:
        return

    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as hc:
            if qbit.get("username"):
                await hc.post(f"{base}/api/v2/auth/login",
                    data={"username": qbit["username"], "password": qbit.get("password", "")})
            resp = await hc.get(f"{base}/api/v2/torrents/info", params={"category": "music"})
            if resp.status_code != 200:
                return
            torrents = resp.json()
    except Exception as e:
        log.debug(f"torrent_completion_check qbit error: {e}")
        return

    processed_raw = await get_setting("torrent_hardlinked_hashes", "[]")
    try:
        processed = set(_json.loads(processed_raw))
    except Exception:
        processed = set()

    newly_processed = []
    for t in torrents:
        state = t.get("state", "")
        thash = t.get("hash", "")
        if state not in ("uploading", "stalledUP"):
            continue
        if thash in processed:
            continue

        content_path = t.get("content_path") or t.get("save_path") or torrent_save_path
        torrent_name = t.get("name", thash)
        dst_root = os.path.join(music_path, torrent_name)

        def _hardlink_tree(src_root: str, dst_root: str):
            src = Path(src_root)
            dst = Path(dst_root)
            if src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.exists():
                    os.link(src, dst)
                return
            for item in src.rglob("*"):
                if item.is_file():
                    target = dst / item.relative_to(src)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        try:
                            os.link(item, target)
                        except OSError as link_err:
                            log.warning(f"hardlink failed {item} → {target}: {link_err}")

        try:
            await asyncio.to_thread(_hardlink_tree, content_path, dst_root)
            log.info(f"Hardlinked torrent '{torrent_name}' → {dst_root}")
            newly_processed.append(thash)
        except Exception as e:
            log.warning(f"Hardlink error for '{torrent_name}': {e}")

    if newly_processed:
        processed.update(newly_processed)
        if len(processed) > 1000:
            processed = set(list(processed)[-1000:])
        await set_setting("torrent_hardlinked_hashes", _json.dumps(list(processed)))


async def run_upgrade_scan():
    """
    Re-examine monitored_tracks with status='have' to see if a better local
    version exists than what is currently linked.  A 'better' match is one
    with a lower version_penalty score against the Spotify reference.
    Only upgrades when the improvement is >= 20 points to avoid churn.
    """
    from matcher import version_penalty

    fuzzy_threshold = int(await get_setting("fuzzy_threshold", "85"))
    IMPROVEMENT_MIN = 20  # minimum penalty reduction to trigger upgrade

    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT mt.id, mt.spotify_id, mt.name, mt.artist_name, mt.album_name,
                      mt.local_path,
                      t.title AS local_title, t.artist AS local_artist,
                      t.album AS local_album
               FROM monitored_tracks mt
               LEFT JOIN tracks t ON t.path = mt.local_path
               WHERE mt.status = 'have' AND mt.local_path IS NOT NULL
               LIMIT 500"""
        )
        rows = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()

    if not rows:
        return

    upgraded = 0
    for row in rows:
        spotify_ref = f"{row['name']} {row['album_name'] or ''}".strip()
        local_text = f"{row['local_title'] or ''} {row['local_album'] or ''}".strip()
        current_penalty = version_penalty(local_text, spotify_ref)

        if current_penalty < IMPROVEMENT_MIN:
            continue  # current match is already clean enough

        # Search for a better local match
        db = await get_db()
        try:
            better = await _find_local_path(
                db,
                row["spotify_id"],
                row["artist_name"] or "",
                row["name"] or "",
                fuzzy_threshold,
                row["album_name"] or "",
            )
        finally:
            await db.close()

        if not better or better.get("path") == row["local_path"]:
            continue

        candidate_text = f"{better.get('title','') or ''} {better.get('album','') or ''}".strip()
        new_penalty = version_penalty(candidate_text, spotify_ref)

        if current_penalty - new_penalty >= IMPROVEMENT_MIN:
            db = await get_db()
            try:
                await db.execute(
                    "UPDATE monitored_tracks SET local_path=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (better["path"], row["id"]),
                )
                await db.commit()
            finally:
                await db.close()
            log.info(
                f"Upgraded match for '{row['name']}': penalty {current_penalty}→{new_penalty} "
                f"({row['local_path']} → {better['path']})"
            )
            upgraded += 1

    if upgraded:
        log.info(f"Upgrade scan complete: {upgraded} tracks upgraded to better local matches")
        await generate_all_m3u()
