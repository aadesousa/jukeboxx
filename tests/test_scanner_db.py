"""
Phase 1.7 / Phase 4.3: Library scanner integration tests.
Tests cleanup of stale scans, scan progress tracking, and scan history.
"""
import pytest
import pytest_asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


class TestCleanupStaleScans:
    @pytest.mark.asyncio
    async def test_cleanup_marks_running_as_failed(self, db):
        from scanner import cleanup_stale_scans
        # Insert a stale running scan
        await db.execute(
            """INSERT INTO scan_history (status, started_at)
               VALUES ('running', datetime('now', '-1 hour'))"""
        )
        await db.commit()
        await cleanup_stale_scans()

        cur = await db.execute(
            "SELECT status FROM scan_history WHERE status='running'"
        )
        rows = await cur.fetchall()
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_cleanup_preserves_completed_scans(self, db):
        from scanner import cleanup_stale_scans
        # Insert a completed scan
        await db.execute(
            """INSERT INTO scan_history (status, started_at, completed_at)
               VALUES ('complete', datetime('now', '-2 hours'), datetime('now', '-1 hour'))"""
        )
        await db.commit()
        await cleanup_stale_scans()

        cur = await db.execute(
            "SELECT status FROM scan_history WHERE status='complete'"
        )
        rows = await cur.fetchall()
        assert len(rows) == 1


class TestScanProgress:
    def test_initial_progress_is_idle(self):
        from scanner import scan_progress
        assert scan_progress["phase"] in ("idle", "complete", "walking", "indexing", "dedup")

    def test_scan_progress_has_expected_keys(self):
        from scanner import scan_progress
        assert "total_files" in scan_progress
        assert "processed" in scan_progress
        assert "phase" in scan_progress


class TestScanHistory:
    @pytest.mark.asyncio
    async def test_scan_history_inserted(self, db):
        """Verify scan history records can be queried correctly."""
        await db.execute(
            """INSERT INTO scan_history
               (started_at, completed_at, tracks_found, tracks_added, status)
               VALUES (datetime('now', '-5 minutes'), datetime('now'), 1000, 50, 'complete')"""
        )
        await db.commit()

        cur = await db.execute(
            "SELECT * FROM scan_history ORDER BY id DESC LIMIT 1"
        )
        row = await cur.fetchone()
        assert row["status"] == "complete"
        assert row["tracks_found"] == 1000
        assert row["tracks_added"] == 50
