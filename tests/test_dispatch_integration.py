"""
Dispatch pipeline integration tests — designed to expose real failures.

Tests the actual _run_multi_source_dispatch_inner logic:
- Source fallback chain (torrent fail → try youtube)
- Break on first success (no double-dispatch)
- DB state after dispatch (track marked 'downloading', unified_download created)
- Source priority order respected
- Results without download_url not grabbed
- Quality profile ignored_words filters out results
- Spotizerr skipped when capacity=0
- state['dispatched'] matches actual DB records
- Soulseek album dedup: siblings get unified_download records and 'downloading' status
- Soulseek slsk_grabbed_albums prevents second album grab in same run
- poll_unified_downloads: album rollup on completion, prune to 3 failed, stale boundary,
  NULL monitored_track_id handled gracefully
"""
import pytest
import pytest_asyncio
import sys
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _settings(**overrides):
    """Return a mock_setting side_effect with sensible defaults."""
    base = {
        "library_ready": "1",
        "queue_paused": "0",
        "download_source_priority": '["torrent","youtube"]',
        "dispatch_batch_size": "10",
        "slsk_album_download": "1",
    }
    base.update(overrides)
    async def _get(key, default=""):
        return base.get(key, default)
    return _get


def _torrent_hit(url="magnet:?xt=urn:btih:abc", seeders=10):
    return [{"title": "Artist Track FLAC", "download_url": url, "seeders": seeders}]


