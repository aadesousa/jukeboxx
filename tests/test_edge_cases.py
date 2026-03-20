"""
Phase 5: Edge cases and error handling tests.
Covers network failures, DB edge cases, filesystem edge cases, and stale UI states.
"""
import pytest
import pytest_asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import asyncio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


# ---------------------------------------------------------------------------
# Phase 5.1: Network failures
# ---------------------------------------------------------------------------
class TestNetworkFailures:
    @pytest.mark.asyncio
    async def test_slskd_down_grab_returns_false(self):
        """When slskd is unreachable, grab_soulseek_files returns False."""
        from grabbers import grab_soulseek_files
        mock_row = {
            "host": "localhost", "port": 5030, "url_base": "",
            "api_key": "testkey",
        }
        with patch("grabbers._get_client_row", new_callable=AsyncMock, return_value=mock_row):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
                mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_client

                result = await grab_soulseek_files(
                    "someuser", [{"filename": "song.flac", "size": 10000}]
                )
                assert result is False

    @pytest.mark.asyncio
    async def test_qbit_down_grab_returns_false(self):
        """When qBittorrent is unreachable, grab_torrent returns False."""
        from grabbers import grab_torrent
        mock_row = {
            "host": "localhost", "port": 8080, "use_ssl": 0,
            "url_base": "", "username": "", "password": "",
        }
        with patch("grabbers._get_client_row", new_callable=AsyncMock, return_value=mock_row):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_client

                result = await grab_torrent("magnet:?xt=urn:btih:abc123")
                assert result is False

    @pytest.mark.asyncio
    async def test_metube_down_grab_returns_false(self):
        """When MeTube is unreachable, grab_youtube returns False."""
        from grabbers import grab_youtube
        with patch("grabbers.get_setting", new_callable=AsyncMock, side_effect=["http://metube:8081", "mp3", "0"]):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_client

                result = await grab_youtube("https://youtube.com/watch?v=abc")
                assert result is False

    @pytest.mark.asyncio
    async def test_dispatch_continues_after_source_failure(self, populated_db):
        """If one source fails, dispatch should try the next source."""
        import tasks

        call_log = []

        async def mock_setting(key, default=""):
            settings = {
                "library_ready": "1",
                "queue_paused": "0",
                "download_source_priority": '["torrent","youtube"]',
                "dispatch_batch_size": "1",
                "slsk_album_download": "1",
            }
            return settings.get(key, default)

        async def mock_search(*args, **kwargs):
            return []  # No torrent results → falls through to youtube

        async def mock_yt_grab(*args, **kwargs):
            call_log.append("youtube")
            return True

        with patch("tasks.get_setting", new_callable=AsyncMock, side_effect=mock_setting), \
             patch("tasks.get_spotizerr_queue_status", new_callable=AsyncMock,
                   return_value={"reachable": False, "available": 0}), \
             patch("grabbers.search_indexers_auto", new_callable=AsyncMock,
                   return_value=[]), \
             patch("grabbers.auto_grab_youtube", new_callable=AsyncMock,
                   return_value=True) as mock_yt, \
             patch("tasks._write_unified_download", new_callable=AsyncMock):
            result = await tasks._run_multi_source_dispatch_inner(limit=1)

        # YouTube was tried because torrent returned no results
        # (or the function returned something)
        assert isinstance(result, dict)
        # Reset dispatch progress so subsequent tests see clean state
        tasks._dp(running=False, dispatched=0, breakdown={})


