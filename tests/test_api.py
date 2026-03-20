"""
Phase 2: API endpoint tests.
Covers health, stats, source labels, and core API routes.
"""
import pytest
import pytest_asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "jukeboxx"


class TestStatsEndpoint:
    @pytest.mark.asyncio
    async def test_stats_returns_structure(self, client, auth_headers):
        await client.post("/auth/setup", json={"username": "testuser", "password": "testpass"})
        resp = await client.get("/stats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_tracks" in data
        assert "total_artists" in data
        assert "total_albums" in data
        assert "total_missing" in data
        assert "total_size_gb" in data
        assert "format_breakdown" in data
        assert "spotify_connected" in data
        assert "spotizerr_reachable" in data

    @pytest.mark.asyncio
    async def test_stats_counts_are_integers(self, client, auth_headers):
        await client.post("/auth/setup", json={"username": "testuser", "password": "testpass"})
        resp = await client.get("/stats", headers=auth_headers)
        data = resp.json()
        assert isinstance(data["total_tracks"], int)
        assert isinstance(data["total_artists"], int)
        assert isinstance(data["total_albums"], int)
        assert isinstance(data["total_missing"], int)
        assert isinstance(data["total_size_gb"], (int, float))


class TestSourceLabels:
    def test_friendly_source_mapping(self):
        from main import _friendly_source
        assert _friendly_source("torrent") == "qBittorrent"
        assert _friendly_source("usenet") == "SABnzbd"
        assert _friendly_source("soulseek") == "Soulseek"
        assert _friendly_source("youtube") == "YouTube"
        assert _friendly_source("metube") == "YouTube"
        assert _friendly_source("spotizerr") == "Spotizerr"
        assert _friendly_source("auto") == "Spotizerr"
        assert _friendly_source("auto_sync") == "Spotizerr"
        assert _friendly_source("manual") == "Spotizerr"

    def test_friendly_source_unknown(self):
        from main import _friendly_source
        assert _friendly_source("unknown_source") == "Unknown Source"
        assert _friendly_source(None) == "Unknown"

    def test_friendly_error_mapping(self):
        from main import _friendly_error
        assert _friendly_error("cannot get alternate track") == "No sources found"
        assert "will retry" in _friendly_error("Recovered: dispatch not confirmed by Spotizerr")
        assert "Timed out" in _friendly_error("Timed out: not found locally after 24h")

    def test_friendly_error_passthrough(self):
        from main import _friendly_error
        assert _friendly_error("Some random error") == "Some random error"
        assert _friendly_error(None) is None


class TestSSEEndpoint:
    @pytest.mark.asyncio
    async def test_sse_test_endpoint(self, client):
        """SSE test endpoint should be publicly accessible."""
        resp = await client.get("/sse-test")
        assert resp.status_code == 200
        # StreamingResponse returns text/event-stream
        assert "text/event-stream" in resp.headers.get("content-type", "")


class TestImageBackfill:
    @pytest.mark.asyncio
    async def test_backfill_artists_endpoint(self, client, auth_headers):
        await client.post("/auth/setup", json={"username": "testuser", "password": "testpass"})
        with patch("images.backfill_artist_images", new_callable=AsyncMock, return_value=5):
            resp = await client.post("/images/backfill-artists", headers=auth_headers)
            assert resp.status_code == 200
            assert resp.json()["updated"] == 5

    @pytest.mark.asyncio
    async def test_backfill_albums_endpoint(self, client, auth_headers):
        await client.post("/auth/setup", json={"username": "testuser", "password": "testpass"})
        with patch("images.backfill_album_covers", new_callable=AsyncMock, return_value=3):
            resp = await client.post("/images/backfill-albums", headers=auth_headers)
            assert resp.status_code == 200
            assert resp.json()["updated"] == 3