# ---------------------------------------------------------------------------
# Source fallback chain
# ---------------------------------------------------------------------------
class TestDispatchSourceFallback:
    @pytest.mark.asyncio
    async def test_torrent_grab_fail_falls_to_youtube(self, populated_db):
        """Torrent search returns results but grab_torrent returns False —
        dispatch must continue to next source (youtube)."""
        import tasks

        with patch("tasks.get_setting", new_callable=AsyncMock,
                   side_effect=_settings(dispatch_batch_size="1")), \
             patch("tasks.get_spotizerr_queue_status", new_callable=AsyncMock,
                   return_value={"reachable": False, "available": 0}), \
             patch("grabbers.search_indexers_auto", new_callable=AsyncMock,
                   return_value=_torrent_hit()), \
             patch("grabbers.grab_torrent", new_callable=AsyncMock,
                   return_value=False) as mock_torrent, \
             patch("grabbers.auto_grab_youtube", new_callable=AsyncMock,
                   return_value=True) as mock_yt, \
             patch("tasks._write_unified_download", new_callable=AsyncMock):
            result = await tasks._run_multi_source_dispatch_inner(limit=1)

        mock_torrent.assert_called_once()
        mock_yt.assert_called_once(), (
            "youtube must be tried after torrent grab failure"
        )
        assert result.get("breakdown", {}).get("youtube", 0) == 1

    @pytest.mark.asyncio
    async def test_torrent_success_does_not_try_youtube(self, populated_db):
        """Successful torrent grab must break the source loop — no double dispatch."""
        import tasks

        with patch("tasks.get_setting", new_callable=AsyncMock,
                   side_effect=_settings(dispatch_batch_size="1")), \
             patch("tasks.get_spotizerr_queue_status", new_callable=AsyncMock,
                   return_value={"reachable": False, "available": 0}), \
             patch("grabbers.search_indexers_auto", new_callable=AsyncMock,
                   return_value=_torrent_hit()), \
             patch("grabbers.grab_torrent", new_callable=AsyncMock, return_value=True), \
             patch("grabbers.auto_grab_youtube", new_callable=AsyncMock,
                   return_value=True) as mock_yt, \
             patch("tasks._write_unified_download", new_callable=AsyncMock):
            result = await tasks._run_multi_source_dispatch_inner(limit=1)

        mock_yt.assert_not_called(), "youtube must NOT be tried after successful torrent grab"
        assert result.get("breakdown", {}).get("torrent", 0) == 1

    @pytest.mark.asyncio
    async def test_source_priority_order_respected(self, populated_db):
        """With priority=['youtube','torrent'], youtube must be tried before torrent."""
        import tasks

        sources_tried = []

        async def mock_yt(*a, **kw):
            sources_tried.append("youtube")
            return True

        async def mock_torrent_search(*a, **kw):
            sources_tried.append("torrent")
            return _torrent_hit()

        with patch("tasks.get_setting", new_callable=AsyncMock,
                   side_effect=_settings(
                       download_source_priority='["youtube","torrent"]',
                       dispatch_batch_size="1"
                   )), \
             patch("tasks.get_spotizerr_queue_status", new_callable=AsyncMock,
                   return_value={"reachable": False, "available": 0}), \
             patch("grabbers.auto_grab_youtube", side_effect=mock_yt), \
             patch("grabbers.search_indexers_auto", side_effect=mock_torrent_search), \
             patch("tasks._write_unified_download", new_callable=AsyncMock):
            await tasks._run_multi_source_dispatch_inner(limit=1)

        assert sources_tried, "No sources were tried"
        assert sources_tried[0] == "youtube", (
            f"youtube must be first when it's first in priority. Got: {sources_tried}"
        )
        assert "torrent" not in sources_tried, (
            "torrent must not be tried after youtube succeeds"
        )

    @pytest.mark.asyncio
    async def test_result_without_download_url_not_grabbed(self, populated_db):
        """Search result missing 'download_url' must be filtered — grab_torrent not called."""
        import tasks

        bad_result = [{"title": "Artist FLAC", "seeders": 10}]  # no download_url

        with patch("tasks.get_setting", new_callable=AsyncMock,
                   side_effect=_settings(dispatch_batch_size="1")), \
             patch("tasks.get_spotizerr_queue_status", new_callable=AsyncMock,
                   return_value={"reachable": False, "available": 0}), \
             patch("grabbers.search_indexers_auto", new_callable=AsyncMock,
                   return_value=bad_result), \
             patch("grabbers.grab_torrent", new_callable=AsyncMock,
                   return_value=True) as mock_grab, \
             patch("grabbers.auto_grab_youtube", new_callable=AsyncMock, return_value=False), \
             patch("tasks._write_unified_download", new_callable=AsyncMock):
            await tasks._run_multi_source_dispatch_inner(limit=1)

        mock_grab.assert_not_called(), (
            "grab_torrent must not be called for results without download_url"
        )

    @pytest.mark.asyncio
    async def test_ignored_word_schema_bug(self, populated_db):
        """SCHEMA BUG: quality_profiles table has no ignored_words/preferred_words/required_words
        columns, but _score_result() references them. Word-filtering feature is completely broken.

        This test documents the gap: attempting to use these columns raises OperationalError.
        Fix: add ignored_words, preferred_words, required_words TEXT columns to quality_profiles.
        """
        import sqlite3
        db = populated_db

        with pytest.raises(Exception) as exc_info:
            await db.execute(
                "INSERT INTO quality_profiles (id, name, preferred_format, ignored_words) "
                "VALUES (99, 'NoKaraoke', 'any', 'karaoke')"
            )

        assert "ignored_words" in str(exc_info.value).lower() or "no column" in str(exc_info.value).lower(), (
            "Expected OperationalError about missing ignored_words column, "
            f"got: {exc_info.value}"
        )

    @pytest.mark.asyncio
    async def test_score_result_respects_ignored_words_when_provided(self):
        """When _score_result() is given a quality profile dict with ignored_words,
        the filtering logic DOES work at the function level — the schema is the only gap.
        Fix the schema (add column) and the DB→dispatch pipeline will filter correctly."""
        from grabbers import _score_result

        qp_with_ignored = {"ignored_words": "karaoke", "preferred_format": "any", "min_bitrate": 0}
        karaoke_result = {"title": "Artist Track Karaoke FLAC", "download_url": "magnet:abc", "seeders": 10}
        clean_result = {"title": "Artist Track FLAC", "download_url": "magnet:abc", "seeders": 10}

        karaoke_score = _score_result(karaoke_result, qp_with_ignored)
        clean_score = _score_result(clean_result, qp_with_ignored)

        assert karaoke_score <= -999, (
            f"Result with ignored word 'karaoke' should score -999 (filtered), got {karaoke_score}. "
            "If this fails, _score_result() doesn't honor ignored_words either."
        )
        assert clean_score > -999, (
            f"Clean result should not be filtered, got {clean_score}"
        )

    @pytest.mark.asyncio
    async def test_spotizerr_skipped_when_no_available_slots(self, populated_db):
        """When spotizerr reports available=0, it must be skipped entirely."""
        import tasks

        with patch("tasks.get_setting", new_callable=AsyncMock,
                   side_effect=_settings(
                       download_source_priority='["spotizerr","youtube"]',
                       dispatch_batch_size="1"
                   )), \
             patch("tasks.get_spotizerr_queue_status", new_callable=AsyncMock,
                   return_value={"reachable": True, "available": 0}), \
             patch("tasks.dispatch_download", new_callable=AsyncMock,
                   return_value={"status": "downloading"}) as mock_sp, \
             patch("grabbers.auto_grab_youtube", new_callable=AsyncMock,
                   return_value=True) as mock_yt, \
             patch("tasks._write_unified_download", new_callable=AsyncMock):
            result = await tasks._run_multi_source_dispatch_inner(limit=1)

        mock_sp.assert_not_called(), "spotizerr must be skipped when available=0"
        mock_yt.assert_called_once(), "Should fall through to youtube after spotizerr skip"


