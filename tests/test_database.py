"""
Phase 6.1 + Phase 7: Database initialization, settings, migrations, and data integrity.
Tests the DB schema, default settings, and integrity constraints.
"""
import pytest
import pytest_asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


# ---------------------------------------------------------------------------
# Schema & initialization
# ---------------------------------------------------------------------------
class TestDatabaseInit:
    @pytest.mark.asyncio
    async def test_init_creates_all_tables(self, db):
        """Verify init_db creates every expected table."""
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in await cur.fetchall()}
        expected = {
            "tracks", "spotify_auth", "sync_items", "downloads",
            "duplicate_pairs", "scan_history", "settings", "auth",
            "notifications", "activity_log", "spotify_cache",
            "wanted_artists", "wanted_albums", "match_reviews",
            "youtube_downloads", "youtube_review_queue",
            "quality_profiles", "monitored_artists", "monitored_albums",
            "monitored_tracks", "unified_downloads", "release_calendar",
            "download_clients", "indexers", "download_history",
            "metadata_profiles", "release_profiles", "blocklist",
        }
        missing = expected - tables
        assert not missing, f"Missing tables: {missing}"

    @pytest.mark.asyncio
    async def test_default_settings_populated(self, db):
        """Verify all default settings are seeded."""
        from database import DEFAULT_SETTINGS
        for key in DEFAULT_SETTINGS:
            cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
            row = await cur.fetchone()
            assert row is not None, f"Missing default setting: {key}"

    @pytest.mark.asyncio
    async def test_default_quality_profiles(self, db):
        """Verify seed quality profiles exist."""
        cur = await db.execute("SELECT name FROM quality_profiles ORDER BY id")
        profiles = [row[0] for row in await cur.fetchall()]
        assert "Any" in profiles
        assert "Lossless (FLAC)" in profiles
        assert "High (MP3 320)" in profiles

    @pytest.mark.asyncio
    async def test_default_metadata_profiles(self, db):
        cur = await db.execute("SELECT name FROM metadata_profiles ORDER BY id")
        profiles = [row[0] for row in await cur.fetchall()]
        assert "Standard" in profiles
        assert "All" in profiles

    @pytest.mark.asyncio
    async def test_default_release_profiles(self, db):
        cur = await db.execute("SELECT name FROM release_profiles ORDER BY id")
        profiles = [row[0] for row in await cur.fetchall()]
        assert "Default" in profiles


# ---------------------------------------------------------------------------
# Settings CRUD
# ---------------------------------------------------------------------------
class TestSettings:
    @pytest.mark.asyncio
    async def test_get_setting_returns_default(self, db):
        from database import get_setting
        val = await get_setting("nonexistent_key", "fallback")
        assert val == "fallback"

    @pytest.mark.asyncio
    async def test_set_and_get_setting(self, db):
        from database import get_setting, set_setting
        await set_setting("test_key", "test_value")
        val = await get_setting("test_key")
        assert val == "test_value"

    @pytest.mark.asyncio
    async def test_set_setting_overwrites(self, db):
        from database import get_setting, set_setting
        await set_setting("overwrite_key", "v1")
        await set_setting("overwrite_key", "v2")
        val = await get_setting("overwrite_key")
        assert val == "v2"


# ---------------------------------------------------------------------------
# Notifications & Activity
# ---------------------------------------------------------------------------
class TestNotificationsActivity:
    @pytest.mark.asyncio
    async def test_add_notification(self, db):
        from database import add_notification
        await add_notification("info", "Test Title", "Test message")
        cur = await db.execute("SELECT * FROM notifications WHERE title='Test Title'")
        row = await cur.fetchone()
        assert row is not None
        assert row["type"] == "info"
        assert row["message"] == "Test message"
        assert row["read"] == 0

    @pytest.mark.asyncio
    async def test_add_activity(self, db):
        from database import add_activity
        await add_activity("test_action", "test detail")
        cur = await db.execute("SELECT * FROM activity_log WHERE action='test_action'")
        row = await cur.fetchone()
        assert row is not None
        assert row["detail"] == "test detail"