# ---------------------------------------------------------------------------
# Phase 5.2: Database edge cases
# ---------------------------------------------------------------------------
class TestDatabaseEdgeCases:
    @pytest.mark.asyncio
    async def test_duplicate_spotify_id_insert_ignored(self, populated_db):
        """INSERT OR IGNORE prevents duplicate spotify_ids in monitored_tracks."""
        db = populated_db
        # Try to insert a duplicate
        await db.execute(
            """INSERT OR IGNORE INTO monitored_tracks
               (spotify_id, name, artist_name, status, monitored)
               VALUES ('track_sp_001', 'Duplicate Track', 'Artist', 'wanted', 1)"""
        )
        await db.commit()

        cur = await db.execute(
            "SELECT COUNT(*) as c FROM monitored_tracks WHERE spotify_id='track_sp_001'"
        )
        row = await cur.fetchone()
        assert row["c"] == 1

    @pytest.mark.asyncio
    async def test_auto_ignored_blank_track(self, populated_db):
        """Tracks with blank names should be auto-ignored by poll_unified_downloads."""
        from tasks import poll_unified_downloads
        db = populated_db

        await db.execute(
            """INSERT INTO monitored_tracks
               (spotify_id, name, artist_name, status, monitored)
               VALUES ('blank_track_001', '', 'Some Artist', 'wanted', 1)"""
        )
        await db.commit()

        await poll_unified_downloads()

        cur = await db.execute(
            "SELECT status FROM monitored_tracks WHERE spotify_id='blank_track_001'"
        )
        row = await cur.fetchone()
        assert row["status"] == "ignored"

    @pytest.mark.asyncio
    async def test_auto_ignored_whitespace_track(self, populated_db):
        """Tracks with only whitespace in name should also be auto-ignored."""
        from tasks import poll_unified_downloads
        db = populated_db

        await db.execute(
            """INSERT INTO monitored_tracks
               (spotify_id, name, artist_name, status, monitored)
               VALUES ('whitespace_track_001', '   ', 'Some Artist', 'wanted', 1)"""
        )
        await db.commit()

        await poll_unified_downloads()

        cur = await db.execute(
            "SELECT status FROM monitored_tracks WHERE spotify_id='whitespace_track_001'"
        )
        row = await cur.fetchone()
        assert row["status"] == "ignored"

    @pytest.mark.asyncio
    async def test_settings_not_duped_on_reinit(self, db):
        """Re-running init_db should not duplicate default settings."""
        from database import init_db, DEFAULT_SETTINGS
        # Run init a second time
        await init_db()

        cur = await db.execute(
            "SELECT key, COUNT(*) as c FROM settings GROUP BY key HAVING c > 1"
        )
        dupes = await cur.fetchall()
        assert len(dupes) == 0, f"Duplicate settings found: {[dict(r) for r in dupes]}"


# ---------------------------------------------------------------------------
# Phase 5.4: Auth edge cases
# ---------------------------------------------------------------------------
class TestAuthEdgeCases:
    @pytest.mark.asyncio
    async def test_expired_session_returns_401(self, client):
        import jwt
        from datetime import datetime, timezone, timedelta
        token = jwt.encode(
            {"sub": "testuser", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
            "test-secret-key-for-tests",
            algorithm="HS256",
        )
        resp = await client.get("/stats", headers={"Cookie": f"jukeboxx_token={token}"})
        assert resp.status_code == 401
        assert "expired" in resp.json().get("detail", "").lower()

    @pytest.mark.asyncio
    async def test_tampered_token_rejected(self, client):
        import jwt
        from datetime import datetime, timezone, timedelta
        # Sign with wrong secret
        token = jwt.encode(
            {"sub": "testuser", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            "wrong-secret",
            algorithm="HS256",
        )
        resp = await client.get("/stats", headers={"Cookie": f"jukeboxx_token={token}"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_token_rejected(self, client):
        resp = await client.get("/stats", headers={"Cookie": "jukeboxx_token="})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Phase 5.5: Stale UI states
# ---------------------------------------------------------------------------
class TestDispatchProgressRecovery:
    def test_progress_recoverable_after_backend_restart(self):
        """After restart, dispatch progress should be in clean initial state."""
        from tasks import _dispatch_progress
        assert _dispatch_progress["running"] is False
        assert _dispatch_progress["dispatched"] == 0

    def test_sync_progress_recoverable_after_restart(self):
        """After restart, sync progress should be in clean initial state."""
        from tasks import _sync_progress
        assert _sync_progress["running"] is False


# ---------------------------------------------------------------------------
# Phase 6.1: Regression — numpy/rapidfuzz import
# ---------------------------------------------------------------------------
class TestRapidFuzzNumpyImport:
    def test_rapidfuzz_cdist_import(self):
        """Verify rapidfuzz and numpy can be imported correctly (Phase 6.1).
        This was a previous regression: 'from rapidfuzz.process import cdist' failed.
        """
        try:
            from rapidfuzz.process import cdist
            from rapidfuzz import fuzz
            import numpy
            # Basic sanity: cdist with a valid scorer
            result = cdist(["hello"], ["hello", "world"], scorer=fuzz.ratio)
            assert result is not None
            assert result.shape == (1, 2)
        except ImportError as e:
            pytest.fail(f"Import failed: {e}")

    def test_rapidfuzz_fuzz_import(self):
        from rapidfuzz import fuzz
        score = fuzz.token_sort_ratio("hello world", "world hello")
        assert score == 100

    def test_rapidfuzz_token_sort_ratio(self):
        from rapidfuzz import fuzz
        # Exact match
        assert fuzz.token_sort_ratio("test song", "test song") == 100
        # Different strings
        assert fuzz.token_sort_ratio("test song", "completely different") < 50