# ---------------------------------------------------------------------------
# DB state after dispatch
# ---------------------------------------------------------------------------
class TestDispatchDbState:
    @pytest.mark.asyncio
    async def test_track_marked_downloading_after_success(self, populated_db):
        """After successful dispatch, monitored_track.status must be 'downloading'."""
        import tasks, database

        with patch("tasks.get_setting", new_callable=AsyncMock,
                   side_effect=_settings(dispatch_batch_size="1")), \
             patch("tasks.get_spotizerr_queue_status", new_callable=AsyncMock,
                   return_value={"reachable": False, "available": 0}), \
             patch("grabbers.search_indexers_auto", new_callable=AsyncMock,
                   return_value=_torrent_hit()), \
             patch("grabbers.grab_torrent", new_callable=AsyncMock, return_value=True):
            await tasks._run_multi_source_dispatch_inner(limit=1)

        db = await database.get_db()
        try:
            cur = await db.execute(
                "SELECT COUNT(*) as c FROM monitored_tracks WHERE status='downloading'"
            )
            count = (await cur.fetchone())["c"]
        finally:
            await db.close()

        assert count >= 1, (
            "At least one track must be marked 'downloading' after successful dispatch"
        )

    @pytest.mark.asyncio
    async def test_unified_download_record_created_with_correct_source(self, populated_db):
        """After dispatch, unified_downloads must have a row with correct source and URL."""
        import tasks, database
        magnet = "magnet:?xt=urn:btih:TESTMAGNET999"

        with patch("tasks.get_setting", new_callable=AsyncMock,
                   side_effect=_settings(dispatch_batch_size="1")), \
             patch("tasks.get_spotizerr_queue_status", new_callable=AsyncMock,
                   return_value={"reachable": False, "available": 0}), \
             patch("grabbers.search_indexers_auto", new_callable=AsyncMock,
                   return_value=_torrent_hit(url=magnet)), \
             patch("grabbers.grab_torrent", new_callable=AsyncMock, return_value=True):
            await tasks._run_multi_source_dispatch_inner(limit=1)

        db = await database.get_db()
        try:
            cur = await db.execute(
                "SELECT source, source_url, status FROM unified_downloads WHERE source='torrent'"
            )
            row = await cur.fetchone()
        finally:
            await db.close()

        assert row is not None, "No unified_download record created"
        assert row["source"] == "torrent"
        assert row["status"] == "queued"
        assert row["source_url"] == magnet, (
            f"source_url mismatch. Expected {magnet}, got {row['source_url']}"
        )

    @pytest.mark.asyncio
    async def test_dispatched_count_matches_db_records(self, populated_db):
        """state['dispatched'] return value must equal actual unified_download rows created."""
        import tasks, database

        with patch("tasks.get_setting", new_callable=AsyncMock,
                   side_effect=_settings(dispatch_batch_size="5")), \
             patch("tasks.get_spotizerr_queue_status", new_callable=AsyncMock,
                   return_value={"reachable": False, "available": 0}), \
             patch("grabbers.search_indexers_auto", new_callable=AsyncMock,
                   return_value=_torrent_hit()), \
             patch("grabbers.grab_torrent", new_callable=AsyncMock, return_value=True):
            result = await tasks._run_multi_source_dispatch_inner(limit=5)

        reported = result["dispatched"]
        db = await database.get_db()
        try:
            cur = await db.execute(
                "SELECT COUNT(*) as c FROM unified_downloads WHERE source='torrent'"
            )
            actual = (await cur.fetchone())["c"]
        finally:
            await db.close()

        assert reported == actual, (
            f"state['dispatched']={reported} but actual DB records={actual}. "
            "The counter and DB writes are out of sync."
        )

    @pytest.mark.asyncio
    async def test_failed_grab_does_not_mark_track_downloading(self, populated_db):
        """If all sources fail, the track must remain 'wanted', not 'downloading'."""
        import tasks, database

        with patch("tasks.get_setting", new_callable=AsyncMock,
                   side_effect=_settings(dispatch_batch_size="1")), \
             patch("tasks.get_spotizerr_queue_status", new_callable=AsyncMock,
                   return_value={"reachable": False, "available": 0}), \
             patch("grabbers.search_indexers_auto", new_callable=AsyncMock,
                   return_value=_torrent_hit()), \
             patch("grabbers.grab_torrent", new_callable=AsyncMock, return_value=False), \
             patch("grabbers.auto_grab_youtube", new_callable=AsyncMock, return_value=False):
            result = await tasks._run_multi_source_dispatch_inner(limit=1)

        assert result["dispatched"] == 0

        db = await database.get_db()
        try:
            cur = await db.execute(
                "SELECT COUNT(*) as c FROM monitored_tracks WHERE status='downloading'"
            )
            count = (await cur.fetchone())["c"]
        finally:
            await db.close()

        assert count == 0, (
            f"{count} track(s) marked 'downloading' despite all grabs failing"
        )


