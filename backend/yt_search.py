"""
YouTube search integration using YouTube Data API v3.
Used as fallback download source when Spotizerr fails.
"""
import logging
import re
from typing import Optional

import httpx

from database import get_db, get_setting

log = logging.getLogger("jukeboxx.yt_search")

YT_API_BASE = "https://www.googleapis.com/youtube/v3"


async def get_api_key() -> Optional[str]:
    key = await get_setting("youtube_api_key", "")
    return key if key else None


def _parse_duration(iso_duration: str) -> int:
    """Parse ISO 8601 duration (PT4M33S) → seconds."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration)
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def _score_candidate(artist: str, title: str, duration_ms: int, yt_item: dict) -> float:
    """
    Score a YouTube search result against a Spotify track.
    Returns 0-100 score. Higher is better.

    Scoring weights:
    - Title similarity: 40 pts
    - Artist in channel/title: 30 pts
    - Duration match: 30 pts
    """
    from difflib import SequenceMatcher

    def sim(a: str, b: str) -> float:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    snippet = yt_item.get("snippet", {})
    content = yt_item.get("contentDetails", {})

    yt_title   = snippet.get("title", "")
    yt_channel = snippet.get("channelTitle", "")
    yt_dur_s   = _parse_duration(content.get("duration", "PT0S"))
    target_s   = duration_ms / 1000 if duration_ms else 0

    # Title score
    title_score = sim(title, yt_title) * 40

    # Artist score: check if artist name appears in title or channel
    artist_in_title   = sim(artist, yt_title)   * 15
    artist_in_channel = sim(artist, yt_channel) * 15
    artist_score = max(artist_in_title, artist_in_channel)

    # Duration score: within 5s → full, degrades over 30s
    if target_s > 0 and yt_dur_s > 0:
        diff = abs(target_s - yt_dur_s)
        dur_score = max(0.0, 1.0 - diff / 30) * 30
    else:
        dur_score = 0.0

    total = title_score + artist_score + dur_score
    return round(min(100.0, total), 1)


async def search_track(
    artist: str,
    title: str,
    duration_ms: int = 0,
    max_results: int = 5,
    mode: str = "studio",
) -> list[dict]:
    """
    Search YouTube for a track and return scored candidates.
    Each result: {video_id, title, channel, duration_s, score, thumbnail}
    mode: "studio" → "official audio", "music_video" → "official music video"
    """
    api_key = await get_api_key()
    if not api_key:
        return []

    suffix = "official audio" if mode == "studio" else "official music video"
    query = f"{artist} {title} {suffix}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Step 1: search
            r = await client.get(f"{YT_API_BASE}/search", params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "videoCategoryId": "10",  # Music category
                "maxResults": max_results,
                "key": api_key,
            })
            r.raise_for_status()
            search_data = r.json()

            video_ids = [item["id"]["videoId"] for item in search_data.get("items", [])
                         if item.get("id", {}).get("videoId")]
            if not video_ids:
                return []

            # Step 2: get content details (duration)
            r2 = await client.get(f"{YT_API_BASE}/videos", params={
                "part": "snippet,contentDetails",
                "id": ",".join(video_ids),
                "key": api_key,
            })
            r2.raise_for_status()
            video_data = {v["id"]: v for v in r2.json().get("items", [])}

    except httpx.HTTPError as e:
        log.error(f"YouTube API error: {e}")
        return []

    results = []
    for vid_id in video_ids:
        item = video_data.get(vid_id)
        if not item:
            continue
        snippet = item.get("snippet", {})
        content = item.get("contentDetails", {})
        dur_s   = _parse_duration(content.get("duration", "PT0S"))
        score   = _score_candidate(artist, title, duration_ms, item)

        thumb = (snippet.get("thumbnails", {}).get("medium", {}) or
                 snippet.get("thumbnails", {}).get("default", {}))

        results.append({
            "video_id":   vid_id,
            "url":        f"https://www.youtube.com/watch?v={vid_id}",
            "title":      snippet.get("title", ""),
            "channel":    snippet.get("channelTitle", ""),
            "duration_s": dur_s,
            "score":      score,
            "thumbnail":  thumb.get("url", ""),
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


async def auto_fallback(
    monitored_track_id: int,
    artist: str,
    title: str,
    duration_ms: int = 0,
) -> dict:
    """
    Run YouTube fallback for a failed Spotizerr download.
    - Score ≥ auto_threshold → auto-queue to MeTube
    - 70 ≤ score < threshold → create pending_review entry
    - score < 70 → no match
    Returns: {action: 'queued'|'review'|'no_match', score, video_id}
    """
    auto_threshold = int(await get_setting("youtube_auto_threshold", "85"))
    fallback_enabled = await get_setting("youtube_fallback_enabled", "0") == "1"

    if not fallback_enabled:
        return {"action": "disabled"}

    mode = await get_setting("youtube_search_mode", "studio")
    candidates = await search_track(artist, title, duration_ms, max_results=5, mode=mode)
    if not candidates:
        return {"action": "no_match", "reason": "No API key or no results"}

    best = candidates[0]
    score = best["score"]

    db = await get_db()
    try:
        if score >= auto_threshold:
            # Auto-queue to MeTube
            from youtube import YoutubeDownloadRequest
            import httpx as _httpx
            metube_url = await get_setting("metube_url", "http://metube:8081")
            audio_format = await get_setting("youtube_audio_format", "mp3")
            try:
                async with _httpx.AsyncClient(timeout=30) as client:
                    await client.post(f"{metube_url}/add", json={
                        "url": best["url"],
                        "quality": "audio",
                        "format": audio_format,
                    })
                action = "queued"
            except Exception as e:
                log.error(f"MeTube dispatch failed: {e}")
                action = "review"  # Fall through to review if MeTube is down

            if action == "queued":
                # Update monitored track status
                await db.execute(
                    "UPDATE monitored_tracks SET status='downloading' WHERE id=?",
                    (monitored_track_id,)
                )
                await db.commit()
                return {"action": "queued", "score": score, "video_id": best["video_id"], "url": best["url"]}

        if score >= 70:
            # Create review entry
            await db.execute(
                """INSERT INTO youtube_review_queue
                   (monitored_track_id, video_id, video_url, video_title, video_channel,
                    video_duration_s, score, artist, title, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(monitored_track_id) DO UPDATE SET
                     video_id=excluded.video_id, video_url=excluded.video_url,
                     video_title=excluded.video_title, score=excluded.score,
                     created_at=CURRENT_TIMESTAMP""",
                (monitored_track_id, best["video_id"], best["url"], best["title"],
                 best["channel"], best["duration_s"], score, artist, title)
            )
            await db.commit()
            return {"action": "review", "score": score, "video_id": best["video_id"]}

        return {"action": "no_match", "score": score}
    finally:
        await db.close()


async def get_review_queue(limit: int = 50, offset: int = 0) -> list[dict]:
    """Fetch pending YouTube review items."""
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT q.*, mt.name AS track_name, mt.artist_name, mt.album_name
               FROM youtube_review_queue q
               LEFT JOIN monitored_tracks mt ON mt.id = q.monitored_track_id
               WHERE q.reviewed = 0
               ORDER BY q.score DESC
               LIMIT ? OFFSET ?""",
            (limit, offset)
        )
        return [dict(r) for r in await cur.fetchall()]
    except Exception:
        # Table may not exist yet
        return []
    finally:
        await db.close()
