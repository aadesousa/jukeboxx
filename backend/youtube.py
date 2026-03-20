"""
YouTube integration via MeTube.
MeTube handles the actual downloading; this module proxies requests to it
and tracks downloads in the local DB.
"""
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db, get_setting, add_activity

log = logging.getLogger("jukeboxx.youtube")
router = APIRouter(prefix="/youtube", tags=["youtube"])


async def get_metube_url() -> str:
    return await get_setting("metube_url", "http://metube:8081")


# ─── Models ────────────────────────────────────────────────────────────────────

class YoutubeDownloadRequest(BaseModel):
    url: str
    audio_format: Optional[str] = None   # mp3, opus, flac, m4a, wav, best
    audio_quality: Optional[str] = None  # 0=best, 5=medium, 9=worst
    folder: Optional[str] = None


# ─── Routes ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def youtube_status():
    """Check if MeTube is reachable."""
    base = await get_metube_url()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{base}/")
            return {"reachable": r.status_code < 500, "url": base}
    except Exception as e:
        return {"reachable": False, "url": base, "error": str(e)}


@router.post("/download")
async def youtube_download(body: YoutubeDownloadRequest):
    """Submit a URL to MeTube for download."""
    base = await get_metube_url()
    audio_format = body.audio_format or await get_setting("youtube_audio_format", "mp3")
    raw_quality = body.audio_quality or await get_setting("youtube_audio_quality", "0")
    # MeTube quality: '128', '192', '320', 'best' (not yt-dlp's 0-9 VBR scale)
    quality_map = {"0": "best", "1": "best", "2": "320", "3": "320",
                   "4": "192", "5": "192", "6": "128", "7": "128", "8": "128", "9": "128"}
    audio_quality = quality_map.get(raw_quality, raw_quality) if raw_quality in quality_map else raw_quality

    # MeTube add endpoint
    payload = {
        "url": body.url,
        "quality": audio_quality,
        "format": audio_format,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{base}/add", json=payload)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"MeTube unreachable: {e}")

    # Track in local DB
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO youtube_downloads (url, status) VALUES (?, 'pending')",
            (body.url,)
        )
        dl_id = cur.lastrowid
        await db.commit()
    finally:
        await db.close()

    await add_activity("youtube_download_queued", body.url)
    return {"ok": True, "local_id": dl_id, "metube_response": data}


@router.get("/queue")
async def youtube_queue():
    """Proxy the MeTube queue status."""
    base = await get_metube_url()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # MeTube exposes /queue via WebSocket, but also /history via HTTP
            r = await client.get(f"{base}/history")
            if r.status_code == 200:
                return {"history": r.json()}
            return {"history": [], "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"history": [], "error": str(e)}


@router.get("/history")
async def youtube_local_history():
    """Return locally tracked YouTube downloads."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM youtube_downloads ORDER BY created_at DESC LIMIT 200"
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()
