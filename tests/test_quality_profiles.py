"""
Phase 2.11: Quality and metadata profile tests.
Covers CRUD for quality_profiles, metadata_profiles, release_profiles.
"""
import pytest
import pytest_asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


class TestQualityProfiles:
    @pytest.mark.asyncio
    async def test_list_profiles_has_defaults(self, client, auth_headers):
        await client.post("/auth/setup", json={"username": "testuser", "password": "testpass"})
        resp = await client.get("/quality-profiles", headers=auth_headers)
        assert resp.status_code == 200
        profiles = resp.json()
        assert isinstance(profiles, list)
        names = [p["name"] for p in profiles]
        assert "Any" in names

    @pytest.mark.asyncio
    async def test_create_profile(self, client, auth_headers):
        await client.post("/auth/setup", json={"username": "testuser", "password": "testpass"})
        resp = await client.post(
            "/quality-profiles",
            headers=auth_headers,
            json={"name": "My Profile", "preferred_format": "flac", "min_bitrate": 0},
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["name"] == "My Profile"

    @pytest.mark.asyncio
    async def test_get_profile(self, client, auth_headers):
        await client.post("/auth/setup", json={"username": "testuser", "password": "testpass"})
        # Get the default profile (id=1)
        resp = await client.get("/quality-profiles/1", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "name" in data

    @pytest.mark.asyncio
    async def test_delete_nondefault_profile(self, client, auth_headers):
        await client.post("/auth/setup", json={"username": "testuser", "password": "testpass"})
        # Create a profile first
        create_resp = await client.post(
            "/quality-profiles",
            headers=auth_headers,
            json={"name": "Temp Profile", "preferred_format": "any"},
        )
        assert create_resp.status_code in (200, 201)
        new_id = create_resp.json()["id"]

        # Delete it
        del_resp = await client.delete(f"/quality-profiles/{new_id}", headers=auth_headers)
        assert del_resp.status_code in (200, 204)

    @pytest.mark.asyncio
    async def test_update_profile(self, client, auth_headers):
        await client.post("/auth/setup", json={"username": "testuser", "password": "testpass"})
        create_resp = await client.post(
            "/quality-profiles",
            headers=auth_headers,
            json={"name": "Edit Me", "preferred_format": "any"},
        )
        new_id = create_resp.json()["id"]

        update_resp = await client.put(
            f"/quality-profiles/{new_id}",
            headers=auth_headers,
            json={"name": "Edited", "preferred_format": "flac", "min_bitrate": 0},
        )
        assert update_resp.status_code == 200
        # Verify by fetching the profile — update returns {"ok": True}
        get_resp = await client.get(f"/quality-profiles/{new_id}", headers=auth_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "Edited"


class TestQualityModule:
    @pytest.mark.asyncio
    async def test_list_returns_list(self, db):
        import quality
        profiles = await quality.list_profiles()
        assert isinstance(profiles, list)
        assert len(profiles) >= 1  # At least "Any" default

    @pytest.mark.asyncio
    async def test_create_and_get(self, db):
        import quality
        data = {"name": "Test Quality", "preferred_format": "mp3_320", "min_bitrate": 320}
        created = await quality.create_profile(data)
        assert created["name"] == "Test Quality"
        profile_id = created["id"]

        # create_profile returns {"id": ..., "name": ...}; get_profile returns full dict
        fetched = await quality.get_profile(profile_id)
        assert fetched is not None
        assert fetched["name"] == "Test Quality"
        assert fetched["preferred_format"] == "mp3_320"

    @pytest.mark.asyncio
    async def test_delete_profile(self, db):
        import quality
        data = {"name": "Delete Me", "preferred_format": "any"}
        created = await quality.create_profile(data)
        pid = created["id"]
        result = await quality.delete_profile(pid)
        assert result is not None  # returns {"ok": True}
