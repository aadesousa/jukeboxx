"""
Shared grab/search helpers used by both the API endpoints (main.py)
and the background auto-dispatch (tasks.py).
No FastAPI imports — pure async functions.
"""
import logging
import asyncio
import xml.etree.ElementTree as _ET

import httpx

from database import get_db, get_setting

log = logging.getLogger("jukeboxx.grabbers")

_AUDIO_EXTS = {".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav", ".ape", ".wv", ".aac", ".alac"}

# In-memory YouTube/MeTube submission queue (resets on restart)
_yt_submitted: list[dict] = []

def get_yt_queue() -> list[dict]:
    """Return a copy of in-memory submitted YouTube downloads."""
    return list(_yt_submitted)

# Patterns that strongly indicate a movie/TV torrent, not music
_NON_MUSIC_RE = None

def _is_likely_music(title: str) -> bool:
    """Return False if the torrent title looks like a movie or TV show."""
    import re
    global _NON_MUSIC_RE
    if _NON_MUSIC_RE is None:
        patterns = [
            r'\bS\d{2}E\d{2}\b',          # S01E03
            r'\bSeason\s*\d+\b',            # Season 2
            r'\b(720p|1080p|2160p|4K|4k)\b',
            r'\b(BluRay|BDRip|BRRip|WEB[-.]?DL|WEBRip|HDTV|DVDRip|DVDScr|YIFY|AMZN|NF|DSNP)\b',
            r'\b(x264|x265|HEVC|AVC|h264|h265|XviD|AV1)\b',
            r'\b(mkv|mp4|avi|mov)\b',
            r'\b(Blu[-.]?Ray|UHD|HDR|SDR|Remux)\b',
        ]
        _NON_MUSIC_RE = re.compile("|".join(patterns), re.IGNORECASE)
    return not bool(_NON_MUSIC_RE.search(title))


# ─── Client helpers ───────────────────────────────────────────────────────────

