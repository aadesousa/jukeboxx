import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from database import get_setting

log = logging.getLogger("jukeboxx.scheduler")

scheduler = AsyncIOScheduler()
_sync_running = False
_dispatch_running = False


async def _run_auto_sync():
    global _sync_running
    if _sync_running:
        log.info("Auto-sync already running, skipping")
        return
    _sync_running = True
    try:
        from tasks import run_auto_sync
        await run_auto_sync()
    finally:
        _sync_running = False


async def _run_download_monitor():
    from tasks import run_download_monitor
    await run_download_monitor()


async def _run_steady_dispatch():
    global _dispatch_running
    if _dispatch_running:
        log.debug("Steady dispatch already running, skipping")
        return
    _dispatch_running = True
    try:
        from tasks import run_steady_dispatch
        await run_steady_dispatch()
    finally:
        _dispatch_running = False


async def _run_scan():
    from tasks import run_scan
    await run_scan()


async def _run_token_refresh():
    from tasks import run_token_refresh
    await run_token_refresh()


async def _run_failed_imports_cleanup():
    from tasks import run_failed_imports_cleanup
    await run_failed_imports_cleanup()


async def _run_release_check():
    from tasks import run_release_check
    await run_release_check()


async def _run_image_backfill():
    try:
        from images import backfill_artist_images, backfill_album_covers
        a = await backfill_artist_images(batch_size=10)
        b = await backfill_album_covers(batch_size=15)
        if a + b > 0:
            log.info(f"Image backfill: {a} artists, {b} albums updated")
    except Exception as e:
        log.debug(f"Image backfill error: {e}")


async def _run_torrent_completion_check():
    from tasks import run_torrent_completion_check
    await run_torrent_completion_check()


async def _run_upgrade_scan():
    try:
        from tasks import run_upgrade_scan
        await run_upgrade_scan()
    except Exception as e:
        log.debug(f"Upgrade scan error: {e}")


async def start_scheduler():
    sync_interval = int(await get_setting("sync_interval_minutes", "60"))
    scan_interval = int(await get_setting("scan_interval_hours", "6"))

    scheduler.add_job(_run_auto_sync, IntervalTrigger(minutes=sync_interval), id="auto_sync", replace_existing=True)
    scheduler.add_job(_run_download_monitor, IntervalTrigger(minutes=2), id="download_monitor", replace_existing=True)
    scheduler.add_job(_run_steady_dispatch, IntervalTrigger(minutes=5), id="steady_dispatch", replace_existing=True)
    scheduler.add_job(_run_scan, IntervalTrigger(hours=scan_interval), id="periodic_scan", replace_existing=True)
    scheduler.add_job(_run_token_refresh, IntervalTrigger(minutes=30), id="token_refresh", replace_existing=True)
    scheduler.add_job(_run_failed_imports_cleanup, IntervalTrigger(hours=6), id="failed_imports_cleanup", replace_existing=True)
    scheduler.add_job(_run_release_check, IntervalTrigger(hours=24), id="release_check", replace_existing=True)
    scheduler.add_job(_run_image_backfill, IntervalTrigger(minutes=30), id="image_backfill", replace_existing=True)
    scheduler.add_job(_run_torrent_completion_check, IntervalTrigger(minutes=5), id="torrent_completion", replace_existing=True)
    scheduler.add_job(_run_upgrade_scan, IntervalTrigger(hours=12), id="upgrade_scan", replace_existing=True)

    scheduler.start()
    log.info(f"Scheduler started: sync every {sync_interval}min, steady dispatch every 5min, scan every {scan_interval}h, release check every 24h")


async def stop_scheduler():
    scheduler.shutdown(wait=False)
    log.info("Scheduler stopped")


async def reschedule_jobs():
    sync_interval = int(await get_setting("sync_interval_minutes", "60"))
    scan_interval = int(await get_setting("scan_interval_hours", "6"))

    scheduler.reschedule_job("auto_sync", trigger=IntervalTrigger(minutes=sync_interval))
    scheduler.reschedule_job("periodic_scan", trigger=IntervalTrigger(hours=scan_interval))
    log.info(f"Rescheduled: sync every {sync_interval}min, scan every {scan_interval}h")


async def get_sync_status():
    job = scheduler.get_job("auto_sync")
    next_run = str(job.next_run_time) if job else None
    dispatch_job = scheduler.get_job("steady_dispatch")
    next_dispatch = str(dispatch_job.next_run_time) if dispatch_job else None
    return {
        "running": _sync_running,
        "next_run": next_run,
        "dispatch_running": _dispatch_running,
        "next_dispatch": next_dispatch,
    }
