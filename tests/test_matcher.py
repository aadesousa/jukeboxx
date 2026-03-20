"""
Phase 6.1 / Phase 1: Matcher tests.
Covers normalization, version penalties, scoring, and match logic.
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from matcher import _norm, version_penalty, _score


class TestNorm:
    def test_strips_feat(self):
        assert "guest" not in _norm("Song (feat. Guest Artist)")

    def test_strips_brackets(self):
        assert "remastered" not in _norm("Song [Remastered 2020]")

    def test_strips_punctuation(self):
        result = _norm("Hello, World! It's Great")
        assert "," not in result
        assert "!" not in result

    def test_strips_articles(self):
        assert _norm("The Beatles").startswith("beatles")
        assert _norm("A Song").startswith("song")
        assert _norm("An Album").startswith("album")

    def test_lowercases(self):
        assert _norm("UPPERCASE") == "uppercase"

    def test_collapses_whitespace(self):
        assert "  " not in _norm("  multiple   spaces  ")

    def test_empty_string(self):
        assert _norm("") == ""

    def test_none_handled(self):
        assert _norm(None) == ""


class TestVersionPenalty:
    def test_no_penalty_studio_vs_studio(self):
        assert version_penalty("Song Name", "Song Name") == 0

    def test_live_penalty(self):
        pen = version_penalty("Song (Live at Wembley)", "Song")
        assert pen >= 20

    def test_screwed_chopped_penalty(self):
        pen = version_penalty("V.I.C.E.S. (Screwed X Chopped by DJ Kirby)", "V.I.C.E.S.")
        assert pen >= 40

    def test_instrumental_penalty(self):
        pen = version_penalty("Song (Instrumental)", "Song")
        assert pen >= 30

    def test_karaoke_max_penalty(self):
        pen = version_penalty("Song (Karaoke Version)", "Song")
        assert pen >= 50

    def test_remix_penalty(self):
        pen = version_penalty("Song (DJ Remix)", "Song")
        assert pen >= 15

    def test_cover_penalty(self):
        pen = version_penalty("Song (Cover)", "Song")
        assert pen >= 25

    def test_demo_penalty(self):
        pen = version_penalty("Song (Demo)", "Song")
        assert pen >= 20

    def test_remaster_low_penalty(self):
        pen = version_penalty("Song (Remastered)", "Song")
        assert pen <= 10

    def test_penalty_capped_at_55(self):
        """Penalty should never exceed 55."""
        pen = version_penalty(
            "Song (Karaoke Instrumental Cover Screwed Chopped Live Demo)",
            "Song"
        )
        assert pen <= 55

    def test_no_penalty_when_both_have_keyword(self):
        """If both local and Spotify have the keyword, no penalty."""
        pen = version_penalty("Song (Live)", "Song (Live)")
        assert pen == 0

    def test_radio_edit_low_penalty(self):
        pen = version_penalty("Song (Radio Edit)", "Song")
        assert pen <= 15


class TestScore:
    def test_perfect_match(self):
        score = _score(
            "Song Title", "Artist Name", 200,
            "Song Title", "Artist Name", 200000,
        )
        assert score >= 90

    def test_different_titles_low_score(self):
        score = _score(
            "Completely Different", "Other Artist", 180,
            "Song Title", "Artist Name", 200000,
        )
        assert score < 50

    def test_duration_mismatch_caps_score(self):
        """Large duration diff (>10s) + imperfect title match should cap score at 65.

        The _score function caps conf at 65 when:
          - abs(local_dur - spotify_dur) > 10 seconds, AND
          - title_score < 95 OR artist_score < 95
        This prevents a 100s-different track from scoring as a confident match.
        """
        # "My Song Title Name" vs "My Track Title Name" → title_score ~78% (< 95)
        # artist is identical → artist_score = 100
        # local 300s vs spotify 200s → dur diff = 100s > 10s → cap applies
        # conf before cap ≈ 0.45*78 + 0.35*100 + 0.20*0 = 70 → capped to 65
        score = _score(
            "My Song Title Name", "Band Artist Name", 300,
            "My Track Title Name", "Band Artist Name", 200000,
        )
        assert score <= 65

        # Same strings but matching duration should score HIGHER (no cap)
        score_same_dur = _score(
            "My Song Title Name", "Band Artist Name", 300,
            "My Track Title Name", "Band Artist Name", 300000,
        )
        assert score_same_dur > score

    def test_missing_artist_gives_moderate_score(self):
        """When artist is empty, artist_score defaults to 40."""
        score = _score(
            "Song Title", "", 200,
            "Song Title", "", 200000,
        )
        assert 50 <= score <= 85

    def test_version_penalty_reduces_score(self):
        """A live version matched against studio should score lower."""
        studio_score = _score(
            "Song", "Artist", 200,
            "Song", "Artist", 200000,
        )
        live_score = _score(
            "Song (Live at Wembley)", "Artist", 200,
            "Song", "Artist", 200000,
        )
        assert live_score < studio_score

    def test_score_never_negative(self):
        score = _score(
            "Karaoke Instrumental Cover", "Nobody", 999,
            "Real Song", "Real Artist", 200000,
        )
        assert score >= 0

    def test_album_context_affects_penalty(self):
        """Version keywords in album name should also trigger penalty."""
        score_clean = _score(
            "Song", "Artist", 200,
            "Song", "Artist", 200000,
            local_album="Studio Album",
            spotify_album="Studio Album",
        )
        score_live = _score(
            "Song", "Artist", 200,
            "Song", "Artist", 200000,
            local_album="Live in Concert",
            spotify_album="Studio Album",
        )
        assert score_live < score_clean
