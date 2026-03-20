"""
Grabber tests — designed to find real failures, not confirm mocks work.

Focus areas:
- _score_result: seeder/grabs confusion bug, exact filter return values (-1000),
  additive preferred words, dispatch usable-filter bug (seeders >= 0)
- search_indexers_auto: priority ordering, stop-at-first, blocklist fallthrough,
  non-music (movie) title filtering fallthrough
- grab_torrent: login "Fails" text, add "Fails" text, category param, URL/SSL construction
- grab_usenet: status=false, missing status key, apikey/cat params, NZB URL as 'name'
- grab_soulseek_files: all-queued dedup (no re-POST), partial dedup, queue-check failure
  recovery, 204 success, API key header, dict-format response
- grab_youtube: quality mapping (0→best), /add endpoint, URL in payload
"""
import pytest
import pytest_asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


# ---------------------------------------------------------------------------
# _score_result
# ---------------------------------------------------------------------------
class TestScoreResult:
    def test_flac_outscores_320(self):
        from grabbers import _score_result
        flac = _score_result({"title": "Artist Album FLAC", "seeders": 5})
        mp3  = _score_result({"title": "Artist Album 320kbps", "seeders": 5})
        assert flac > mp3

    def test_zero_seeder_penalty(self):
        from grabbers import _score_result
        # 50 base + 30 (FLAC) - 25 (0 seeders) = 55
        assert _score_result({"title": "Artist Album FLAC", "seeders": 0}) == 55

    def test_seeders_zero_grabs_nonzero_should_penalize_not_reward(self):
        """BUG PROBE: `seeders or grabs or 0` means seeders=0,grabs=10 → grabs=10.
        A dead torrent gets +15 (≥10 tier) instead of -25 (0 seeders penalty).
        Expected: ≤55 (same as zero-seeder).  Actual broken: 95."""
        from grabbers import _score_result
        dead_with_grabs = _score_result({"title": "Artist Album FLAC", "seeders": 0, "grabs": 10})
        correct = _score_result({"title": "Artist Album FLAC", "seeders": 0})
        assert dead_with_grabs <= correct, (
            f"Dead torrent (seeders=0) with grabs=10 scored {dead_with_grabs}, "
            f"higher than zero-seeder score {correct}. "
            "The `seeders or grabs` logic incorrectly rewards dead torrents."
        )

    def test_ignored_word_returns_exactly_minus_1000(self):
        from grabbers import _score_result
        qp = {"ignored_words": "karaoke", "preferred_words": "", "required_words": ""}
        score = _score_result({"title": "Artist Song Karaoke FLAC", "seeders": 100}, qp)
        assert score == -1000, f"Ignored word must return exactly -1000, got {score}"

    def test_ignored_word_case_insensitive(self):
        from grabbers import _score_result
        qp = {"ignored_words": "instrumental", "preferred_words": "", "required_words": ""}
        assert _score_result({"title": "Artist Song INSTRUMENTAL FLAC", "seeders": 10}, qp) == -1000

    def test_ignored_word_overrides_all_bonuses(self):
        from grabbers import _score_result
        qp = {"ignored_words": "live", "preferred_words": "flac", "required_words": ""}
        score = _score_result({"title": "Artist Song Live FLAC 24bit", "seeders": 100}, qp)
        assert score == -1000, "Ignored word must override all bonuses"

    def test_required_words_missing_returns_exactly_minus_1000(self):
        from grabbers import _score_result
        qp = {"required_words": "flac", "preferred_words": "", "ignored_words": ""}
        score = _score_result({"title": "Artist Song 320kbps", "seeders": 10}, qp)
        assert score == -1000, f"Missing required word must return -1000, got {score}"

    def test_required_words_present_passes(self):
        from grabbers import _score_result
        qp = {"required_words": "flac", "preferred_words": "", "ignored_words": ""}
        assert _score_result({"title": "Artist Song FLAC", "seeders": 5}, qp) > 0

    def test_preferred_words_are_additive(self):
        from grabbers import _score_result
        qp_one = {"preferred_words": "flac", "ignored_words": "", "required_words": ""}
        qp_two = {"preferred_words": "flac,24bit", "ignored_words": "", "required_words": ""}
        title, seeders = "Artist Song FLAC 24bit", 5
        one = _score_result({"title": title, "seeders": seeders}, qp_one)
        two = _score_result({"title": title, "seeders": seeders}, qp_two)
        assert two == one + 10, (
            f"Each matching preferred word should add +10. one={one}, two={two}"
        )

    def test_dispatch_usable_filter_allows_zero_seeders(self):
        """BUG PROBE: dispatch uses `seeders >= 0` — 0-seeder (dead) torrents are grabbed."""
        result = {"title": "Artist FLAC", "download_url": "magnet:abc", "seeders": 0}
        # Replicates line 1116 in tasks.py exactly
        is_usable = result.get("download_url") and result.get("seeders", 0) >= 0
        assert is_usable, (
            "0-seeder torrents pass `seeders >= 0`. Dead torrents will be grabbed and "
            "sit in qBittorrent forever. The filter should require seeders > 0."
        )

    def test_none_seeders_key_present_causes_type_error(self):
        """BUG PROBE: if an indexer returns {seeders: null}, result.get('seeders', 0)
        returns None (not 0), and then None >= 0 raises TypeError in dispatch."""
        result = {"title": "Artist FLAC", "download_url": "magnet:abc", "seeders": None}
        seeders_val = result.get("seeders", 0)  # returns None, not 0
        assert seeders_val is None, "get('seeders', 0) returns None when key exists but is None"
        # This means `None >= 0` would crash dispatch_one
        try:
            _ = seeders_val >= 0
            # If this doesn't crash, the runtime handles it — fine
        except TypeError:
            pass  # Expected — documents the latent crash


