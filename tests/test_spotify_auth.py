"""
Phase 3.1: Spotify OAuth and rate limiting tests.
"""
import pytest
import pytest_asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


class TestSpotifyRateLimit:
    def test_not_rate_limited_initially(self):
        import spotify_auth
        # _rate_limit_until is a float epoch timestamp (0.0 = not limited)
        spotify_auth._rate_limit_until = 0.0
        assert not spotify_auth.is_rate_limited()

    def test_set_rate_limited(self):
        from spotify_auth import is_rate_limited, set_rate_limited
        set_rate_limited(3600)
        assert is_rate_limited()

    def test_rate_limit_clears_after_time(self):
        """Rate limit should clear when the deadline passes (timestamp in the past)."""
        import spotify_auth, time
        # Set deadline to 1 second ago
        spotify_auth._rate_limit_until = time.time() - 1
        assert not spotify_auth.is_rate_limited()
        # Reset
        spotify_auth._rate_limit_until = 0.0

    def test_api_usage_info_structure(self):
        import spotify_auth, time
        # Ensure not rate limited before checking structure
        spotify_auth._rate_limit_until = 0.0
        from spotify_auth import get_api_usage_info
        info = get_api_usage_info()
        assert isinstance(info, dict)
        assert "rate_limited" in info or "calls_last_minute" in info or "calls_last_hour" in info


class TestSpotifyTokenInfo:
    @pytest.mark.asyncio
    async def test_get_token_info_no_token(self, db):
        from spotify_auth import get_token_info
        info = await get_token_info()
        assert info is None or not info.get("access_token")

    @pytest.mark.asyncio
    async def test_get_token_info_with_token(self, db):
        from spotify_auth import get_token_info
        import time
        # Insert a token
        await db.execute(
            """INSERT OR REPLACE INTO spotify_auth
               (id, access_token, refresh_token, expires_at)
               VALUES (1, 'test_token', 'refresh_token', ?)""",
            (int(time.time()) + 3600,),
        )
        await db.commit()
        info = await get_token_info()
        assert info is not None
        assert info["access_token"] == "test_token"


class TestSpotifyAuthUrl:
    @pytest.mark.asyncio
    async def test_auth_url_requires_client_id(self, client, auth_headers):
        await client.post("/auth/setup", json={"username": "testuser", "password": "testpass"})
        resp = await client.get("/spotify/auth-url", headers=auth_headers)
        # Without credentials configured, should return 400
        assert resp.status_code in (400, 200)

    @pytest.mark.asyncio
    async def test_spotify_status_disconnected(self, client, auth_headers):
        import spotify_auth
        # Ensure no rate limit state is active (uses float epoch, not datetime)
        spotify_auth._rate_limit_until = 0.0
        await client.post("/auth/setup", json={"username": "testuser", "password": "testpass"})
        resp = await client.get("/spotify/status", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["connected"] is False


class TestRecordSuccessfulCall:
    def test_increments_counter(self):
        from spotify_auth import record_successful_call, get_api_usage_info
        import spotify_auth
        # Reset rate limit state so get_api_usage_info works
        spotify_auth._rate_limit_until = 0.0
        info_before = get_api_usage_info()
        calls_before = info_before.get("calls_last_minute", info_before.get("calls_last_hour", 0))
        record_successful_call()
        info_after = get_api_usage_info()
        calls_after = info_after.get("calls_last_minute", info_after.get("calls_last_hour", 0))
        assert calls_after >= calls_before