# ---------------------------------------------------------------------------
# Soulseek album dedup in dispatch
# ---------------------------------------------------------------------------
class TestDispatchSoulseekAlbumDedup:
    @pytest.mark.asyncio
    async def test_sibling_tracks_get_unified_downloads_and_downloading_status(self, populated_db):
        """When soulseek grabs album track 1, the other 4 sibling tracks must:
        1. be marked 'downloading'
        2. each have a unified_download record with source='soulseek'"""
        import tasks, database

        with patch("tasks.get_setting", new_callable=AsyncMock,
                   side_effect=_settings(
                       download_source_priority='["soulseek"]',
                       slsk_album_download="1",
                       dispatch_batch_size="1",
                   )), \
             patch("tasks.get_spotizerr_queue_status", new_callable=AsyncMock,
                   return_value={"reachable": False, "available": 0}), \
             patch("grabbers.auto_grab_soulseek", new_callable=AsyncMock,
                   return_value=(True, "user1|Music/Artist/Album")):
            result = await tasks._run_multi_source_dispatch_inner(limit=1)

        db = await database.get_db()
        try:
            cur = await db.execute(
                "SELECT COUNT(*) as c FROM unified_downloads "
                "WHERE source='soulseek' AND monitored_album_id=1"
            )
            ud_count = (await cur.fetchone())["c"]

            cur2 = await db.execute(
                "SELECT COUNT(*) as c FROM monitored_tracks "
                "WHERE album_id=1 AND status='downloading'"
            )
            dl_count = (await cur2.fetchone())["c"]
        finally:
            await db.close()

        assert ud_count >= 5, (
            f"Expected ≥5 unified_download records for album 1 (1 main + 4 siblings), got {ud_count}"
        )
        assert dl_count == 5, (
            f"All 5 album tracks should be 'downloading', got {dl_count}. "
            "Soulseek sibling dedup is broken."
        )

    @pytest.mark.asyncio
    async def test_album_grabbed_once_per_run(self, populated_db):
        """With 5 wanted tracks from the same album, soulseek must grab only once.
        slsk_grabbed_albums prevents re-grabbing siblings as individual dispatches."""
        import tasks

        grab_calls = []

        async def mock_slsk(name, artist, album, skip_keys=None):
            grab_calls.append(name)
            return (True, "user|folder")

        with patch("tasks.get_setting", new_callable=AsyncMock,
                   side_effect=_settings(
                       download_source_priority='["soulseek"]',
                       slsk_album_download="1",
                       dispatch_batch_size="5",
                   )), \
             patch("tasks.get_spotizerr_queue_status", new_callable=AsyncMock,
                   return_value={"reachable": False, "available": 0}), \
             patch("grabbers.auto_grab_soulseek", side_effect=mock_slsk):
            await tasks._run_multi_source_dispatch_inner(limit=5)

        assert len(grab_calls) == 1, (
            f"Soulseek grabbed {len(grab_calls)} times for 5 tracks from the same album. "
            "Expected exactly 1 (siblings should be pre-dispatched, not re-grabbed)."
        )

    @pytest.mark.asyncio
    async def test_slsk_key_dedup_prevents_same_folder_twice(self, populated_db):
        """skip_keys prevents re-grabbing the same username|folder within one dispatch run."""
        import tasks

        grabbed_keys = []

        async def mock_slsk(name, artist, album, skip_keys=None):
            key = "user1|Music/Artist/SameFolder"
            if skip_keys is not None and key in skip_keys:
                return (False, key)
            grabbed_keys.append(key)
            return (True, key)

        # Add a second album with a wanted track
        await populated_db.execute(
            "INSERT OR IGNORE INTO monitored_albums "
            "(id, spotify_id, artist_id, artist_spotify_id, name, album_type, status, monitored) "
            "VALUES (99, 'album_sp_099', 1, 'artist_sp_001', 'Other Album', 'album', 'wanted', 1)"
        )
        await populated_db.execute(
            "INSERT OR IGNORE INTO monitored_tracks "
            "(id, spotify_id, album_id, name, artist_name, album_name, status, monitored) "
            "VALUES (99, 'track_sp_099', 99, 'Other Track', 'Test Artist', 'Other Album', 'wanted', 1)"
        )
        await populated_db.commit()

        with patch("tasks.get_setting", new_callable=AsyncMock,
                   side_effect=_settings(
                       download_source_priority='["soulseek"]',
                       slsk_album_download="0",
                       dispatch_batch_size="10",
                   )), \
             patch("tasks.get_spotizerr_queue_status", new_callable=AsyncMock,
                   return_value={"reachable": False, "available": 0}), \
             patch("grabbers.auto_grab_soulseek", side_effect=mock_slsk):
            await tasks._run_multi_source_dispatch_inner(limit=10)

        assert len(grabbed_keys) == 1, (
            f"Same soulseek folder grabbed {len(grabbed_keys)} times. "
            "skip_keys dedup is broken."
        )