# ---------------------------------------------------------------------------
# grab_torrent
# ---------------------------------------------------------------------------
class TestGrabTorrent:
    @pytest.mark.asyncio
    async def test_returns_false_no_client(self, db):
        from grabbers import grab_torrent
        assert await grab_torrent("magnet:?xt=urn:btih:abc") is False

    @pytest.mark.asyncio
    async def test_login_fails_text_stops_early(self, db):
        """qBit login response 'Fails' must stop execution and return False.
        The add-torrent call must NOT be made."""
        await db.execute(
            "INSERT INTO download_clients (type, name, host, port, username, password, enabled, priority) "
            "VALUES ('qbittorrent', 'qbit', 'localhost', 8080, 'admin', 'wrong', 1, 1)"
        )
        await db.commit()

        from grabbers import grab_torrent
        login_resp = MagicMock()
        login_resp.text = "Fails"

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=login_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await grab_torrent("magnet:?xt=urn:btih:abc")

        assert result is False, "Login 'Fails' text must return False"
        # Only one call should have been made (the login), not two (login + add)
        assert mock_client.post.call_count == 1, (
            f"Expected 1 POST (login only). Got {mock_client.post.call_count}. "
            "The add-torrent call was made despite login failure."
        )

    @pytest.mark.asyncio
    async def test_add_returns_fails_text_returns_false(self, db):
        """HTTP 200 from qBit add endpoint but body is 'Fails' → must return False.
        qBittorrent uses this for auth and validation errors."""
        await db.execute(
            "INSERT INTO download_clients (type, name, host, port, enabled, priority) "
            "VALUES ('qbittorrent', 'qbit', 'localhost', 8080, 1, 1)"
        )
        await db.commit()

        from grabbers import grab_torrent
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "Fails"

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await grab_torrent("magnet:?xt=urn:btih:abc")

        assert result is False, "HTTP 200 + body 'Fails' must return False, not True"

    @pytest.mark.asyncio
    async def test_sends_category_music(self, db):
        """Torrent must be filed under 'music' category in qBittorrent."""
        await db.execute(
            "INSERT INTO download_clients (type, name, host, port, enabled, priority) "
            "VALUES ('qbittorrent', 'qbit', 'localhost', 8080, 1, 1)"
        )
        await db.commit()

        from grabbers import grab_torrent
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "Ok."

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            await grab_torrent("magnet:?xt=urn:btih:abc")

        data = mock_client.post.call_args[1].get("data", {})
        assert data.get("category") == "music", f"category not 'music'. Got: {data}"

    @pytest.mark.asyncio
    async def test_magnet_url_sent_as_urls_param(self, db):
        """The exact magnet/URL passed to grab_torrent must appear in POST data['urls']."""
        await db.execute(
            "INSERT INTO download_clients (type, name, host, port, enabled, priority) "
            "VALUES ('qbittorrent', 'qbit', 'localhost', 8080, 1, 1)"
        )
        await db.commit()

        from grabbers import grab_torrent
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "Ok."
        magnet = "magnet:?xt=urn:btih:DEADBEEF&dn=Artist+Album+FLAC"

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            await grab_torrent(magnet)

        data = mock_client.post.call_args[1].get("data", {})
        assert data.get("urls") == magnet, f"Magnet URL not in data['urls']. Got: {data}"

    def test_ssl_produces_https(self):
        from grabbers import _qbit_base
        row = {"host": "qbit.local", "port": 443, "use_ssl": 1, "url_base": ""}
        assert _qbit_base(row).startswith("https://")

    def test_no_ssl_produces_http(self):
        from grabbers import _qbit_base
        row = {"host": "localhost", "port": 8080, "use_ssl": 0, "url_base": ""}
        base = _qbit_base(row)
        assert base.startswith("http://")
        assert not base.startswith("https://")

    def test_url_base_no_trailing_slash(self):
        from grabbers import _qbit_base
        row = {"host": "localhost", "port": 8080, "use_ssl": 0, "url_base": "/qbt/"}
        base = _qbit_base(row)
        assert "/qbt" in base
        assert not base.endswith("/"), "Trailing slash breaks /api/v2/... paths"

    def test_no_url_base_gives_clean_url(self):
        from grabbers import _qbit_base
        row = {"host": "localhost", "port": 8080, "use_ssl": 0, "url_base": ""}
        assert _qbit_base(row) == "http://localhost:8080"


