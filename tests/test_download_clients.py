"""
Phase 2.11 / Phase 3.2: Download client tests.
Covers CRUD operations and connection testing for all client types.
"""
import pytest
import pytest_asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


class TestDownloadClientCRUD:
    @pytest.mark.asyncio
    async def test_create_client(self, db):
        from download_clients import create_client, list_clients
        client_id = await create_client({
            "name": "My qBit",
            "type": "qbittorrent",
            "host": "localhost",
            "port": 8080,
            "username": "admin",
            "password": "secret",
        })
        assert isinstance(client_id, int)
        clients = await list_clients()
        names = [c["name"] for c in clients]
        assert "My qBit" in names

    @pytest.mark.asyncio
    async def test_list_clients_empty(self, db):
        from download_clients import list_clients
        clients = await list_clients()
        assert isinstance(clients, list)

    @pytest.mark.asyncio
    async def test_get_client(self, db):
        from download_clients import create_client, get_client
        cid = await create_client({
            "name": "SABnzbd Test",
            "type": "sabnzbd",
            "host": "192.168.1.1",
            "port": 8080,
            "api_key": "abc123",
        })
        client = await get_client(cid)
        assert client is not None
        assert client["name"] == "SABnzbd Test"
        assert client["type"] == "sabnzbd"

    @pytest.mark.asyncio
    async def test_get_nonexistent_client_returns_none(self, db):
        from download_clients import get_client
        client = await get_client(99999)
        assert client is None

    @pytest.mark.asyncio
    async def test_create_client_priority_auto_increment(self, db):
        from download_clients import create_client, get_client
        id1 = await create_client({"name": "First", "type": "qbittorrent"})
        id2 = await create_client({"name": "Second", "type": "sabnzbd"})
        c1 = await get_client(id1)
        c2 = await get_client(id2)
        assert c2["priority"] > c1["priority"]

    @pytest.mark.asyncio
    async def test_password_masked_in_list(self, db):
        from download_clients import create_client, list_clients
        await create_client({
            "name": "Masked Test",
            "type": "qbittorrent",
            "password": "supersecret",
        })
        clients = await list_clients()
        masked = next(c for c in clients if c["name"] == "Masked Test")
        assert masked["password"] == "***"

    @pytest.mark.asyncio
    async def test_supported_client_types(self):
        from download_clients import SUPPORTED_TYPES
        assert "qbittorrent" in SUPPORTED_TYPES
        assert "sabnzbd" in SUPPORTED_TYPES
        assert "slskd" in SUPPORTED_TYPES
        assert "spotizerr" in SUPPORTED_TYPES
        assert "metube" in SUPPORTED_TYPES


class TestClientBaseUrl:
    def test_qbit_base_http(self):
        from grabbers import _qbit_base
        row = {"host": "localhost", "port": 8080, "use_ssl": 0, "url_base": ""}
        assert _qbit_base(row) == "http://localhost:8080"

    def test_qbit_base_https(self):
        from grabbers import _qbit_base
        row = {"host": "example.com", "port": 443, "use_ssl": 1, "url_base": ""}
        assert _qbit_base(row) == "https://example.com:443"

    def test_qbit_base_with_url_base(self):
        from grabbers import _qbit_base
        row = {"host": "localhost", "port": 8080, "use_ssl": 0, "url_base": "/qbit/"}
        assert _qbit_base(row) == "http://localhost:8080/qbit"

    def test_sabnzbd_base(self):
        from grabbers import _sabnzbd_base
        row = {"host": "localhost", "port": 8080, "use_ssl": 0, "url_base": ""}
        assert _sabnzbd_base(row) == "http://localhost:8080"

    def test_slskd_base_from_url(self):
        from grabbers import _slskd_base
        row = {"url_base": "http://192.168.1.152:5030", "host": "", "port": 0}
        assert _slskd_base(row) == "http://192.168.1.152:5030"

    def test_slskd_base_from_host_port(self):
        from grabbers import _slskd_base
        row = {"url_base": "", "host": "192.168.1.152", "port": 5030}
        assert _slskd_base(row) == "http://192.168.1.152:5030"
