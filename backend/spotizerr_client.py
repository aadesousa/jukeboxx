import os
import asyncio
import logging
import httpx
from database import get_db, get_setting, add_activity

log = logging.getLogger("jukeboxx.spotizerr")

SPOTIZERR_URL = os.environ.get("SPOTIZERR_URL", "http://192.168.1.152:7171")
DISPATCH_DELAY = 1.5  # seconds between dispatch requests


def _spotizerr_url(item_type: str, spotify_id: str) -> str:
    if item_type == "track":
        return f"{SPOTIZERR_URL}/api/track/download/{spotify_id}"
    elif item_type == "playlist":
        return f"{SPOTIZERR_URL}/api/playlist/download/{spotify_id}"
    raise ValueError(f"Unknown item_type: {item_type}")


async def get_spotizerr_queue_status() -> dict:
    """Get current Spotizerr queue depth. Used for capacity-aware dispatch."""
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(f"{SPOTIZERR_URL}/api/history/", params={"limit": 500})
            if resp.status_code != 200:
                return {"active": 0, "available": 0, "reachable": False, "total": 0}
            data = resp.json()
            items = data.get("downloads", [])
            active = sum(1 for i in items if i.get("status") in ("queued", "processing"))
            limit = int(await get_setting("spotizerr_concurrent_limit", "20"))
            return {
                "active": active,
                "limit": limit,
                "available": max(0, limit - active),
                "reachable": True,
                "total": len(items),
            }
    except Exception as e:
        log.debug(f"Spotizerr queue status error: {e}")
        return {"active": 0, "available": 0, "reachable": False, "total": 0, "error": str(e)}


async def get_spotizerr_history_ids() -> set:
    """Return set of spotify_ids currently known to Spotizerr (any status)."""
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(f"{SPOTIZERR_URL}/api/history/", params={"limit": 500})
            if resp.status_code != 200:
                return set()
            data = resp.json()
            ids = set()
            for item in data.get("downloads", []):
                sid = item.get("external_ids", {}).get("spotify", "")
                if sid:
                    ids.add(sid)
            return ids
    except Exception:
        return set()


async def dispatch_download(
    spotify_id: str, item_type: str,
    title: str = "", artist: str = "", album: str = "",
    source: str = "manual"
) -> dict:
    """Send download request to Spotizerr and record in DB.
    Only marks as 'downloading' if Spotizerr actually confirmed acceptance (HTTP 200/202).
    On any other response, keeps as 'pending' for retry.
    """
    library_ready = await get_setting("library_ready", "0")
    if library_ready != "1" and source != "manual":
        return {"status": "skipped", "reason": "Library not ready"}

    db = await get_db()
    try:
        # Skip if already queued or recently completed
        cur = await db.execute(
            "SELECT id, status FROM downloads WHERE spotify_id = ? AND status IN ('pending', 'downloading', 'completed') ORDER BY created_at DESC LIMIT 1",
            (spotify_id,),
        )
        existing = await cur.fetchone()
        if existing:
            return {"id": existing["id"], "status": existing["status"], "skipped": True}

        cur = await db.execute(
            """INSERT INTO downloads (spotify_id, title, artist, album, item_type, status, source, updated_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?, CURRENT_TIMESTAMP)""",
            (spotify_id, title, artist, album, item_type, source),
        )
        download_id = cur.lastrowid
        await db.commit()
    finally:
        await db.close()

    # Send to Spotizerr — only mark 'downloading' on confirmed acceptance
    try:
        url = _spotizerr_url(item_type, spotify_id)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)

        if resp.status_code in (200, 202):
            # Spotizerr accepted the request
            try:
                data = resp.json()
            except Exception:
                data = {}
            db = await get_db()
            try:
                await db.execute(
                    "UPDATE downloads SET status = 'downloading', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (download_id,),
                )
                await db.commit()
            finally:
                await db.close()
            return {"id": download_id, "status": "downloading", "spotizerr_response": data}
        else:
            # Non-success response — keep as 'pending', will be retried
            log.warning(f"Spotizerr returned {resp.status_code} for {item_type}/{spotify_id} — keeping as pending")
            db = await get_db()
            try:
                await db.execute(
                    "UPDATE downloads SET error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (f"Spotizerr HTTP {resp.status_code}", download_id),
                )
                await db.commit()
            finally:
                await db.close()
            return {"id": download_id, "status": "pending", "error": f"HTTP {resp.status_code}"}

    except Exception as e:
        log.error(f"Spotizerr dispatch error for {spotify_id}: {e}")
        db = await get_db()
        try:
            await db.execute(
                "UPDATE downloads SET error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (str(e), download_id),
            )
            await db.commit()
        finally:
            await db.close()
        return {"id": download_id, "status": "pending", "error": str(e)}


