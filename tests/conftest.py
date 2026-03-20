"""
Shared fixtures for Jukeboxx test suite.
Uses per-test temp file DBs (not :memory:) because aiosqlite opens a new
connection per get_db() call — each :memory: connection is isolated.
"""
import os
import sys
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Ensure backend is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

# Override env vars before any backend imports
os.environ["MUSIC_PATH"] = "/tmp/jukeboxx_test_music"
os.environ["JWT_SECRET"] = "test-secret-key-for-tests"
os.environ["SPOTIZERR_URL"] = "http://localhost:19999"


# ---------------------------------------------------------------------------
# Event loop (session-scoped so all async fixtures/tests share one loop)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# DB path management
# ---------------------------------------------------------------------------

def _make_temp_db_path():
    """Return a fresh temp file path for a test DB."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="jukeboxx_test_")
    os.close(fd)
    os.unlink(path)  # Let aiosqlite create it fresh
    return path


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def db():
    """Fresh initialized DB for each test (file-based to allow multiple connections)."""
    import database

    db_path = _make_temp_db_path()
    original_path = database.DB_PATH
    database.DB_PATH = db_path
    os.environ["DB_PATH"] = db_path

    try:
        await database.init_db()
        conn = await database.get_db()
        try:
            yield conn
        finally:
            await conn.close()
    finally:
        database.DB_PATH = original_path
        os.environ.pop("DB_PATH", None)
        try:
            os.unlink(db_path)
        except OSError:
            pass


@pytest_asyncio.fixture
async def populated_db(db):
    """DB with sample artists, albums, tracks, and settings."""
    import bcrypt

    # Auth user
    pw_hash = bcrypt.hashpw(b"testpass", bcrypt.gensalt()).decode()
    await db.execute(
        "INSERT OR REPLACE INTO auth (id, username, password_hash) VALUES (1, 'testuser', ?)",
        (pw_hash,),
    )

    # Quality profile
    await db.execute(
        "INSERT OR IGNORE INTO quality_profiles (id, name, preferred_format, min_bitrate, is_default) "
        "VALUES (1, 'Any', 'any', 0, 1)"
    )

    # Monitored artist
    await db.execute(
        "INSERT OR IGNORE INTO monitored_artists "
        "(id, spotify_id, name, image_url, genres, monitored, monitor_new_releases) "
        "VALUES (1, 'artist_sp_001', 'Test Artist', '', '[]', 1, 1)"
    )

    # Album 1 — all wanted (5 tracks)
    await db.execute(
        "INSERT OR IGNORE INTO monitored_albums "
        "(id, spotify_id, artist_id, artist_spotify_id, name, album_type, track_count, status, monitored) "
        "VALUES (1, 'album_sp_001', 1, 'artist_sp_001', 'Test Album', 'album', 5, 'wanted', 1)"
    )
    for i in range(1, 6):
        await db.execute(
            "INSERT OR IGNORE INTO monitored_tracks "
            "(id, spotify_id, album_id, artist_id, album_spotify_id, artist_spotify_id, "
            "name, artist_name, album_name, track_number, duration_ms, status, monitored) "
            "VALUES (?, ?, 1, 1, 'album_sp_001', 'artist_sp_001', ?, 'Test Artist', 'Test Album', ?, ?, 'wanted', 1)",
            (i, f"track_sp_{i:03d}", f"Track {i}", i, 200000 + i * 10000),
        )

    # Album 2 — partial (3 tracks: 1 have, 2 wanted)
    await db.execute(
        "INSERT OR IGNORE INTO monitored_albums "
        "(id, spotify_id, artist_id, artist_spotify_id, name, album_type, track_count, status, monitored) "
        "VALUES (2, 'album_sp_002', 1, 'artist_sp_001', 'Second Album', 'album', 3, 'partial', 1)"
    )
    for i, status in [(6, "have"), (7, "wanted"), (8, "wanted")]:
        await db.execute(
            "INSERT OR IGNORE INTO monitored_tracks "
            "(id, spotify_id, album_id, artist_id, album_spotify_id, artist_spotify_id, "
            "name, artist_name, album_name, track_number, duration_ms, status, monitored) "
            "VALUES (?, ?, 2, 1, 'album_sp_002', 'artist_sp_001', ?, 'Test Artist', 'Second Album', ?, ?, ?, 1)",
            (i, f"track_sp_{i:03d}", f"Track {i}", i - 5, 180000 + i * 5000, status),
        )

    # One local track matched to track_sp_001
    await db.execute(
        "INSERT OR IGNORE INTO tracks "
        "(id, path, title, artist, album_artist, album, format, bitrate, duration, size, spotify_id) "
        "VALUES (1, '/music/Test Artist/Test Album/01 Track 1.flac', "
        "'Track 1', 'Test Artist', 'Test Artist', 'Test Album', 'FLAC', 1411, 200, 30000000, 'track_sp_001')"
    )

    # Settings
    await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('library_ready', '1')")
    await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('slsk_album_download', '1')")
    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('download_source_priority', ?)",
        ('["torrent","usenet","soulseek","youtube"]',),
    )

    await db.commit()
    return db


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------
@pytest.fixture
def db_path_for_app():
    """Create a temp DB file for the FastAPI app."""
    path = _make_temp_db_path()
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def test_app(db_path_for_app):
    """FastAPI app with scheduler mocked and DB pointing to a temp file."""
    import database
    original_path = database.DB_PATH
    database.DB_PATH = db_path_for_app
    os.environ["DB_PATH"] = db_path_for_app

    with patch("scheduler.start_scheduler", new_callable=AsyncMock), \
         patch("scheduler.stop_scheduler", new_callable=AsyncMock), \
         patch("scanner.cleanup_stale_scans", new_callable=AsyncMock):
        from main import app
        yield app

    database.DB_PATH = original_path
    os.environ.pop("DB_PATH", None)


@pytest_asyncio.fixture
async def client(test_app, db_path_for_app):
    """Async HTTP test client (no auth by default).

    ASGITransport does not trigger ASGI lifespan, so we call init_db()
    explicitly before yielding the client.
    """
    import database
    # db_path_for_app is already set on database.DB_PATH by test_app fixture
    await database.init_db()

    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
def auth_headers():
    """Valid JWT cookie for authenticated requests."""
    import jwt
    from datetime import datetime, timezone, timedelta
    token = jwt.encode(
        {"sub": "testuser", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "test-secret-key-for-tests",
        algorithm="HS256",
    )
    return {"Cookie": f"jukeboxx_token={token}"}


# ---------------------------------------------------------------------------
# Music directory fixture
# ---------------------------------------------------------------------------
@pytest.fixture
def music_dir(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    (music / "Playlists").mkdir()
    (music / "failed_imports").mkdir()
    album_dir = music / "Test Artist" / "Test Album"
    album_dir.mkdir(parents=True)
    for i in range(1, 4):
        (album_dir / f"{i:02d} Track {i}.mp3").write_bytes(b"\x00" * 100)
    return music


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_mock_httpx_response(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


def make_track_dict(track_id=1, name="Test Track", artist="Test Artist",
                    album="Test Album", spotify_id="sp_123", status="wanted",
                    album_id=1, duration_ms=200000):
    return {
        "id": track_id,
        "spotify_id": spotify_id,
        "name": name,
        "artist_name": artist,
        "album_name": album,
        "album_id": album_id,
        "artist_id": 1,
        "track_number": 1,
        "duration_ms": duration_ms,
        "status": status,
        "monitored": 1,
        "image_url": "",
    }