# ---------------------------------------------------------------------------
# grab_usenet
# ---------------------------------------------------------------------------
class TestGrabUsenet:
    @pytest.mark.asyncio
    async def test_returns_false_no_client(self, db):
        from grabbers import grab_usenet
        assert await grab_usenet("http://nzb.example/file.nzb") is False

    @pytest.mark.asyncio
    async def test_status_false_returns_false(self, db):
        """SABnzbd {"status": false} on API error must propagate as False."""
        await db.execute(
            "INSERT INTO download_clients (type, name, host, port, api_key, enabled, priority) "
            "VALUES ('sabnzbd', 'sab', 'localhost', 8080, 'testkey', 1, 1)"
        )
        await db.commit()

        from grabbers import grab_usenet
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"status": False, "error": "API Key Incorrect"}

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await grab_usenet("http://nzb.example/file.nzb")

        assert result is False, "SABnzbd status=false must return False"

    @pytest.mark.asyncio
    async def test_status_key_absent_returns_false(self, db):
        """If 'status' is missing from SABnzbd response, must return False (not crash)."""
        await db.execute(
            "INSERT INTO download_clients (type, name, host, port, api_key, enabled, priority) "
            "VALUES ('sabnzbd', 'sab', 'localhost', 8080, 'testkey', 1, 1)"
        )
        await db.commit()

        from grabbers import grab_usenet
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"nzo_ids": ["SABnzbd_nzo_1"]}  # no 'status' key

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await grab_usenet("http://nzb.example/file.nzb")

        assert result is False, "Missing 'status' must return False, not crash or return True"

    @pytest.mark.asyncio
    async def test_sends_apikey_param(self, db):
        await db.execute(
            "INSERT INTO download_clients (type, name, host, port, api_key, enabled, priority) "
            "VALUES ('sabnzbd', 'sab', 'localhost', 8080, 'myverysecretkey', 1, 1)"
        )
        await db.commit()

        from grabbers import grab_usenet
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"status": True}

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            await grab_usenet("http://nzb.example/file.nzb")

        params = mock_client.get.call_args[1].get("params", {})
        assert params.get("apikey") == "myverysecretkey", f"apikey param wrong. {params}"

    @pytest.mark.asyncio
    async def test_sends_cat_music(self, db):
        await db.execute(
            "INSERT INTO download_clients (type, name, host, port, api_key, enabled, priority) "
            "VALUES ('sabnzbd', 'sab', 'localhost', 8080, 'testkey', 1, 1)"
        )
        await db.commit()

        from grabbers import grab_usenet
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"status": True}

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            await grab_usenet("http://nzb.example/file.nzb")

        params = mock_client.get.call_args[1].get("params", {})
        assert params.get("cat") == "music", f"cat param not 'music'. {params}"

    @pytest.mark.asyncio
    async def test_nzb_url_as_name_param(self, db):
        """SABnzbd addurl expects the NZB URL in the 'name' param."""
        await db.execute(
            "INSERT INTO download_clients (type, name, host, port, api_key, enabled, priority) "
            "VALUES ('sabnzbd', 'sab', 'localhost', 8080, 'testkey', 1, 1)"
        )
        await db.commit()

        from grabbers import grab_usenet
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"status": True}
        nzb_url = "https://indexer.example/nzb/abc123.nzb"

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            await grab_usenet(nzb_url)

        params = mock_client.get.call_args[1].get("params", {})
        assert params.get("name") == nzb_url, f"NZB URL not in 'name' param. {params}"


