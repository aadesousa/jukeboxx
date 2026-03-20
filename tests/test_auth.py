"""
Phase 2.11 / Phase 5.4: Authentication tests.
Covers setup, login, logout, JWT validation, API key auth, and edge cases.
"""
import pytest
import pytest_asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


class TestAuthSetup:
    @pytest.mark.asyncio
    async def test_auth_status_no_user(self, client):
        resp = await client.get("/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["setup_complete"] is False
        assert data["authenticated"] is False

    @pytest.mark.asyncio
    async def test_setup_creates_account(self, client):
        resp = await client.post("/auth/setup", json={"username": "admin", "password": "secret123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["username"] == "admin"
        # Should set cookie
        assert "jukeboxx_token" in resp.headers.get("set-cookie", "")

    @pytest.mark.asyncio
    async def test_setup_rejects_duplicate(self, client):
        # First setup
        await client.post("/auth/setup", json={"username": "admin", "password": "secret123"})
        # Second setup should fail
        resp = await client.post("/auth/setup", json={"username": "admin2", "password": "secret456"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_setup_validates_password_length(self, client):
        resp = await client.post("/auth/setup", json={"username": "admin", "password": "abc"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_setup_requires_username(self, client):
        resp = await client.post("/auth/setup", json={"username": "  ", "password": "secret123"})
        assert resp.status_code == 400


class TestAuthLogin:
    @pytest.mark.asyncio
    async def test_login_success(self, client):
        await client.post("/auth/setup", json={"username": "admin", "password": "secret123"})
        resp = await client.post("/auth/login", json={"username": "admin", "password": "secret123"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client):
        await client.post("/auth/setup", json={"username": "admin", "password": "secret123"})
        resp = await client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_wrong_username(self, client):
        await client.post("/auth/setup", json={"username": "admin", "password": "secret123"})
        resp = await client.post("/auth/login", json={"username": "wrong", "password": "secret123"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_no_account(self, client):
        resp = await client.post("/auth/login", json={"username": "admin", "password": "secret"})
        assert resp.status_code == 400


class TestAuthLogout:
    @pytest.mark.asyncio
    async def test_logout_clears_cookie(self, client):
        resp = await client.post("/auth/logout")
        assert resp.status_code == 200
        cookie_header = resp.headers.get("set-cookie", "")
        assert "jukeboxx_token" in cookie_header


class TestJWTMiddleware:
    @pytest.mark.asyncio
    async def test_public_paths_no_auth(self, client):
        """Public paths should not require auth."""
        resp = await client.get("/health")
        assert resp.status_code == 200

        resp = await client.get("/auth/status")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_protected_path_no_token(self, client):
        """Protected paths should return 401 without token."""
        resp = await client.get("/stats")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_protected_path_valid_token(self, client, auth_headers):
        """Protected paths should work with valid JWT."""
        await client.post("/auth/setup", json={"username": "testuser", "password": "testpass"})
        resp = await client.get("/stats", headers=auth_headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_expired_token_rejected(self, client):
        """Expired JWT should return 401."""
        import jwt
        from datetime import datetime, timezone, timedelta
        token = jwt.encode(
            {"sub": "testuser", "exp": datetime.now(timezone.utc) - timedelta(hours=1)},
            "test-secret-key-for-tests",
            algorithm="HS256",
        )
        resp = await client.get("/stats", headers={"Cookie": f"jukeboxx_token={token}"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_token_rejected(self, client):
        """Malformed JWT should return 401."""
        resp = await client.get("/stats", headers={"Cookie": "jukeboxx_token=not.a.valid.token"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_api_key_auth(self, client):
        """X-Api-Key header should authenticate when matching stored key."""
        from database import set_setting
        await set_setting("jukeboxx_api_key", "test-api-key-123")
        resp = await client.get("/stats", headers={"X-Api-Key": "test-api-key-123"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_api_key_wrong_key(self, client):
        """Wrong API key should fall through to JWT check (and fail if no JWT)."""
        from database import set_setting
        await set_setting("jukeboxx_api_key", "correct-key")
        resp = await client.get("/stats", headers={"X-Api-Key": "wrong-key"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_api_key_query_param(self, client):
        """?apikey= query param should authenticate."""
        from database import set_setting
        await set_setting("jukeboxx_api_key", "qp-key-456")
        resp = await client.get("/stats?apikey=qp-key-456")
        assert resp.status_code == 200
