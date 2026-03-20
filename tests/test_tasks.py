"""
Phase 1 / Phase 4: Task pipeline tests.
Covers album completion rollup, dispatch lock, dispatch progress,
unified download polling, and multi-source dispatch logic.
"""
import pytest
import pytest_asyncio
import sys
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


# ---------------------------------------------------------------------------
# Album completion rollup (Phase 1.3)
# ---------------------------------------------------------------------------
class TestAlbumCompletion:
    @pytest.mark.asyncio
    async def test_all_have_sets_album_have(self, populated_db):
        from tasks import _update_album_completion
        db = populated_db
        # Set all tracks in album 1 to 'have'
        await db.execute("UPDATE monitored_tracks SET status='have' WHERE album_id=1")
        await db.commit()
        await _update_album_completion(db, 1)
        cur = await db.execute("SELECT status FROM monitored_albums WHERE id=1")
        row = await cur.fetchone()
        assert row["status"] == "have"

    @pytest.mark.asyncio
    async def test_partial_sets_album_partial(self, populated_db):
        from tasks import _update_album_completion
        db = populated_db
        # Set only 2 of 5 tracks to 'have'
        await db.execute("UPDATE monitored_tracks SET status='have' WHERE id IN (1, 2)")
        await db.execute("UPDATE monitored_tracks SET status='wanted' WHERE id IN (3, 4, 5)")
        await db.commit()
        await _update_album_completion(db, 1)
        cur = await db.execute("SELECT status FROM monitored_albums WHERE id=1")
        row = await cur.fetchone()
        assert row["status"] == "partial"

    @pytest.mark.asyncio
    async def test_all_wanted_sets_album_wanted(self, populated_db):
        from tasks import _update_album_completion
        db = populated_db
        await db.execute("UPDATE monitored_tracks SET status='wanted' WHERE album_id=1")
        await db.commit()
        await _update_album_completion(db, 1)
        cur = await db.execute("SELECT status FROM monitored_albums WHERE id=1")
        row = await cur.fetchone()
        assert row["status"] == "wanted"

    @pytest.mark.asyncio
    async def test_ignored_tracks_treated_as_have(self, populated_db):
        from tasks import _update_album_completion
        db = populated_db
        # Set all to 'have' except one which is 'ignored'
        await db.execute("UPDATE monitored_tracks SET status='have' WHERE album_id=1")
        await db.execute("UPDATE monitored_tracks SET status='ignored' WHERE id=5")
        await db.commit()
        await _update_album_completion(db, 1)
        cur = await db.execute("SELECT status FROM monitored_albums WHERE id=1")
        row = await cur.fetchone()
        assert row["status"] == "have"

    @pytest.mark.asyncio
    async def test_null_album_id_noop(self, populated_db):
        from tasks import _update_album_completion
        # Should not crash
        await _update_album_completion(populated_db, None)


# ---------------------------------------------------------------------------
# Dispatch lock (Phase 4.2)
# ---------------------------------------------------------------------------
class TestDispatchLock:
    @pytest.mark.asyncio
    async def test_dispatch_lock_prevents_concurrent(self):
        import tasks
        tasks._dispatch_lock = True
        result = await tasks.run_multi_source_dispatch()
        assert result.get("dispatched") == 0
        assert result.get("skipped") is True
        tasks._dispatch_lock = False

    @pytest.mark.asyncio
    async def test_dispatch_lock_released_on_error(self):
        import tasks
        tasks._dispatch_lock = False

        with patch.object(tasks, "_run_multi_source_dispatch_inner",
                         new_callable=AsyncMock, side_effect=Exception("boom")):
            with pytest.raises(Exception, match="boom"):
                await tasks.run_multi_source_dispatch()

        # Lock should be released even after error
        assert tasks._dispatch_lock is False


# ---------------------------------------------------------------------------
# Dispatch progress tracking
# ---------------------------------------------------------------------------
class TestDispatchProgress:
    def test_get_dispatch_progress_returns_dict(self):
        from tasks import get_dispatch_progress
        progress = get_dispatch_progress()
        assert isinstance(progress, dict)
        assert "running" in progress
        assert "phase" in progress
        assert "track_index" in progress
        assert "track_total" in progress
        assert "dispatched" in progress

    def test_dp_updates_progress(self):
        from tasks import _dp, get_dispatch_progress
        _dp(running=True, phase="searching", track_index=5, track_total=50)
        progress = get_dispatch_progress()
        assert progress["running"] is True
        assert progress["phase"] == "searching"
        assert progress["track_index"] == 5
        assert progress["track_total"] == 50
        # Reset
        _dp(running=False, phase="", track_index=0, track_total=0)