# ---------------------------------------------------------------------------
# Phase 7: Data Integrity Checks (SQL queries from test plan)
# ---------------------------------------------------------------------------
class TestDataIntegrity:
    @pytest.mark.asyncio
    async def test_no_orphaned_downloading_tracks(self, populated_db):
        """Tracks in 'downloading' status must have a matching active unified_download."""
        db = populated_db
        cur = await db.execute(
            """SELECT COUNT(*) as c FROM monitored_tracks mt
               WHERE mt.status = 'downloading'
               AND NOT EXISTS (
                   SELECT 1 FROM unified_downloads ud
                   WHERE ud.monitored_track_id = mt.id
                   AND ud.status IN ('queued','downloading')
               )"""
        )
        row = await cur.fetchone()
        assert row["c"] == 0, f"Found {row['c']} orphaned downloading tracks"

    @pytest.mark.asyncio
    async def test_no_duplicate_active_unified_downloads(self, populated_db):
        """No track should have multiple active unified_downloads."""
        db = populated_db
        cur = await db.execute(
            """SELECT monitored_track_id, COUNT(*) as c FROM unified_downloads
               WHERE status IN ('queued','downloading')
               GROUP BY monitored_track_id HAVING c > 1"""
        )
        dupes = await cur.fetchall()
        assert len(dupes) == 0, f"Found {len(dupes)} tracks with duplicate active downloads"

    @pytest.mark.asyncio
    async def test_album_status_consistency(self, populated_db):
        """Album status should match the state of its tracks."""
        db = populated_db
        cur = await db.execute(
            """SELECT ma.id, ma.name, ma.status,
                  SUM(CASE WHEN mt.status='have' THEN 1 ELSE 0 END) as have,
                  COUNT(*) as total
               FROM monitored_albums ma
               JOIN monitored_tracks mt ON mt.album_id = ma.id
               GROUP BY ma.id
               HAVING (ma.status='have' AND have < total)
                   OR (ma.status='wanted' AND have > 0 AND have < total)"""
        )
        inconsistent = await cur.fetchall()
        # The populated_db fixture has album 2 with status='partial' and 1 'have' track, which is correct.
        # We check for truly wrong states.
        for row in inconsistent:
            row_d = dict(row)
            # Album marked 'have' but not all tracks are 'have' → bad
            if row_d["status"] == "have" and row_d["have"] < row_d["total"]:
                pytest.fail(
                    f"Album '{row_d['name']}' (id={row_d['id']}) marked 'have' "
                    f"but only {row_d['have']}/{row_d['total']} tracks are 'have'"
                )

    @pytest.mark.asyncio
    async def test_monitored_tracks_unique_spotify_id(self, populated_db):
        """Each monitored_track should have a unique spotify_id."""
        db = populated_db
        cur = await db.execute(
            """SELECT spotify_id, COUNT(*) as c FROM monitored_tracks
               GROUP BY spotify_id HAVING c > 1"""
        )
        dupes = await cur.fetchall()
        assert len(dupes) == 0, f"Found {len(dupes)} duplicate spotify_ids in monitored_tracks"

    @pytest.mark.asyncio
    async def test_foreign_key_integrity(self, populated_db):
        """All monitored_tracks should reference valid albums and artists."""
        db = populated_db
        cur = await db.execute(
            """SELECT mt.id FROM monitored_tracks mt
               WHERE mt.album_id IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM monitored_albums ma WHERE ma.id = mt.album_id)"""
        )
        orphans = await cur.fetchall()
        assert len(orphans) == 0, f"Found {len(orphans)} tracks referencing non-existent albums"

    @pytest.mark.asyncio
    async def test_unified_downloads_reference_valid_tracks(self, populated_db):
        """All unified_downloads should reference valid monitored_tracks."""
        db = populated_db
        # Add a test unified_download with valid reference
        await db.execute(
            """INSERT INTO unified_downloads
               (spotify_id, item_type, title, artist, status, source, monitored_track_id)
               VALUES ('track_sp_002', 'track', 'Track 2', 'Test Artist', 'queued', 'torrent', 2)"""
        )
        await db.commit()

        cur = await db.execute(
            """SELECT ud.id FROM unified_downloads ud
               WHERE ud.monitored_track_id IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM monitored_tracks mt WHERE mt.id = ud.monitored_track_id)"""
        )
        orphans = await cur.fetchall()
        assert len(orphans) == 0, f"Found {len(orphans)} unified_downloads referencing non-existent tracks"