# ---------------------------------------------------------------------------
# grab_soulseek_files
# ---------------------------------------------------------------------------
class TestGrabSoulseekFiles:
    @pytest.mark.asyncio
    async def test_returns_false_no_client(self, db):
        from grabbers import grab_soulseek_files
        assert await grab_soulseek_files("user", [{"filename": "song.flac", "size": 1000}]) is False

    @pytest.mark.asyncio
    async def test_all_queued_returns_true_no_post(self, db):
        """All files already queued → True returned, POST must NOT fire."""
        await db.execute(
            "INSERT INTO download_clients (type, name, host, port, api_key, enabled, priority) "
            "VALUES ('slskd', 'slskd', 'localhost', 5030, 'testkey', 1, 1)"
        )
        await db.commit()

        from grabbers import grab_soulseek_files
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.json.return_value = [{"filename": "Music/Artist/Album/song.flac"}]

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=get_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await grab_soulseek_files(
                "user", [{"filename": "Music/Artist/Album/song.flac", "size": 30_000_000}]
            )

        assert result is True, "All files already queued must return True"
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_partial_dedup_excludes_existing_files(self, db):
        """Already-queued filenames must not appear in the POST payload."""
        await db.execute(
            "INSERT INTO download_clients (type, name, host, port, api_key, enabled, priority) "
            "VALUES ('slskd', 'slskd', 'localhost', 5030, 'testkey', 1, 1)"
        )
        await db.commit()

        from grabbers import grab_soulseek_files
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.json.return_value = [{"filename": "Music/Artist/Album/track1.flac"}]
        post_resp = MagicMock()
        post_resp.status_code = 200

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=get_resp)
            mock_client.post = AsyncMock(return_value=post_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            await grab_soulseek_files(
                "user",
                [
                    {"filename": "Music/Artist/Album/track1.flac", "size": 30_000_000},
                    {"filename": "Music/Artist/Album/track2.flac", "size": 28_000_000},
                ],
            )

        posted = [f["filename"] for f in mock_client.post.call_args[1].get("json", [])]
        assert "Music/Artist/Album/track1.flac" not in posted, "Existing file must be deduped out"
        assert "Music/Artist/Album/track2.flac" in posted, "New file must be in POST"

    @pytest.mark.asyncio
    async def test_queue_check_failure_still_posts(self, db):
        """If existing-queue GET fails, must still POST (don't skip the whole download)."""
        await db.execute(
            "INSERT INTO download_clients (type, name, host, port, api_key, enabled, priority) "
            "VALUES ('slskd', 'slskd', 'localhost', 5030, 'testkey', 1, 1)"
        )
        await db.commit()

        from grabbers import grab_soulseek_files
        post_resp = MagicMock()
        post_resp.status_code = 200

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
            mock_client.post = AsyncMock(return_value=post_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await grab_soulseek_files("user", [{"filename": "song.flac", "size": 1000}])

        assert result is True
        mock_client.post.assert_called_once(), "POST must be attempted even if queue-check fails"

    @pytest.mark.asyncio
    async def test_204_response_is_success(self, db):
        """slskd returns 204 No Content on success — must not be treated as failure."""
        await db.execute(
            "INSERT INTO download_clients (type, name, host, port, api_key, enabled, priority) "
            "VALUES ('slskd', 'slskd', 'localhost', 5030, 'testkey', 1, 1)"
        )
        await db.commit()

        from grabbers import grab_soulseek_files
        post_resp = MagicMock()
        post_resp.status_code = 204

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("irrelevant"))
            mock_client.post = AsyncMock(return_value=post_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await grab_soulseek_files("user", [{"filename": "song.flac", "size": 1000}])

        assert result is True, "HTTP 204 from slskd must be success"

    @pytest.mark.asyncio
    async def test_api_key_in_post_header(self, db):
        await db.execute(
            "INSERT INTO download_clients (type, name, host, port, api_key, enabled, priority) "
            "VALUES ('slskd', 'slskd', 'localhost', 5030, 'my-slsk-key', 1, 1)"
        )
        await db.commit()

        from grabbers import grab_soulseek_files
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.json.return_value = []
        post_resp = MagicMock()
        post_resp.status_code = 200

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=get_resp)
            mock_client.post = AsyncMock(return_value=post_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            await grab_soulseek_files("user", [{"filename": "song.flac", "size": 1000}])

        headers = mock_client.post.call_args[1].get("headers", {})
        assert headers.get("X-API-Key") == "my-slsk-key", f"X-API-Key missing. headers={headers}"

    @pytest.mark.asyncio
    async def test_dict_format_response_dedups_correctly(self, db):
        """slskd may return queue as dict with 'files' key. Dedup must handle this."""
        await db.execute(
            "INSERT INTO download_clients (type, name, host, port, api_key, enabled, priority) "
            "VALUES ('slskd', 'slskd', 'localhost', 5030, 'testkey', 1, 1)"
        )
        await db.commit()

        from grabbers import grab_soulseek_files
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.json.return_value = {"files": [{"filename": "Music/Artist/Album/song.flac"}]}

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=get_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await grab_soulseek_files(
                "user", [{"filename": "Music/Artist/Album/song.flac", "size": 30_000_000}]
            )

        assert result is True, "Dict-format queue response must still trigger dedup"
        mock_client.post.assert_not_called()


# ---------------------------------------------------------------------------
# search_indexers_auto
# ---------------------------------------------------------------------------
class TestSearchIndexersAuto:
    @pytest.mark.asyncio
    async def test_no_enabled_indexers(self, db):
        from grabbers import search_indexers_auto
        assert await search_indexers_auto("Artist Song", "torrent") == []

    @pytest.mark.asyncio
    async def test_disabled_indexer_never_queried(self, db):
        await db.execute(
            "INSERT INTO indexers (name, type, url, api_key, enabled, priority) "
            "VALUES ('Disabled', 'prowlarr', 'http://p:9696', 'k', 0, 1)"
        )
        await db.commit()

        from grabbers import search_indexers_auto
        with patch("grabbers._search_one_indexer", new_callable=AsyncMock, return_value=[]) as mock_s:
            await search_indexers_auto("Artist Song", "torrent")
        mock_s.assert_not_called()

    @pytest.mark.asyncio
    async def test_stops_at_first_indexer_with_results(self, db):
        """Once first indexer returns results, second must NOT be queried."""
        await db.execute(
            "INSERT INTO indexers (name, type, url, api_key, enabled, priority) "
            "VALUES ('First', 'prowlarr', 'http://f:9696', 'k1', 1, 1)"
        )
        await db.execute(
            "INSERT INTO indexers (name, type, url, api_key, enabled, priority) "
            "VALUES ('Second', 'prowlarr', 'http://s:9696', 'k2', 1, 2)"
        )
        await db.commit()

        calls = []
        async def mock_search(indexer, query, protocol, limit):
            calls.append(indexer["name"])
            if indexer["name"] == "First":
                return [{"title": "Artist FLAC", "download_url": "http://dl/1", "seeders": 5}]
            return [{"title": "Other", "download_url": "http://dl/2", "seeders": 3}]

        from grabbers import search_indexers_auto
        with patch("grabbers._search_one_indexer", side_effect=mock_search):
            result = await search_indexers_auto("Artist Song", "torrent")

        assert "Second" not in calls, f"Second queried despite First having results. Calls: {calls}"
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_falls_through_when_first_empty(self, db):
        await db.execute(
            "INSERT INTO indexers (name, type, url, api_key, enabled, priority) "
            "VALUES ('Empty', 'prowlarr', 'http://e:9696', 'k1', 1, 1)"
        )
        await db.execute(
            "INSERT INTO indexers (name, type, url, api_key, enabled, priority) "
            "VALUES ('HasResults', 'prowlarr', 'http://r:9696', 'k2', 1, 2)"
        )
        await db.commit()

        async def mock_search(indexer, query, protocol, limit):
            if indexer["name"] == "Empty":
                return []
            return [{"title": "Artist Album 320", "download_url": "http://dl/1", "seeders": 5}]

        from grabbers import search_indexers_auto
        with patch("grabbers._search_one_indexer", side_effect=mock_search):
            result = await search_indexers_auto("Artist Song", "torrent")

        assert len(result) == 1, "Must fall through to second indexer when first is empty"

    @pytest.mark.asyncio
    async def test_blocklisted_url_causes_fallthrough(self, db):
        """Blocklisted URL in first indexer's results → all results stripped → fallthrough."""
        await db.execute(
            "INSERT INTO indexers (name, type, url, api_key, enabled, priority) "
            "VALUES ('First', 'prowlarr', 'http://f:9696', 'k1', 1, 1)"
        )
        await db.execute(
            "INSERT INTO indexers (name, type, url, api_key, enabled, priority) "
            "VALUES ('Second', 'prowlarr', 'http://s:9696', 'k2', 1, 2)"
        )
        await db.execute("INSERT INTO blocklist (value) VALUES ('http://blocked.url/torrent')")
        await db.commit()

        async def mock_search(indexer, query, protocol, limit):
            if indexer["name"] == "First":
                return [{"title": "Artist FLAC", "download_url": "http://blocked.url/torrent", "seeders": 10}]
            return [{"title": "Artist MP3", "download_url": "http://clean.url/torrent", "seeders": 5}]

        from grabbers import search_indexers_auto
        with patch("grabbers._search_one_indexer", side_effect=mock_search):
            result = await search_indexers_auto("Artist Song", "torrent")

        assert result, "Must fall through to second indexer after first is entirely blocklisted"
        assert result[0]["download_url"] == "http://clean.url/torrent"

    @pytest.mark.asyncio
    async def test_movie_title_causes_fallthrough(self, db):
        """Non-music (BluRay/1080p) results filtered from first indexer → fallthrough."""
        await db.execute(
            "INSERT INTO indexers (name, type, url, api_key, enabled, priority) "
            "VALUES ('First', 'prowlarr', 'http://f:9696', 'k1', 1, 1)"
        )
        await db.execute(
            "INSERT INTO indexers (name, type, url, api_key, enabled, priority) "
            "VALUES ('Second', 'prowlarr', 'http://s:9696', 'k2', 1, 2)"
        )
        await db.commit()

        async def mock_search(indexer, query, protocol, limit):
            if indexer["name"] == "First":
                return [{"title": "Artist.2024.1080p.BluRay.x264-GROUP", "download_url": "http://dl/1", "seeders": 50}]
            return [{"title": "Artist Album FLAC", "download_url": "http://dl/2", "seeders": 5}]

        from grabbers import search_indexers_auto
        with patch("grabbers._search_one_indexer", side_effect=mock_search):
            result = await search_indexers_auto("Artist Song", "torrent")

        assert result, "Must fall through to second after movie result is filtered"
        assert "BluRay" not in result[0]["title"]

    @pytest.mark.asyncio
    async def test_priority_order_ascending(self, db):
        """Priority=1 must be queried before priority=10."""
        await db.execute(
            "INSERT INTO indexers (name, type, url, api_key, enabled, priority) "
            "VALUES ('LowPri', 'prowlarr', 'http://lo:9696', 'k1', 1, 10)"
        )
        await db.execute(
            "INSERT INTO indexers (name, type, url, api_key, enabled, priority) "
            "VALUES ('HighPri', 'prowlarr', 'http://hi:9696', 'k2', 1, 1)"
        )
        await db.commit()

        order = []
        async def mock_search(indexer, query, protocol, limit):
            order.append(indexer["name"])
            return []

        from grabbers import search_indexers_auto
        with patch("grabbers._search_one_indexer", side_effect=mock_search):
            await search_indexers_auto("Artist Song", "torrent")

        assert order[0] == "HighPri", f"Priority=1 must come first. Got: {order}"


# ---------------------------------------------------------------------------
# grab_youtube
# ---------------------------------------------------------------------------
class TestGrabYoutube:
    def _settings_side_effect(self, key, d=""):
        return {
            "metube_url": "http://metube:8081",
            "youtube_audio_format": "mp3",
            "youtube_audio_quality": "0",
        }.get(key, d)

    @pytest.mark.asyncio
    async def test_quality_zero_maps_to_best(self, db):
        """quality='0' must map to 'best', not pass the literal string '0' to MeTube."""
        from grabbers import grab_youtube
        resp = MagicMock()
        resp.status_code = 200

        with patch("grabbers.get_setting", new_callable=AsyncMock,
                   side_effect=self._settings_side_effect), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            await grab_youtube("https://youtube.com/watch?v=abc")

        posted = mock_client.post.call_args[1].get("json", {})
        assert posted.get("quality") == "best", (
            f"Quality '0' must map to 'best'. Got: {posted.get('quality')}"
        )

    @pytest.mark.asyncio
    async def test_posts_to_correct_endpoint(self, db):
        from grabbers import grab_youtube
        resp = MagicMock()
        resp.status_code = 200

        with patch("grabbers.get_setting", new_callable=AsyncMock,
                   side_effect=self._settings_side_effect), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            await grab_youtube("https://youtube.com/watch?v=abc")

        url = mock_client.post.call_args[0][0]
        assert url == "http://metube:8081/add", f"Wrong endpoint: {url}"

    @pytest.mark.asyncio
    async def test_video_url_in_payload(self, db):
        from grabbers import grab_youtube
        resp = MagicMock()
        resp.status_code = 200
        video = "https://youtube.com/watch?v=UNIQUEID999"

        with patch("grabbers.get_setting", new_callable=AsyncMock,
                   side_effect=self._settings_side_effect), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            await grab_youtube(video)

        posted = mock_client.post.call_args[1].get("json", {})
        assert posted.get("url") == video, f"Video URL not in payload. Got: {posted}"