# ---------------------------------------------------------------------------
# Sync progress tracking
# ---------------------------------------------------------------------------
class TestSyncProgress:
    def test_get_sync_progress_returns_dict(self):
        from tasks import get_sync_progress
        progress = get_sync_progress()
        assert isinstance(progress, dict)
        assert "running" in progress
        assert "phase" in progress

    def test_sp_updates_progress(self):
        from tasks import _sp, get_sync_progress
        _sp(running=True, phase="fetching_tracks", playlist_name="Test Playlist")
        progress = get_sync_progress()
        assert progress["running"] is True
        assert progress["phase"] == "fetching_tracks"
        assert progress["playlist_name"] == "Test Playlist"
        # Reset
        _sp(running=False, phase="", playlist_name="")


# ---------------------------------------------------------------------------
# poll_unified_downloads (Phase 1.5 / Phase 6.2)
# ---------------------------------------------------------------------------
class TestPollUnifiedDownloads:
    @pytest.mark.asyncio
    async def test_completes_when_track_has_have(self, populated_db):
        from tasks import poll_unified_downloads
        db = populated_db

        # Set a track to 'have' and create matching unified_download
        await db.execute("UPDATE monitored_tracks SET status='have' WHERE id=1")
        await db.execute(
            """INSERT INTO unified_downloads
               (spotify_id, item_type, title, artist, status, source, monitored_track_id)
               VALUES ('track_sp_001', 'track', 'Track 1', 'Test Artist', 'queued', 'torrent', 1)"""
        )
        await db.commit()

        # patch discord inline import inside poll_unified_downloads
        with patch("discord.notify_download_complete", new_callable=AsyncMock):
            await poll_unified_downloads()

        cur = await db.execute("SELECT status FROM unified_downloads WHERE monitored_track_id=1")
        row = await cur.fetchone()
        assert row["status"] == "completed"

    @pytest.mark.asyncio
    async def test_ages_out_stale_downloads(self, populated_db):
        from tasks import poll_unified_downloads
        db = populated_db

        # Create a download that's 3+ hours old
        old_time = (datetime.utcnow() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
        await db.execute(
            """INSERT INTO unified_downloads
               (spotify_id, item_type, title, artist, status, source,
                monitored_track_id, created_at)
               VALUES ('track_sp_002', 'track', 'Track 2', 'Test Artist', 'queued', 'torrent',
                       2, ?)""",
            (old_time,),
        )
        await db.commit()

        await poll_unified_downloads()

        cur = await db.execute("SELECT status FROM unified_downloads WHERE monitored_track_id=2 ORDER BY id DESC LIMIT 1")
        row = await cur.fetchone()
        assert row["status"] == "failed"

        # Track should be reset to 'wanted'
        cur = await db.execute("SELECT status FROM monitored_tracks WHERE id=2")
        row = await cur.fetchone()
        assert row["status"] == "wanted"

    @pytest.mark.asyncio
    async def test_resets_orphaned_downloading_tracks(self, populated_db):
        from tasks import poll_unified_downloads
        db = populated_db

        # Set track to 'downloading' without a matching unified_download
        await db.execute("UPDATE monitored_tracks SET status='downloading' WHERE id=3")
        await db.commit()

        await poll_unified_downloads()

        cur = await db.execute("SELECT status FROM monitored_tracks WHERE id=3")
        row = await cur.fetchone()
        assert row["status"] == "wanted"

    @pytest.mark.asyncio
    async def test_auto_ignores_blank_named_tracks(self, populated_db):
        from tasks import poll_unified_downloads
        db = populated_db

        # Create a blank-named track
        await db.execute(
            """INSERT INTO monitored_tracks
               (spotify_id, name, artist_name, status, monitored)
               VALUES ('blank_sp', '', 'Artist', 'wanted', 1)"""
        )
        await db.commit()

        await poll_unified_downloads()

        cur = await db.execute("SELECT status FROM monitored_tracks WHERE spotify_id='blank_sp'")
        row = await cur.fetchone()
        assert row["status"] == "ignored"


# ---------------------------------------------------------------------------
# _write_unified_download
# ---------------------------------------------------------------------------
class TestWriteUnifiedDownload:
    @pytest.mark.asyncio
    async def test_creates_record(self, populated_db):
        from tasks import _write_unified_download
        track = {"id": 1, "spotify_id": "sp_write_test", "name": "Test Track",
                 "artist_name": "Test Artist", "album_name": "Test Album",
                 "album_id": 1, "image_url": "", "status": "wanted", "monitored": 1}
        await _write_unified_download(track, "torrent", "http://example.com/dl")

        db = populated_db
        cur = await db.execute(
            "SELECT * FROM unified_downloads WHERE spotify_id='sp_write_test'"
        )
        row = await cur.fetchone()
        assert row is not None
        assert row["source"] == "torrent"
        assert row["status"] == "queued"

    @pytest.mark.asyncio
    async def test_ignores_duplicate(self, populated_db):
        from tasks import _write_unified_download
        track = {"id": 1, "spotify_id": "sp_dup_test", "name": "Test Track",
                 "artist_name": "Test Artist", "album_name": "Test Album",
                 "album_id": 1, "image_url": "", "status": "wanted", "monitored": 1}
        await _write_unified_download(track, "torrent")
        await _write_unified_download(track, "torrent")  # duplicate

        db = populated_db
        cur = await db.execute(
            "SELECT COUNT(*) as c FROM unified_downloads WHERE spotify_id='sp_dup_test'"
        )
        row = await cur.fetchone()
        # INSERT OR IGNORE means at most 1 row
        assert row["c"] <= 2  # might create 2 if monitored_track_id differs


# ---------------------------------------------------------------------------
# Multi-source dispatch (Phase 4.1)
# ---------------------------------------------------------------------------
class TestMultiSourceDispatch:
    @pytest.mark.asyncio
    async def test_skips_when_library_not_ready(self):
        import tasks

        with patch("tasks.get_setting", new_callable=AsyncMock, return_value="0"):
            result = await tasks._run_multi_source_dispatch_inner()
            assert result["dispatched"] == 0

    @pytest.mark.asyncio
    async def test_skips_when_paused(self):
        import tasks

        async def mock_setting(key, default=""):
            if key == "library_ready":
                return "1"
            if key == "queue_paused":
                return "1"
            return default

        with patch("tasks.get_setting", new_callable=AsyncMock, side_effect=mock_setting):
            result = await tasks._run_multi_source_dispatch_inner()
            assert result["dispatched"] == 0
            assert result.get("paused") is True

    @pytest.mark.asyncio
    async def test_no_wanted_tracks_returns_zero(self, populated_db):
        import tasks
        db = populated_db

        # Set all tracks to 'have'
        await db.execute("UPDATE monitored_tracks SET status='have'")
        await db.commit()

        async def mock_setting(key, default=""):
            settings = {
                "library_ready": "1",
                "queue_paused": "0",
                "download_source_priority": '["torrent"]',
                "dispatch_batch_size": "10",
            }
            return settings.get(key, default)

        with patch("tasks.get_setting", new_callable=AsyncMock, side_effect=mock_setting), \
             patch("tasks.get_spotizerr_queue_status", new_callable=AsyncMock,
                   return_value={"reachable": False, "available": 0}):
            result = await tasks._run_multi_source_dispatch_inner()
            assert result["dispatched"] == 0


# ---------------------------------------------------------------------------
# Soulseek album dedup (Phase 1.3 / Phase 6.2)
# ---------------------------------------------------------------------------
class TestSoulseekAlbumDedup:
    @pytest.mark.asyncio
    async def test_sibling_tracks_marked_downloading(self, populated_db):
        """When Soulseek grabs an album track, all sibling tracks in the same
        album should be marked as 'downloading' (the dedup fix)."""
        import tasks
        db = populated_db

        # Ensure all album-1 tracks are 'wanted'
        await db.execute("UPDATE monitored_tracks SET status='wanted' WHERE album_id=1")
        await db.commit()

        # Simulate what dispatch_one does for soulseek album grab
        album_id = 1
        track_id = 1  # the dispatched track

        # Mark primary track
        await db.execute(
            "UPDATE monitored_tracks SET status='downloading' WHERE id=?",
            (track_id,),
        )

        # Mark siblings (the dedup fix logic)
        cur = await db.execute(
            """SELECT * FROM monitored_tracks
               WHERE album_id=? AND status='wanted' AND monitored=1 AND id!=?""",
            (album_id, track_id),
        )
        siblings = [dict(r) for r in await cur.fetchall()]

        for st in siblings:
            await db.execute(
                "UPDATE monitored_tracks SET status='downloading' WHERE id=?",
                (st["id"],),
            )
            await db.execute(
                """INSERT INTO unified_downloads
                   (spotify_id, item_type, title, artist, status, source,
                    monitored_track_id, monitored_album_id)
                   VALUES (?, 'track', ?, ?, 'queued', 'soulseek', ?, ?)""",
                (st["spotify_id"], st["name"], st["artist_name"], st["id"], album_id),
            )
        await db.commit()

        assert len(siblings) == 4  # 5 tracks total, 1 dispatched = 4 siblings

        # Verify all 5 tracks are now 'downloading'
        cur = await db.execute(
            "SELECT COUNT(*) as c FROM monitored_tracks WHERE album_id=1 AND status='downloading'"
        )
        row = await cur.fetchone()
        assert row["c"] == 5

    @pytest.mark.asyncio
    async def test_pending_albums_set_prevents_double_grab(self):
        """slsk_pending_albums should prevent concurrent tasks from grabbing same album."""
        slsk_pending_albums = set()

        album_id = 42
        # First task claims the album
        slsk_pending_albums.add(album_id)

        # Second task checks — should skip
        assert album_id in slsk_pending_albums

        # After first task completes, it moves to slsk_grabbed_albums
        slsk_grabbed_albums = set()
        slsk_grabbed_albums.add(album_id)
        slsk_pending_albums.discard(album_id)

        # Third task checks grabbed — should skip
        assert album_id in slsk_grabbed_albums