async def _get_client_row(ctype: str) -> dict | None:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM download_clients WHERE type=? AND enabled=1 ORDER BY priority ASC LIMIT 1",
            (ctype,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


def _qbit_base(row: dict) -> str:
    scheme = "https" if row.get("use_ssl") else "http"
    return f"{scheme}://{row['host']}:{row['port']}{(row.get('url_base') or '').rstrip('/')}"


def _sabnzbd_base(row: dict) -> str:
    scheme = "https" if row.get("use_ssl") else "http"
    return f"{scheme}://{row['host']}:{row['port']}{(row.get('url_base') or '').rstrip('/')}"


def _slskd_base(row: dict) -> str:
    url = (row.get("url_base") or "").rstrip("/")
    if not url:
        url = f"http://{row.get('host','localhost')}:{row.get('port',5030)}"
    return url


# ─── Result scoring ───────────────────────────────────────────────────────────

def _score_result(result: dict, quality_profile: dict | None = None) -> int:
    """Score a search result 0-100 based on format and quality profile preferences."""
    score = 50
    title = (result.get("title") or "").lower()

    # Format scoring
    if any(x in title for x in ["flac", "lossless", "24bit", "24-bit"]):
        score += 30
    elif "320" in title:
        score += 20
    elif any(x in title for x in ["v0", "v2", "256kbps", "256 kbps"]):
        score += 10
    elif any(x in title for x in ["128", "96kbps", "64kbps"]):
        score -= 20

    # Seeders (torrents)
    # Use `is not None` to distinguish seeders=0 (dead) from absent
    seeders = result["seeders"] if result.get("seeders") is not None else (result.get("grabs") or 0)
    if isinstance(seeders, int):
        if seeders >= 10:
            score += 15
        elif seeders >= 3:
            score += 7
        elif seeders == 0:
            score -= 25

    # Quality profile word filtering
    if quality_profile:
        preferred = quality_profile.get("preferred_words") or ""
        ignored = quality_profile.get("ignored_words") or ""
        required = quality_profile.get("required_words") or ""

        if preferred:
            for word in [w.strip().lower() for w in preferred.split(",") if w.strip()]:
                if word in title:
                    score += 10
        if ignored:
            for word in [w.strip().lower() for w in ignored.split(",") if w.strip()]:
                if word in title:
                    return -1000  # filter out
        if required:
            req_words = [w.strip().lower() for w in required.split(",") if w.strip()]
            if req_words and not any(w in title for w in req_words):
                return -1000  # filter out

    return score


# ─── Grab functions ───────────────────────────────────────────────────────────

async def grab_torrent(download_url: str) -> bool:
    """Add a torrent URL/magnet to qBittorrent. Returns True on success."""
    row = await _get_client_row("qbittorrent")
    if not row:
        return False
    base = _qbit_base(row)
    try:
        async with httpx.AsyncClient(timeout=15) as hc:
            if row.get("username"):
                login = await hc.post(
                    f"{base}/api/v2/auth/login",
                    data={"username": row["username"], "password": row.get("password", "")},
                )
                if login.text.strip().lower() == "fails":
                    return False
            resp = await hc.post(
                f"{base}/api/v2/torrents/add",
                data={"urls": download_url, "category": "music"},
            )
            return resp.status_code in (200, 201) and resp.text.strip().lower() != "fails"
    except Exception as e:
        log.debug(f"grab_torrent error: {e}")
        return False


async def grab_usenet(download_url: str) -> bool:
    """Add an NZB URL to SABnzbd. Returns True on success."""
    row = await _get_client_row("sabnzbd")
    if not row:
        return False
    base = _sabnzbd_base(row)
    try:
        async with httpx.AsyncClient(timeout=15) as hc:
            resp = await hc.get(
                f"{base}/api",
                params={
                    "mode": "addurl",
                    "name": download_url,
                    "apikey": row.get("api_key", ""),
                    "cat": "music",
                    "output": "json",
                },
            )
            if resp.status_code != 200:
                return False
            return bool(resp.json().get("status"))
    except Exception as e:
        log.debug(f"grab_usenet error: {e}")
        return False


async def grab_soulseek_files(username: str, files: list) -> bool:
    """Queue files for download via slskd. Deduplicates against existing queue. Returns True on success."""
    row = await _get_client_row("slskd")
    if not row:
        return False
    url = _slskd_base(row)
    api_key = row.get("api_key", "")
    headers = {"X-API-Key": api_key} if api_key else {}
    payload = [{"filename": f.get("filename", ""), "size": f.get("size", 0)} for f in files]
    try:
        async with httpx.AsyncClient(timeout=30) as hc:
            # Query existing transfers for this user to avoid re-queueing the same files
            try:
                existing_resp = await hc.get(
                    f"{url}/api/v0/transfers/downloads/{username}",
                    headers=headers,
                )
                if existing_resp.status_code == 200:
                    existing_data = existing_resp.json()
                    # Response may be a list of transfers or a dict with a 'files' key
                    if isinstance(existing_data, list):
                        existing_filenames = {t.get("filename", "") for t in existing_data}
                    elif isinstance(existing_data, dict):
                        existing_filenames = {t.get("filename", "") for t in existing_data.get("files", [])}
                    else:
                        existing_filenames = set()
                    before = len(payload)
                    payload = [p for p in payload if p["filename"] not in existing_filenames]
                    skipped = before - len(payload)
                    if skipped:
                        log.debug(f"grab_soulseek: skipped {skipped} already-queued files for {username}")
                    if not payload:
                        log.debug(f"grab_soulseek: all files already queued for {username}, skipping")
                        return True  # already in queue counts as success
            except Exception as _e:
                log.debug(f"grab_soulseek: could not check existing queue: {_e}")

            resp = await hc.post(
                f"{url}/api/v0/transfers/downloads/{username}",
                json=payload,
                headers=headers,
            )
            return resp.status_code in (200, 201, 204)
    except Exception as e:
        log.debug(f"grab_soulseek error: {e}")
        return False


async def grab_youtube(video_url: str, title: str = "") -> bool:
    """Submit a YouTube URL to MeTube. Returns True on success."""
    metube_url = await get_setting("metube_url", "http://metube:8081")
    audio_format = await get_setting("youtube_audio_format", "mp3")
    # MeTube quality for audio: '128', '192', '320', 'best' (not yt-dlp's 0-9 VBR scale)
    raw_quality = await get_setting("youtube_audio_quality", "0")
    quality_map = {"0": "best", "1": "best", "2": "320", "3": "320",
                   "4": "192", "5": "192", "6": "128", "7": "128", "8": "128", "9": "128"}
    audio_quality = quality_map.get(raw_quality, "best")
    try:
        async with httpx.AsyncClient(timeout=30) as hc:
            resp = await hc.post(
                f"{metube_url}/add",
                json={"url": video_url, "quality": audio_quality, "format": audio_format},
            )
            ok = resp.status_code in (200, 201, 204)
            if ok:
                import datetime as _dt
                _yt_submitted.append({
                    "url": video_url,
                    "title": title or video_url,
                    "status": "Submitted",
                    "submitted_at": _dt.datetime.utcnow().isoformat(),
                })
                # Keep list bounded
                if len(_yt_submitted) > 200:
                    _yt_submitted.pop(0)
            return ok
    except Exception as e:
        log.debug(f"grab_youtube error: {e}")
        return False


# ─── Indexer search ───────────────────────────────────────────────────────────

def _parse_torznab_xml(text: str, indexer_name: str, proto: str) -> list:
    ns = {"torznab": "http://torznab.com/schemas/2015/feed"}
    items = []
    try:
        root = _ET.fromstring(text)
        channel = root.find("channel")
        for item in (channel.findall("item") if channel is not None else []):
            def _txt(tag):
                el = item.find(tag)
                return el.text.strip() if el is not None and el.text else ""
            attrs = {el.get("name", ""): el.get("value", "")
                     for el in item.findall("torznab:attr", ns)}
            enc = item.find("enclosure")
            size = int(enc.get("length", "0")) if enc is not None else 0
            dl_url = _txt("link") or (enc.get("url", "") if enc is not None else "")
            items.append({
                "title": _txt("title"),
                "size": size or int(attrs.get("size", "0") or "0"),
                "seeders": int(attrs.get("seeders", "0") or "0"),
                "leechers": int(attrs.get("peers", "0") or "0"),
                "download_url": dl_url,
                "indexer": indexer_name,
                "indexer_type": proto,
            })
    except Exception as e:
        log.debug(f"XML parse error for {indexer_name}: {e}")
    return items


async def _get_blocklist() -> set:
    """Return set of blocklisted values (URLs/hashes) from DB."""
    db = await get_db()
    try:
        cur = await db.execute("SELECT value FROM blocklist")
        return {row[0] for row in await cur.fetchall()}
    except Exception:
        return set()
    finally:
        await db.close()


async def _search_one_indexer(
    indexer: dict, query: str, protocol: str, limit: int
) -> list:
    """Search a single indexer and return its results for the given protocol."""
    iname = indexer.get("name", "Unknown")
    itype = indexer.get("type", "torznab")
    url = indexer.get("url", "").rstrip("/")
    api_key = indexer.get("api_key", "")

    if not url:
        return []

    results = []
    try:
        _timeout = 60 if itype == "prowlarr" else 15
        async with httpx.AsyncClient(timeout=_timeout) as hc:
            if itype == "prowlarr":
                headers = {"X-Api-Key": api_key} if api_key else {}
                params = {"query": query, "type": "search", "limit": limit}
                resp = await hc.get(f"{url}/api/v1/search", params=params, headers=headers)
                if resp.status_code != 200:
                    return []
                items = resp.json()
                if not isinstance(items, list):
                    items = items.get("results", items.get("Results", []))
                for item in items:
                    proto = (item.get("protocol") or "torrent").lower()
                    if proto != protocol:
                        continue
                    dl = (item.get("downloadUrl") or item.get("magnetUrl")
                          or item.get("DownloadUrl") or "")
                    if not dl:
                        continue
                    results.append({
                        "title": item.get("title") or item.get("Title", ""),
                        "size": item.get("size") or item.get("Size", 0),
                        "seeders": item.get("seeders") or item.get("Seeders", 0),
                        "download_url": dl,
                        "indexer": iname,
                        "indexer_type": proto,
                    })

            elif itype in ("torznab", "newznab"):
                proto = "torrent" if itype == "torznab" else "usenet"
                if proto != protocol:
                    return []
                resp = await hc.get(
                    url,
                    params={"t": "search", "q": query, "apikey": api_key,
                            "limit": str(limit), "o": "json"},
                )
                if resp.status_code != 200:
                    return []
                ct = resp.headers.get("content-type", "")
                if "json" in ct:
                    data = resp.json()
                    raw = data.get("Results", data if isinstance(data, list) else [])
                    for item in raw:
                        dl = (item.get("Link") or item.get("link")
                              or item.get("MagnetUri") or "")
                        if not dl:
                            continue
                        results.append({
                            "title": item.get("Title") or item.get("title", ""),
                            "size": item.get("Size") or item.get("size", 0),
                            "seeders": item.get("Seeders") or item.get("seeders", 0),
                            "download_url": dl,
                            "indexer": iname,
                            "indexer_type": proto,
                        })
                else:
                    results.extend(_parse_torznab_xml(resp.text, iname, proto))

    except Exception as e:
        log.debug(f"search_indexers_auto error for {iname}: {e}")

    return results


async def search_indexers_auto(query: str, protocol: str, limit: int = 10) -> list:
    """
    Search enabled indexers for query in priority order, returning results of the given
    protocol ('torrent' or 'usenet'). Stops at the first indexer that returns any usable
    results — only falls through to the next indexer if the current one has nothing.
    Filters out blocklisted download URLs and non-music results.
    """
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM indexers WHERE enabled = 1 ORDER BY priority ASC"
        )
        indexers = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()

    blocklist = await _get_blocklist()

    for indexer in indexers:
        results = await _search_one_indexer(indexer, query, protocol, limit)

        # Filter blocklisted URLs and non-music results
        if blocklist:
            results = [r for r in results if r.get("download_url") not in blocklist]
        results = [r for r in results if _is_likely_music(r.get("title", ""))]

        if results:
            log.debug(
                f"search_indexers_auto: found {len(results)} {protocol} results "
                f"from '{indexer.get('name')}' (priority {indexer.get('priority', 0)})"
            )
            return results

        log.debug(
            f"search_indexers_auto: no {protocol} results from '{indexer.get('name')}', "
            f"trying next indexer"
        )

    return []