async def redispatch_pending(available_slots: int = 0) -> int:
    """Re-send pending downloads to Spotizerr, but only if no other source
    (torrent/usenet/soulseek/youtube) already has an active unified_download for the track.
    Spotizerr is the fallback of last resort."""
    library_ready = await get_setting("library_ready", "0")
    if library_ready != "1":
        return 0

    if available_slots <= 0:
        return 0

    batch = min(available_slots, int(await get_setting("dispatch_batch_size", "10")))

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, spotify_id, item_type, retry_count FROM downloads WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?",
            (batch,),
        )
        all_rows = [dict(r) for r in await cur.fetchall()]

        # Filter out tracks that already have an active non-Spotizerr unified download
        rows = []
        for row in all_rows:
            sid = row.get("spotify_id")
            if not sid:
                rows.append(row)
                continue
            cur2 = await db.execute(
                """SELECT 1 FROM unified_downloads ud
                   JOIN monitored_tracks mt ON ud.monitored_track_id = mt.id
                   WHERE mt.spotify_id = ?
                   AND ud.source NOT IN ('spotizerr', 'spotify', 'auto')
                   AND ud.status IN ('queued', 'downloading')
                   LIMIT 1""",
                (sid,),
            )
            if await cur2.fetchone():
                log.debug(f"Skipping Spotizerr dispatch for {sid} — already active via another source")
            else:
                rows.append(row)
    finally:
        await db.close()

    if not rows:
        return 0

    log.info(f"Dispatching {len(rows)} pending downloads to Spotizerr (available slots: {available_slots})")
    sent = 0
    async with httpx.AsyncClient(timeout=30) as client:
        for row in rows:
            item_type = row["item_type"] or "track"
            sid = row["spotify_id"]
            try:
                url = _spotizerr_url(item_type, sid)
            except ValueError:
                continue

            try:
                resp = await client.get(url)
                db = await get_db()
                try:
                    if resp.status_code in (200, 202):
                        await db.execute(
                            "UPDATE downloads SET status = 'downloading', error_message = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (row["id"],),
                        )
                        sent += 1
                    elif resp.status_code == 404:
                        await db.execute(
                            "UPDATE downloads SET status = 'failed', error_message = 'Not found on Spotizerr', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (row["id"],),
                        )
                        log.info(f"Marked {item_type}/{sid} as failed (404)")
                    else:
                        # Keep as pending, note the error
                        await db.execute(
                            "UPDATE downloads SET error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (f"Spotizerr HTTP {resp.status_code}", row["id"]),
                        )
                        log.warning(f"Spotizerr returned {resp.status_code} for {item_type}/{sid}")
                    await db.commit()
                finally:
                    await db.close()
            except Exception as e:
                log.error(f"Failed to dispatch {item_type}/{sid}: {e}")

            await asyncio.sleep(DISPATCH_DELAY)

    log.info(f"Dispatched {sent}/{len(rows)} downloads")
    return sent


async def get_active_downloads():
    """Get active downloads from Spotizerr history and merge with DB."""
    spotizerr_map = {}
    spotizerr_active = []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{SPOTIZERR_URL}/api/history/", params={"limit": 500})
            if resp.status_code == 200:
                data = resp.json()
                spotizerr_active = data.get("downloads", [])
                for item in spotizerr_active:
                    sid = item.get("external_ids", {}).get("spotify", "")
                    if sid:
                        spotizerr_map[sid] = item
    except Exception as e:
        log.debug(f"Could not fetch Spotizerr downloads: {e}")

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM downloads WHERE status IN ('pending', 'downloading') ORDER BY created_at DESC"
        )
        rows = await cur.fetchall()
        db_downloads = [dict(r) for r in rows]
    finally:
        await db.close()

    # Enrich DB downloads with live Spotizerr stage info
    for dl in db_downloads:
        sid = dl.get("spotify_id", "")
        if sid and sid in spotizerr_map:
            sp_item = spotizerr_map[sid]
            status_info = (sp_item.get("metadata") or {}).get("status_info") or {}
            dl["spotizerr_stage"] = status_info.get("status", "")
            dl["spotizerr_status"] = sp_item.get("status", "")

    return {"spotizerr": spotizerr_active, "queued": db_downloads}


async def stream_progress():
    """SSE proxy for Spotizerr download progress."""
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", f"{SPOTIZERR_URL}/api/prgs/stream") as resp:
                async for line in resp.aiter_lines():
                    yield f"{line}\n"
    except Exception as e:
        yield f"data: {{\"error\": \"{e}\"}}\n\n"


async def retry_download(download_id: int):
    """Retry a single failed download. No retry cap for manual retries."""
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM downloads WHERE id = ?", (download_id,))
        row = await cur.fetchone()
        if not row:
            return {"error": "Download not found"}
        row = dict(row)
        await db.execute(
            "UPDATE downloads SET status = 'pending', retry_count = retry_count + 1, error_message = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (download_id,),
        )
        await db.commit()
    finally:
        await db.close()

    return await dispatch_download(
        row["spotify_id"], row["item_type"],
        row.get("title", ""), row.get("artist", ""), row.get("album", ""),
        source=row.get("source", "manual"),
    )


