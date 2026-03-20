#!/usr/bin/env python3
"""
Phase 7: Data integrity checks for production Jukeboxx database.
Run this against the live DB to find consistency issues.

Usage:
    python check_data_integrity.py [--db /path/to/jukeboxx.db]
"""
import sys
import argparse
import sqlite3
from datetime import datetime


CHECKS = []


def check(name, description):
    """Decorator to register a check function."""
    def decorator(fn):
        CHECKS.append((name, description, fn))
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Phase 7 SQL checks from the test plan
# ---------------------------------------------------------------------------

@check(
    "orphaned_downloading",
    "Tracks stuck in 'downloading' with no matching active unified_download",
)
def check_orphaned_downloading(con):
    cur = con.execute(
        """SELECT COUNT(*) FROM monitored_tracks mt
           WHERE mt.status = 'downloading'
           AND NOT EXISTS (
               SELECT 1 FROM unified_downloads ud
               WHERE ud.monitored_track_id = mt.id
               AND ud.status IN ('queued','downloading')
           )"""
    )
    count = cur.fetchone()[0]
    if count > 0:
        cur2 = con.execute(
            """SELECT mt.id, mt.name, mt.artist_name, mt.updated_at
               FROM monitored_tracks mt
               WHERE mt.status = 'downloading'
               AND NOT EXISTS (
                   SELECT 1 FROM unified_downloads ud
                   WHERE ud.monitored_track_id = mt.id
                   AND ud.status IN ('queued','downloading')
               )
               LIMIT 10"""
        )
        rows = cur2.fetchall()
        return False, f"Found {count} orphaned tracks", rows
    return True, "OK (0 orphaned)", []


@check(
    "duplicate_active_downloads",
    "Tracks with multiple active unified_downloads (should be at most 1)",
)
def check_duplicate_active_downloads(con):
    cur = con.execute(
        """SELECT monitored_track_id, COUNT(*) as c
           FROM unified_downloads
           WHERE status IN ('queued','downloading')
           GROUP BY monitored_track_id HAVING c > 1"""
    )
    rows = cur.fetchall()
    if rows:
        return False, f"Found {len(rows)} tracks with duplicate active downloads", rows
    return True, "OK (no duplicates)", []


@check(
    "album_status_consistency",
    "Albums whose status doesn't match their track completion",
)
def check_album_status_consistency(con):
    cur = con.execute(
        """SELECT ma.id, ma.name, ma.status,
              SUM(CASE WHEN mt.status='have' THEN 1 ELSE 0 END) as have,
              SUM(CASE WHEN mt.status='ignored' THEN 1 ELSE 0 END) as ignored,
              COUNT(*) as total
           FROM monitored_albums ma
           JOIN monitored_tracks mt ON mt.album_id = ma.id
           GROUP BY ma.id
           HAVING
               (ma.status='have' AND (have + ignored) < total)
               OR (ma.status='wanted' AND have > 0)"""
    )
    rows = cur.fetchall()
    if rows:
        return False, f"Found {len(rows)} albums with inconsistent status", [
            (r[0], r[1], f"status={r[2]}, have={r[3]}, ignored={r[4]}, total={r[5]}")
            for r in rows
        ]
    return True, "OK (no inconsistencies)", []


@check(
    "duplicate_monitored_track_spotify_ids",
    "monitored_tracks rows with duplicate spotify_id",
)
def check_duplicate_track_spotify_ids(con):
    cur = con.execute(
        """SELECT spotify_id, COUNT(*) as c FROM monitored_tracks
           GROUP BY spotify_id HAVING c > 1"""
    )
    rows = cur.fetchall()
    if rows:
        return False, f"Found {len(rows)} duplicate spotify_ids", rows
    return True, "OK (all unique)", []


@check(
    "stale_path_tracks",
    "Tracks with a local_path that might not exist on disk (spot-check sample)",
)
def check_stale_paths(con):
    import os
    cur = con.execute(
        """SELECT COUNT(*) FROM tracks WHERE path IS NOT NULL AND path != ''"""
    )
    total = cur.fetchone()[0]

    # Spot-check up to 20 paths
    cur = con.execute(
        """SELECT path FROM tracks WHERE path IS NOT NULL AND path != ''
           ORDER BY RANDOM() LIMIT 20"""
    )
    sample = cur.fetchall()
    missing = [row[0] for row in sample if not os.path.exists(row[0])]

    if missing:
        return False, f"Sample: {len(missing)}/20 paths don't exist on disk", missing
    return True, f"OK (checked 20/{total} paths, all exist)", []


