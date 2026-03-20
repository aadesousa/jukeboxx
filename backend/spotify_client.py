import asyncio
import logging
import requests as _requests
from spotify_auth import get_spotify_client, record_successful_call
from database import get_db
from rapidfuzz import fuzz

log = logging.getLogger("jukeboxx.spotify_client")


async def get_client():
    return await get_spotify_client()


async def enrich_tracks_with_local_status(tracks: list):
    """Add local_status field to each track: 'local', 'downloading', 'queued', 'unavailable', or None."""
    if not tracks:
        return
    db = await get_db()
    try:
        for track in tracks:
            if track.get("unavailable"):
                track["local_status"] = "unavailable"
                continue
            spotify_id = track.get("id")
            if not spotify_id:
                track["local_status"] = None
                continue

            # Check local library
            cur = await db.execute(
                "SELECT id FROM tracks WHERE spotify_id = ? LIMIT 1", (spotify_id,)
            )
            if await cur.fetchone():
                track["local_status"] = "local"
                continue

            # Check downloads
            cur = await db.execute(
                "SELECT status FROM downloads WHERE spotify_id = ? ORDER BY id DESC LIMIT 1",
                (spotify_id,),
            )
            dl_row = await cur.fetchone()
            if dl_row:
                status = dl_row["status"]
                if status in ("pending", "downloading"):
                    track["local_status"] = "downloading"
                    continue
                elif status == "completed":
                    track["local_status"] = "local"
                    continue
                elif status == "failed":
                    track["local_status"] = "failed"
                    continue

            # Fuzzy match by artist + title
            artist = ""
            if track.get("artists"):
                artist = track["artists"][0].get("name", "")
            title = track.get("name", "")
            if artist and title:
                cur = await db.execute(
                    "SELECT id, artist, title FROM tracks WHERE artist LIKE ? LIMIT 20",
                    (f"%{artist[:3]}%",),
                )
                candidates = await cur.fetchall()
                for c in candidates:
                    score = fuzz.token_sort_ratio(
                        f"{artist} {title}".lower(),
                        f"{c['artist'] or ''} {c['title'] or ''}".lower(),
                    )
                    if score >= 85:
                        track["local_status"] = "local"
                        break
                else:
                    track["local_status"] = None
            else:
                track["local_status"] = None
    finally:
        await db.close()


def _extract_playlist_track(item: dict) -> dict | None:
    """Extract a track dict from a playlist item, handling both old and new Spotify API formats.
    Tracks without a valid Spotify ID (local files, removed tracks) are returned with unavailable=True."""
    # New format (Feb 2026 dev mode): item.item contains the track data directly
    t = item.get("item")
    if t and t.get("id") and t.get("track", True):  # track=True means it's a track not episode
        return t
    # Old format: item.track contains the track
    t = item.get("track")
    if t and t.get("id"):
        return t
    # Track exists in playlist but has no valid Spotify ID (local file, removed from Spotify, etc.)
    t = item.get("item") or item.get("track")
    if t:
        return {
            "id": None,
            "name": t.get("name") or "Unavailable Track",
            "artists": t.get("artists", []),
            "album": t.get("album"),
            "is_local": t.get("is_local", False),
            "unavailable": True,
        }
    return None


async def get_all_playlist_tracks(sp, playlist_id: str) -> list:
    """Fetch all tracks from a playlist using the /items endpoint with offset pagination.

    The /tracks endpoint returns 403 in Spotify dev mode. The /items endpoint works.
    We paginate by offset until we have all tracks (using the 'total' field as ground truth).
    """
    tracks = []
    offset = 0
    page_size = 100

    # Get the live access token from spotipy's auth manager
    token = await asyncio.to_thread(_get_token, sp)
    if not token:
        log.error(f"Cannot get access token for playlist {playlist_id}")
        return tracks

    headers = {"Authorization": f"Bearer {token}"}
    base_url = f"https://api.spotify.com/v1/playlists/{playlist_id}/items"
    total_expected = None

    while True:
        try:
            def _fetch(off):
                r = _requests.get(base_url, headers=headers, params={"limit": page_size, "offset": off}, timeout=15)
                r.raise_for_status()
                return r.json()

            data = await asyncio.to_thread(_fetch, offset)
            record_successful_call()

            if total_expected is None:
                total_expected = data.get("total")
                log.info(f"Playlist {playlist_id}: total={total_expected}")

            page_items = data.get("items", [])
            if not page_items:
                break

            for item in page_items:
                t = _extract_playlist_track(item)
                if t:
                    tracks.append(t)

            offset += len(page_items)
            log.debug(f"Playlist {playlist_id}: fetched {offset}/{total_expected}")

            # Stop when we have all tracks or no more pages
            if total_expected is not None and offset >= total_expected:
                break
            if not data.get("next"):
                break

            await asyncio.sleep(0.3)

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "too many" in err_str.lower():
                log.warning(f"Rate limited at offset {offset} for {playlist_id}, stopping with {len(tracks)} tracks")
                break
            log.warning(f"Error at offset {offset} for {playlist_id}: {e}")
            # One retry after a delay
            try:
                await asyncio.sleep(2)
                data = await asyncio.to_thread(_fetch, offset)
                page_items = data.get("items", [])
                for item in page_items:
                    t = _extract_playlist_track(item)
                    if t:
                        tracks.append(t)
                offset += len(page_items)
                if total_expected is not None and offset >= total_expected:
                    break
            except Exception as e2:
                log.error(f"Retry failed for {playlist_id} at offset {offset}: {e2}")
                break

    log.info(f"Playlist {playlist_id}: got {len(tracks)}/{total_expected or '?'} tracks")
    return tracks


def _get_token(sp) -> str | None:
    """Extract the current access token from a spotipy client."""
    try:
        # spotipy stores the token in _auth after any API call
        return sp._auth
    except AttributeError:
        pass
    try:
        return sp.auth_manager.get_access_token(as_dict=False)
    except Exception:
        pass
    return None


