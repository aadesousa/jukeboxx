"""
Phase 2: Pydantic model validation tests.
Ensures models accept valid data and reject invalid data properly.
"""
import pytest
import sys
from pathlib import Path
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from models import (
    SetupRequest, LoginRequest, TrackOut, DownloadOut, SyncItemOut,
    SyncItemCreate, SyncItemUpdate, DuplicateResolve, ScanStatusOut,
    StatsOut, SettingsOut, SettingsUpdate, DownloadPreview,
    NotificationOut, ActivityOut, ScanProgressOut, MatchScoreOut, MatchRequest,
)


class TestSetupLoginModels:
    def test_setup_request_valid(self):
        req = SetupRequest(username="admin", password="secret123")
        assert req.username == "admin"

    def test_login_request_valid(self):
        req = LoginRequest(username="admin", password="pass")
        assert req.username == "admin"

    def test_setup_request_missing_field(self):
        with pytest.raises(ValidationError):
            SetupRequest(username="admin")  # missing password


class TestTrackOut:
    def test_minimal_track(self):
        t = TrackOut(id=1, path="/music/song.mp3")
        assert t.id == 1
        assert t.path == "/music/song.mp3"
        assert t.artist is None
        assert t.format is None

    def test_full_track(self):
        t = TrackOut(
            id=1, path="/music/song.flac",
            artist="Artist", album_artist="Artist", title="Song",
            album="Album", track_number=1, disc_number=1,
            year=2024, genre="Rock", format="FLAC",
            bitrate=1411, duration=240, size=30000000,
            spotify_id="sp_123",
        )
        assert t.format == "FLAC"
        assert t.bitrate == 1411


class TestDownloadOut:
    def test_default_values(self):
        d = DownloadOut(id=1, spotify_id="sp_123")
        assert d.status == "pending"
        assert d.source == "manual"
        assert d.retry_count == 0


class TestSyncItemModels:
    def test_sync_item_create(self):
        c = SyncItemCreate(spotify_id="pl_123")
        assert c.item_type == "playlist"

    def test_sync_item_update(self):
        u = SyncItemUpdate(enabled=False)
        assert u.enabled is False


class TestStatsOut:
    def test_empty_stats(self):
        s = StatsOut()
        assert s.total_tracks == 0
        assert s.total_size_gb == 0.0
        assert s.format_breakdown == {}

    def test_populated_stats(self):
        s = StatsOut(
            total_tracks=1000, total_artists=50, total_albums=100,
            total_missing=200, total_size_gb=45.5,
            format_breakdown={"FLAC": 600, "MP3": 400},
        )
        assert s.total_tracks == 1000
        assert s.format_breakdown["FLAC"] == 600


class TestScanProgressOut:
    def test_idle(self):
        p = ScanProgressOut()
        assert p.phase == "idle"
        assert p.progress_percent == 0.0


class TestMatchScoreOut:
    def test_confident_match(self):
        m = MatchScoreOut(
            total=92.0, title=95.0, artist=90.0, duration=88.0,
            album=85.0, track_number=100.0, year=100.0,
            is_confident=True, is_fuzzy=False, is_no_match=False,
        )
        assert m.is_confident is True
        assert m.total == 92.0


class TestSettingsModels:
    def test_settings_out_defaults(self):
        s = SettingsOut()
        assert s.spotify_connected is False
        assert s.music_path == "/music"
        assert s.fuzzy_threshold == 85

    def test_settings_update_partial(self):
        u = SettingsUpdate(music_path="/new/path")
        assert u.music_path == "/new/path"
        assert u.spotify_client_id is None  # not set


class TestNotificationOut:
    def test_notification_defaults(self):
        n = NotificationOut(id=1, type="info", title="Test")
        assert n.read is False
        assert n.message is None


class TestMatchRequest:
    def test_valid_request(self):
        r = MatchRequest(
            local={"title": "Song", "artist": "Artist"},
            spotify={"name": "Song", "artists": [{"name": "Artist"}]},
        )
        assert r.local["title"] == "Song"