# ─── Soulseek auto-search-and-grab ────────────────────────────────────────────

def _is_audio(filename: str) -> bool:
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    return ext in _AUDIO_EXTS


def _folder_key(filename: str) -> str:
    parts = filename.replace("\\", "/").rstrip("/").split("/")
    return "/".join(parts[:-1]) if len(parts) > 1 else ""


async def search_soulseek(query: str) -> list:
    """Run a slskd search and return raw responses list. Returns [] on error."""
    row = await _get_client_row("slskd")
    if not row:
        return []
    url = _slskd_base(row)
    api_key = row.get("api_key", "")
    headers = {"X-API-Key": api_key} if api_key else {}

    try:
        async with httpx.AsyncClient(timeout=45) as hc:
            resp = await hc.post(f"{url}/api/v0/searches",
                                 json={"searchText": query}, headers=headers)
            if resp.status_code not in (200, 201):
                return []
            search_id = resp.json().get("id")
            for _ in range(10):
                await asyncio.sleep(2)
                r = await hc.get(f"{url}/api/v0/searches/{search_id}", headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    state = data.get("state", "")
                    if state.startswith("Completed") or state == "Finished":
                        # Responses are at a separate endpoint
                        rr = await hc.get(f"{url}/api/v0/searches/{search_id}/responses", headers=headers)
                        if rr.status_code == 200:
                            return rr.json() or []
                        return []
            return []
    except Exception as e:
        log.debug(f"search_soulseek error: {e}")
        return []


def group_soulseek_responses(responses: list) -> tuple[list, list]:
    """Group slskd responses into (album_folders, solo_files)."""
    folders: dict = {}
    for resp_item in (responses or [])[:60]:
        username = resp_item.get("username", "")
        folder_map: dict = {}
        for f in (resp_item.get("files", []) or []):
            fname = f.get("filename", "")
            if not _is_audio(fname):
                continue
            key = _folder_key(fname)
            folder_map.setdefault(key, []).append(f)
        for folder_path, flist in folder_map.items():
            fk = (username, folder_path)
            if fk not in folders:
                fname_last = (folder_path.replace("\\", "/").rstrip("/").split("/")[-1]
                              if folder_path else username)
                folders[fk] = {
                    "username": username,
                    "folder": folder_path,
                    "folder_name": fname_last,
                    "files": [],
                    "total_size": 0,
                    "formats": set(),
                }
            for f in flist:
                ext = (f.get("filename", "").rsplit(".", 1)[-1].upper()
                       if "." in f.get("filename", "") else "")
                folders[fk]["files"].append({
                    "filename": f.get("filename", ""),
                    "size": f.get("size", 0),
                    "bitrate": f.get("bitRate") or f.get("bitrate", 0),
                    "length": f.get("length", 0),
                })
                folders[fk]["total_size"] += f.get("size", 0)
                if ext:
                    folders[fk]["formats"].add(ext)

    album_folders, solo_files = [], []
    for fd in folders.values():
        fd["formats"] = sorted(fd["formats"])
        fd["file_count"] = len(fd["files"])
        if fd["file_count"] >= 2:
            album_folders.append(fd)
        else:
            solo_files.append({**fd["files"][0], "username": fd["username"]})
    album_folders.sort(key=lambda x: x["file_count"], reverse=True)
    return album_folders, solo_files


async def auto_grab_soulseek(
    title: str, artist: str, album: str,
    skip_keys: set | None = None,
) -> tuple[bool, str]:
    """
    Search Soulseek for a track, pick the best album folder, grab it.
    Respects slsk_album_download setting.
    Returns (grabbed: bool, source_key: str) where source_key is "username|folder"
    so callers can deduplicate across multiple tracks in the same dispatch run.
    skip_keys: set of "username|folder" strings already grabbed this run — skip if matched.
    """
    slsk_album = await get_setting("slsk_album_download", "1") == "1"
    track_query = f"{artist} {title}".strip() if artist else title
    album_query = f"{artist} {album}".strip() if album else None

    # Run searches in parallel if we have an album query
    if album_query and album_query.lower() != track_query.lower():
        track_resps, album_resps = await asyncio.gather(
            search_soulseek(track_query),
            search_soulseek(album_query),
        )
    else:
        track_resps = await search_soulseek(track_query)
        album_resps = []

    track_folders, track_solos = group_soulseek_responses(track_resps)
    album_folders, _ = group_soulseek_responses(album_resps)

    # Merge folders (album_folders first for dedup)
    seen = {(f["username"], f["folder"]) for f in album_folders}
    for f in track_folders:
        if (f["username"], f["folder"]) not in seen:
            album_folders.append(f)
            seen.add((f["username"], f["folder"]))

    if album_folders:
        best = album_folders[0]
        source_key = f"{best['username']}|{best['folder']}"

        # Skip if this folder was already grabbed in this dispatch run
        if skip_keys is not None and source_key in skip_keys:
            log.debug(f"auto_grab_soulseek: skipping duplicate folder {source_key}")
            return False, source_key

        if slsk_album:
            files = best["files"]
        else:
            # Grab only the best-matching track file
            title_lower = title.lower()
            best_file = best["files"][0]
            best_score = -1
            for f in best["files"]:
                fname = f["filename"].split("/")[-1].split("\\")[-1].lower()
                score = sum(1 for w in title_lower.split() if w and w in fname)
                if score > best_score:
                    best_score = score
                    best_file = f
            files = [best_file]
        grabbed = await grab_soulseek_files(best["username"], files)
        return grabbed, source_key

    # Fall back to solo file
    if track_solos:
        solo = track_solos[0]
        source_key = f"{solo['username']}|{solo['filename']}"
        if skip_keys is not None and source_key in skip_keys:
            return False, source_key
        grabbed = await grab_soulseek_files(
            solo["username"],
            [{"filename": solo["filename"], "size": solo["size"]}],
        )
        return grabbed, source_key

    return False, ""


# ─── YouTube auto-search-and-grab ─────────────────────────────────────────────

async def auto_grab_youtube(title: str, artist: str, duration_ms: int = 0) -> bool:
    """
    Search YouTube via yt-dlp for a track and submit best result to MeTube.
    Returns True if submitted.
    """
    mode = await get_setting("youtube_search_mode", "studio")
    suffix = "official audio" if mode == "studio" else "official music video"
    query = f"{artist} {title} {suffix}".strip() if artist else f"{title} {suffix}"

    try:
        import json as _j
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp", "--flat-playlist", "--dump-json", "--no-warnings",
            f"ytsearch5:{query}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=25)
        results = []
        for line in stdout.decode().strip().split("\n"):
            if not line.strip():
                continue
            try:
                item = _j.loads(line)
                results.append({
                    "url": f"https://www.youtube.com/watch?v={item.get('id', '')}",
                    "title": item.get("title", ""),
                    "duration": item.get("duration", 0),
                })
            except Exception:
                pass

        if not results:
            return False

        # Score: prefer results whose duration is close to the track duration
        best = results[0]
        if duration_ms > 0:
            target_s = duration_ms / 1000
            def _dur_score(r):
                d = r.get("duration") or 0
                return -abs(d - target_s) if d else -9999
            best = max(results, key=_dur_score)

        display_title = f"{artist} - {title}".strip(" -") if artist else title
        return await grab_youtube(best["url"], title=display_title)

    except Exception as e:
        log.debug(f"auto_grab_youtube error: {e}")
        return False