@check(
    "failed_imports_folder",
    "Files accumulating in failed_imports (non-critical warning)",
)
def check_failed_imports(con):
    import os
    cur = con.execute("SELECT value FROM settings WHERE key='music_path'")
    row = cur.fetchone()
    if not row:
        return True, "No music_path configured — skipping", []
    failed_dir = os.path.join(row[0], "failed_imports")
    if not os.path.isdir(failed_dir):
        return True, "OK (no failed_imports dir)", []
    count = sum(1 for _ in os.scandir(failed_dir))
    if count > 50:
        return False, f"WARNING: {count} items in failed_imports — consider clearing", []
    return True, f"OK ({count} items in failed_imports)", []


@check(
    "unified_downloads_broken_refs",
    "unified_downloads referencing non-existent monitored_tracks",
)
def check_unified_downloads_refs(con):
    cur = con.execute(
        """SELECT COUNT(*) FROM unified_downloads ud
           WHERE ud.monitored_track_id IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM monitored_tracks mt WHERE mt.id = ud.monitored_track_id
           )"""
    )
    count = cur.fetchone()[0]
    if count > 0:
        return False, f"Found {count} unified_downloads with broken track refs", []
    return True, "OK (all refs valid)", []


@check(
    "downloading_tracks_age",
    "monitored_tracks stuck in 'downloading' for more than 4 hours",
)
def check_old_downloading_tracks(con):
    cur = con.execute(
        """SELECT id, name, artist_name, updated_at
           FROM monitored_tracks
           WHERE status='downloading'
           AND datetime(updated_at) < datetime('now', '-4 hours')
           LIMIT 20"""
    )
    rows = cur.fetchall()
    if rows:
        return False, f"Found {len(rows)} tracks stuck in 'downloading' >4h", [
            (r[0], r[1], r[2], r[3]) for r in rows
        ]
    return True, "OK (no stale downloading tracks)", []


@check(
    "wanted_counts_summary",
    "Summary of wanted / downloading / failed track counts",
)
def check_wanted_summary(con):
    cur = con.execute(
        """SELECT status, COUNT(*) as c FROM monitored_tracks
           WHERE monitored=1 GROUP BY status"""
    )
    rows = cur.fetchall()
    summary = {r[0]: r[1] for r in rows}
    details = [f"{status}: {count}" for status, count in sorted(summary.items())]
    return True, "Counts: " + ", ".join(details), []


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_checks(db_path: str) -> int:
    """Run all checks. Returns exit code (0=all pass, 1=failures found)."""
    print(f"Jukeboxx Data Integrity Check")
    print(f"DB: {db_path}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    try:
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
    except Exception as e:
        print(f"ERROR: Cannot open database: {e}")
        return 1

    failures = 0
    warnings = 0

    for name, description, fn in CHECKS:
        try:
            ok, msg, details = fn(con)
            status = "✓ PASS" if ok else "✗ FAIL"
            print(f"\n[{status}] {name}")
            print(f"       {description}")
            print(f"       → {msg}")
            if details and not ok:
                for d in details[:5]:
                    print(f"         · {d}")
                if len(details) > 5:
                    print(f"         · ... ({len(details) - 5} more)")
            if not ok:
                failures += 1
        except Exception as e:
            print(f"\n[! ERR] {name}: {e}")
            warnings += 1

    con.close()
    print("\n" + "=" * 60)
    total = len(CHECKS)
    passed = total - failures - warnings
    print(f"Results: {passed}/{total} passed, {failures} failed, {warnings} errors")

    if failures > 0:
        print("\nACTION REQUIRED: Data integrity issues found.")
        print("Fix orphaned downloads: run poll_unified_downloads() via backend")
        print("Fix album statuses: re-trigger album completion rollup")
        return 1
    else:
        print("\nAll checks passed.")
        return 0


def main():
    parser = argparse.ArgumentParser(description="Jukeboxx data integrity checker")
    parser.add_argument(
        "--db",
        default="/home/eve/jukeboxx/backend/jukeboxx.db",
        help="Path to jukeboxx.db",
    )
    args = parser.parse_args()
    sys.exit(run_checks(args.db))


if __name__ == "__main__":
    main()
