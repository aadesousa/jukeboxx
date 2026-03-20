"""
Phase 3.4: Discord notification tests.
"""
import pytest
import pytest_asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


class TestDiscordNotifications:
    @pytest.mark.asyncio
    async def test_notify_skips_when_no_webhook(self):
        from discord import notify_download_complete
        with patch("discord.get_setting", new_callable=AsyncMock, return_value=""):
            # Should not raise when webhook URL is empty
            try:
                await notify_download_complete("Track 1", "Artist", "torrent")
            except Exception as e:
                pytest.fail(f"notify_download_complete raised unexpectedly: {e}")

    @pytest.mark.asyncio
    async def test_notify_download_complete_sends_webhook(self):
        from discord import notify_download_complete

        mock_resp = MagicMock(status_code=204)

        async def mock_settings(key, default=""):
            if key == "discord_webhook_url":
                return "https://discord.com/api/webhooks/123/abc"
            if key == "discord_notify_download_complete":
                return "1"
            return default

        with patch("discord.get_setting", new_callable=AsyncMock, side_effect=mock_settings):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.post = AsyncMock(return_value=mock_resp)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_client

                await notify_download_complete("Track 1", "Test Artist", "soulseek")
                mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_new_releases(self):
        from discord import notify_new_releases

        mock_resp = MagicMock(status_code=204)

        async def mock_settings(key, default=""):
            if key == "discord_webhook_url":
                return "https://discord.com/api/webhooks/123/abc"
            if key == "discord_notify_new_release":
                return "1"
            return default

        with patch("discord.get_setting", new_callable=AsyncMock, side_effect=mock_settings):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.post = AsyncMock(return_value=mock_resp)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_client

                releases = [
                    {"artist": "Test Artist", "album": "New Album", "type": "album"}
                ]
                await notify_new_releases(releases)
                mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_disabled_by_setting(self):
        from discord import notify_download_complete

        async def mock_settings(key, default=""):
            if key == "discord_webhook_url":
                return "https://discord.com/api/webhooks/123/abc"
            if key == "discord_notify_download_complete":
                return "0"  # Disabled
            return default

        with patch("discord.get_setting", new_callable=AsyncMock, side_effect=mock_settings):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.post = AsyncMock()
                mock_cls.return_value = mock_client

                await notify_download_complete("Track 1", "Artist", "torrent")
                # Should NOT have called post since notifications are disabled
                mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_handles_network_error(self):
        from discord import notify_download_complete

        async def mock_settings(key, default=""):
            if key == "discord_webhook_url":
                return "https://discord.com/api/webhooks/123/abc"
            if key == "discord_notify_download_complete":
                return "1"
            return default

        with patch("discord.get_setting", new_callable=AsyncMock, side_effect=mock_settings):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.post = AsyncMock(side_effect=Exception("Network error"))
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_cls.return_value = mock_client

                # Should not raise — Discord errors are non-fatal
                try:
                    await notify_download_complete("Track 1", "Artist", "torrent")
                except Exception as e:
                    pytest.fail(f"notify_download_complete raised on network error: {e}")
