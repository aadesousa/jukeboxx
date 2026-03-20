"""
Phase 1.7 / Phase 5.3: Scanner tests.
Covers tag reading, normalization, file type support, and edge cases.
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from scanner import (
    normalize_title,
    normalize_artist,
    read_tags,
    SUPPORTED_EXTENSIONS,
    SKIP_DIRS,
)


class TestNormalizeTitle:
    def test_strips_feat(self):
        assert normalize_title("Song (feat. Someone)") == "Song"

    def test_strips_ft(self):
        assert normalize_title("Song (ft. Someone)") == "Song"

    def test_strips_featuring(self):
        assert normalize_title("Song [featuring Artist]") == "Song"

    def test_strips_with(self):
        assert normalize_title("Song (with Other)") == "Song"

    def test_no_feat_unchanged(self):
        assert normalize_title("Just A Song") == "Just A Song"

    def test_empty_string(self):
        assert normalize_title("") == ""

    def test_none_passthrough(self):
        assert normalize_title(None) is None

    def test_multiple_feat_variants(self):
        result = normalize_title("Track feat. A (ft. B)")
        assert "feat" not in result.lower()


class TestNormalizeArtist:
    def test_strips_feat(self):
        assert normalize_artist("Artist feat. Other") == "Artist"

    def test_strips_ft(self):
        assert normalize_artist("Artist ft. Other") == "Artist"

    def test_primary_only(self):
        assert normalize_artist("Main Artist featuring Guest") == "Main Artist"

    def test_no_feat_unchanged(self):
        assert normalize_artist("Solo Artist") == "Solo Artist"

    def test_empty_string(self):
        assert normalize_artist("") == ""

    def test_none_passthrough(self):
        assert normalize_artist(None) is None


class TestSupportedExtensions:
    def test_mp3_supported(self):
        assert ".mp3" in SUPPORTED_EXTENSIONS

    def test_flac_supported(self):
        assert ".flac" in SUPPORTED_EXTENSIONS

    def test_m4a_supported(self):
        assert ".m4a" in SUPPORTED_EXTENSIONS

    def test_ogg_supported(self):
        assert ".ogg" in SUPPORTED_EXTENSIONS

    def test_opus_supported(self):
        assert ".opus" in SUPPORTED_EXTENSIONS

    def test_wav_supported(self):
        assert ".wav" in SUPPORTED_EXTENSIONS

    def test_aac_supported(self):
        assert ".aac" in SUPPORTED_EXTENSIONS

    def test_skip_dirs(self):
        assert "Playlists" in SKIP_DIRS
        assert "failed_imports" in SKIP_DIRS


class TestReadTags:
    def test_nonexistent_file_returns_defaults(self):
        tags = read_tags("/nonexistent/path/song.mp3")
        assert tags["artist"] is None
        assert tags["title"] is None
        assert tags["format"] is None

    def test_returns_dict_with_expected_keys(self):
        tags = read_tags("/nonexistent/path/song.mp3")
        expected_keys = {
            "artist", "album_artist", "title", "album",
            "track_number", "disc_number", "year", "genre",
            "format", "bitrate", "duration", "mbid",
        }
        assert expected_keys.issubset(set(tags.keys()))

    def test_empty_file_returns_defaults(self, tmp_path):
        """An empty file should not crash the tag reader."""
        f = tmp_path / "empty.mp3"
        f.write_bytes(b"")
        tags = read_tags(str(f))
        assert tags["format"] is None or tags["format"] == "MP3"

    def test_special_characters_in_path(self, tmp_path):
        """Files with unicode characters in path should not crash."""
        f = tmp_path / "café_résumé.mp3"
        f.write_bytes(b"\x00" * 10)
        tags = read_tags(str(f))
        assert isinstance(tags, dict)


class TestScannerEdgeCases:
    """Phase 5.3: Filesystem edge cases."""

    def test_symlink_in_music_dir(self, tmp_path):
        """Scanner should handle symlinks without crashing."""
        real = tmp_path / "real.mp3"
        real.write_bytes(b"\x00" * 10)
        link = tmp_path / "link.mp3"
        link.symlink_to(real)
        tags = read_tags(str(link))
        assert isinstance(tags, dict)

    def test_very_long_filename(self, tmp_path):
        """Very long filenames should not crash."""
        long_name = "a" * 200 + ".mp3"
        f = tmp_path / long_name
        try:
            f.write_bytes(b"\x00" * 10)
            tags = read_tags(str(f))
            assert isinstance(tags, dict)
        except OSError:
            # OS may reject very long paths — that's fine
            pass