async def retry_all_failed():
    """Reset ALL failed downloads to pending for re-dispatch.
    Excludes permanent failures (404 / not found on Spotizerr).
    Resets retry_count so backoff starts fresh.
    """
    db = await get_db()
    try:
        cur = await db.execute(
            """UPDATE downloads SET status = 'pending', retry_count = 0, error_message = NULL, updated_at = CURRENT_TIMESTAMP
               WHERE status = 'failed'
               AND (error_message IS NULL OR error_message NOT LIKE '%Not found%')"""
        )
        count = cur.rowcount
        await db.commit()
    finally:
        await db.close()

    log.info(f"Reset {count} failed downloads for retry")
    return count


async def poll_spotizerr_status():
    """Poll Spotizerr history for download status and update DB."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{SPOTIZERR_URL}/api/history/", params={"limit": 500})
            if resp.status_code != 200:
                return

            data = resp.json()
            items = data.get("downloads", [])

            # Build map: spotify_id -> full spotizerr item
            spotizerr_items = {}
            for item in items:
                sid = item.get("external_ids", {}).get("spotify", "")
                if sid:
                    spotizerr_items[sid] = item

            db = await get_db()
            try:
                completed_ids = []
                failed_ids = []
                for spotify_id, item in spotizerr_items.items():
                    status = item.get("status", "")
                    if status in ("completed", "partial"):
                        await db.execute(
                            "UPDATE downloads SET status = 'completed', updated_at = CURRENT_TIMESTAMP WHERE spotify_id = ? AND status IN ('pending', 'downloading')",
                            (spotify_id,),
                        )
                        completed_ids.append(spotify_id)
                    elif status in ("failed", "error"):
                        # Extract the real last error from Spotizerr metadata
                        status_info = (item.get("metadata") or {}).get("status_info") or {}
                        raw_err = status_info.get("error", "")
                        if raw_err and "Last error:" in raw_err:
                            error_msg = raw_err.split("Last error:")[-1].strip()
                        elif raw_err:
                            # Trim the long URL/preamble, keep just the meaningful part
                            if "Original error:" in raw_err:
                                error_msg = raw_err.split("Original error:")[-1].strip()
                                if ", Last error:" in error_msg:
                                    error_msg = error_msg.split(", Last error:")[-1].strip()
                            else:
                                error_msg = "Download failed on Spotizerr"
                        else:
                            error_msg = "Download failed on Spotizerr"
                        await db.execute(
                            "UPDATE downloads SET status = 'failed', error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE spotify_id = ? AND status IN ('pending', 'downloading')",
                            (error_msg, spotify_id),
                        )
                        failed_ids.append(spotify_id)
                    elif status == "skipped":
                        await db.execute(
                            "UPDATE downloads SET status = 'completed', updated_at = CURRENT_TIMESTAMP WHERE spotify_id = ? AND status IN ('pending', 'downloading')",
                            (spotify_id,),
                        )
                        completed_ids.append(spotify_id)

                # Sync monitored_tracks: mark as 'have' for any completed download
                for spotify_id in completed_ids:
                    await db.execute(
                        "UPDATE monitored_tracks SET status = 'have', updated_at = CURRENT_TIMESTAMP WHERE spotify_id = ? AND status != 'have'",
                        (spotify_id,),
                    )

                # Update monitored_albums to 'downloaded' where all monitored tracks are 'have'
                if completed_ids:
                    await db.execute("""
                        UPDATE monitored_albums SET status = 'downloaded', updated_at = CURRENT_TIMESTAMP
                        WHERE status != 'downloaded' AND id IN (
                            SELECT mt.album_id FROM monitored_tracks mt
                            WHERE mt.album_id IS NOT NULL AND mt.monitored = 1
                            GROUP BY mt.album_id
                            HAVING COUNT(*) > 0
                               AND SUM(CASE WHEN mt.status = 'have' THEN 1 ELSE 0 END) = COUNT(*)
                        )
                    """)

                await db.commit()

                # YouTube fallback for failed downloads
                fallback_enabled = await get_setting("youtube_fallback_enabled", "0") == "1"
                if fallback_enabled and failed_ids:
                    try:
                        from yt_search import auto_fallback
                        for spotify_id in failed_ids:
                            # Look up the monitored track for this spotify_id
                            cur = await db.execute(
                                "SELECT id, artist_name, name, duration_ms FROM monitored_tracks WHERE spotify_id = ? LIMIT 1",
                                (spotify_id,)
                            )
                            mt = await cur.fetchone()
                            if mt:
                                await auto_fallback(
                                    mt["id"],
                                    mt["artist_name"] or "",
                                    mt["name"] or "",
                                    mt["duration_ms"] or 0,
                                )
                            await asyncio.sleep(0.3)
                    except Exception as e:
                        log.debug(f"YouTube fallback error: {e}")
            finally:
                await db.close()

    except Exception as e:
        log.debug(f"Poll Spotizerr error: {e}")