# ---------------------------------------------------------------------------
# poll_unified_downloads edge cases
# ---------------------------------------------------------------------------
class TestPollUnifiedDownloads:
    @pytest.mark.asyncio
    async def test_completed_track_triggers_album_rollup(self, populated_db):
        """When a track completes, its album's status must be re-evaluated via _update_album_completion."""
        import tasks, database
        db = populated_db

        # All 5 tracks in album 1 already have status='have' in the DB
        await db.execute("UPDATE monitored_tracks SET status='have' WHERE album_id=1")
        # Album is stuck at 'partial' — poll should roll it up
        await db.execute("UPDATE monitored_albums SET status='partial' WHERE id=1")
        # One queued unified_download for track 1 (the trigger)
        await db.execute(
            "INSERT INTO unified_downloads "
            "(spotify_id, item_type, title, artist, status, source, monitored_track_id) "
            "VALUES ('track_sp_001', 'track', 'Track 1', 'Test Artist', 'queued', 'torrent', 1)"
        )
        await db.commit()

        with patch("discord.notify_download_complete", new_callable=AsyncMock):
            await tasks.poll_unified_downloads()

        db2 = await database.get_db()
        try:
            cur = await db2.execute("SELECT status FROM monitored_albums WHERE id=1")
            row = await cur.fetchone()
        finally:
            await db2.close()

        assert row["status"] == "have", (
            f"Album should roll up to 'have' when all tracks complete. Got: '{row['status']}'"
        )

    @pytest.mark.asyncio
    async def test_stale_over_2h_marked_failed(self, populated_db):
        """Downloads older than 2 hours must be marked 'failed'."""
        import tasks, database
        db = populated_db
        over_2h = (datetime.utcnow() - timedelta(hours=2, seconds=10)).strftime("%Y-%m-%d %H:%M:%S")

        await db.execute(
            "INSERT INTO unified_downloads "
            "(spotify_id, item_type, title, artist, status, source, monitored_track_id, created_at) "
            "VALUES ('track_sp_007', 'track', 'Track 7', 'Test Artist', 'queued', 'torrent', 7, ?)",
            (over_2h,),
        )
        await db.commit()

        await tasks.poll_unified_downloads()

        db2 = await database.get_db()
        try:
            cur = await db2.execute(
                "SELECT status FROM unified_downloads WHERE spotify_id='track_sp_007'"
            )
            row = await cur.fetchone()
        finally:
            await db2.close()

        assert row["status"] == "failed", (
            f"2h+10s old download should be 'failed', got '{row['status']}'"
        )

    @pytest.mark.asyncio
    async def test_stale_track_reset_to_wanted(self, populated_db):
        """When a download times out, its linked track must be reset to 'wanted'."""
        import tasks, database
        db = populated_db
        over_2h = (datetime.utcnow() - timedelta(hours=2, seconds=30)).strftime("%Y-%m-%d %H:%M:%S")

        await db.execute("UPDATE monitored_tracks SET status='downloading' WHERE id=7")
        await db.execute(
            "INSERT INTO unified_downloads "
            "(spotify_id, item_type, title, artist, status, source, monitored_track_id, created_at) "
            "VALUES ('track_sp_007', 'track', 'Track 7', 'Test Artist', 'queued', 'torrent', 7, ?)",
            (over_2h,),
        )
        await db.commit()

        await tasks.poll_unified_downloads()

        db2 = await database.get_db()
        try:
            cur = await db2.execute("SELECT status FROM monitored_tracks WHERE id=7")
            row = await cur.fetchone()
        finally:
            await db2.close()

        assert row["status"] == "wanted", (
            f"Track should be reset to 'wanted' after download timeout. Got: '{row['status']}'"
        )

    @pytest.mark.asyncio
    async def test_failed_records_pruned_to_max_3(self, populated_db):
        """Old failed unified_downloads must be pruned to keep only the 3 most recent per track."""
        import tasks, database
        db = populated_db

        # Insert 5 failed records for track 1 at different times
        for i in range(5):
            ts = (datetime.utcnow() - timedelta(hours=i + 1)).strftime("%Y-%m-%d %H:%M:%S")
            await db.execute(
                "INSERT INTO unified_downloads "
                "(spotify_id, item_type, title, artist, status, source, monitored_track_id, updated_at) "
                "VALUES ('track_sp_001', 'track', 'Track 1', 'Test Artist', 'failed', 'torrent', 1, ?)",
                (ts,),
            )
        await db.commit()

        await tasks.poll_unified_downloads()

        db2 = await database.get_db()
        try:
            cur = await db2.execute(
                "SELECT COUNT(*) as c FROM unified_downloads "
                "WHERE monitored_track_id=1 AND status='failed'"
            )
            count = (await cur.fetchone())["c"]
        finally:
            await db2.close()

        assert count <= 3, (
            f"Failed records should be pruned to max 3, found {count}. "
            "Old failed records are accumulating and will bloat the database."
        )

    @pytest.mark.asyncio
    async def test_null_monitored_track_id_does_not_crash(self, populated_db):
        """Stale download with NULL monitored_track_id must not crash poll."""
        import tasks, database
        db = populated_db
        old = (datetime.utcnow() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")

        await db.execute(
            "INSERT INTO unified_downloads "
            "(spotify_id, item_type, title, artist, status, source, monitored_track_id, created_at) "
            "VALUES ('orphan_sp_999', 'track', 'Orphan', 'Nobody', 'queued', 'torrent', NULL, ?)",
            (old,),
        )
        await db.commit()

        # Must not raise
        await tasks.poll_unified_downloads()

        db2 = await database.get_db()
        try:
            cur = await db2.execute(
                "SELECT status FROM unified_downloads WHERE spotify_id='orphan_sp_999'"
            )
            row = await cur.fetchone()
        finally:
            await db2.close()

        assert row["status"] == "failed", (
            "Stale download with NULL monitored_track_id should still be marked failed"
        )

    @pytest.mark.asyncio
    async def test_track_without_active_download_reset_from_downloading(self, populated_db):
        """Track stuck in 'downloading' with no active unified_download must reset to 'wanted'."""
        import tasks, database
        db = populated_db

        # Track 3 stuck as 'downloading' with no unified_download
        await db.execute("UPDATE monitored_tracks SET status='downloading' WHERE id=3")
        await db.commit()

        await tasks.poll_unified_downloads()

        db2 = await database.get_db()
        try:
            cur = await db2.execute("SELECT status FROM monitored_tracks WHERE id=3")
            row = await cur.fetchone()
        finally:
            await db2.close()

        assert row["status"] == "wanted", (
            f"Orphaned 'downloading' track must reset to 'wanted'. Got: '{row['status']}'"
        )
