"""
matcher.py — Local-first track matching using MusicBrainz + AcoustID.

No Spotify API calls. Pipeline:
  1. Local fuzzy match: compare tracks → monitored_tracks by normalized title+artist+duration
  2. MusicBrainz search: look up by artist+title to get canonical metadata (1 req/s, no key)
  3. AcoustID fingerprint: fpcalc → AcoustID → MusicBrainz recording (needs free API key)

All three methods feed into matching against monitored_tracks using the same local DB comparison.
"""

import asyncio
import json
import logging
import re
import subprocess
from typing import AsyncIterator

import httpx
from rapidfuzz import fuzz

from database import get_db, get_setting

log = logging.getLogger("jukeboxx.matcher")

MB_BASE = "https://musicbrainz.org/ws/2"
MB_HEADERS = {"User-Agent": "JukeBoxx/1.0 (https://github.com/jukeboxx)"}

# ── Normalization ──────────────────────────────────────────────────────────────

_FEAT    = re.compile(r'\s*[\(\[]?(?:feat\.?|ft\.?|featuring|with)\s+[^\)\]]*[\)\]]?', re.IGNORECASE)
_BRACKET = re.compile(r'\s*[\(\[][^\)\]]*[\)\]]')
_PUNCT   = re.compile(r"[^\w\s]")
_ARTICLES = re.compile(r'^(the|a|an)\s+', re.IGNORECASE)


def _norm(s: str) -> str:
    s = _FEAT.sub('', s or '')
    s = _BRACKET.sub('', s)
    s = _PUNCT.sub(' ', s)
    s = _ARTICLES.sub('', s)
    return ' '.join(s.lower().split())


# ── Version discrimination ─────────────────────────────────────────────────────
# Keywords with penalty values (0-55). Penalty applies when keyword is present
# in the LOCAL track's text but NOT in the Spotify track's text.
# This catches: screwed/chopped versions, live recordings, remixes, etc.
# matched against studio originals.

_VERSION_KEYWORDS: dict[str, int] = {
    # Live recordings
    'live': 35, 'concert': 30, 'in concert': 30, 'at the': 20,
    'unplugged': 25, 'mtv unplugged': 30, 'sessions': 15,
    # Chopped/screwed/slowed
    'screwed': 45, 'chopped': 45, 'screw': 40, 'screwed and chopped': 50,
    'slowed': 30, 'slowed down': 35, 'sped up': 25, 'reverb': 15,
    # Remixes
    'remix': 20, 'rmx': 20, 'remixed': 20, 'mashup': 25, 'refix': 20,
    'flip': 15, 'bootleg': 20, 'edit': 10,
    # Instrumentals / karaoke
    'instrumental': 40, 'karaoke': 55, 'backing track': 45, 'minus one': 40,
    # Covers / tributes
    'cover': 30, 'tribute': 35, 'as made famous': 35,
    # Demos / early versions
    'demo': 25, 'rough mix': 25, 'early version': 20, 'pre-production': 20,
    # Radio / promo edits
    'radio edit': 12, 'radio mix': 15, 'single version': 10, 'promo': 10,
    # Extended / club mixes
    'extended mix': 15, 'club mix': 15, 'dub mix': 15, 'dub': 10,
    # Skits / interludes
    'skit': 50, 'interlude': 30, 'intro': 15, 'outro': 15, 'reprise': 20,
    # Remasters that differ significantly from original
    'remaster': 5, 'remastered': 5,
}


def version_penalty(local_text: str, spotify_text: str) -> int:
    """Return score penalty (0-55) when local track has version tags not in Spotify.

    Example: local='V.I.C.E.S. (Screwed X Chopped by DJ Kirby)', spotify='V.I.C.E.S.'
    → penalty 50 (screwed + chopped keywords in local, not in Spotify)

    The penalty is subtracted from the fuzzy match score so wrong versions
    score lower than studio versions for the same Spotify track.
    """
    ll = local_text.lower()
    sl = spotify_text.lower()
    penalty = 0
    for kw, pen in _VERSION_KEYWORDS.items():
        if kw in ll and kw not in sl:
            penalty = max(penalty, pen)
    return min(penalty, 55)


def _score(lt, la, ld_s, mt_name, mt_artist, mt_dur_ms, local_album: str = "", spotify_album: str = "") -> int:
    nt1 = _norm(lt)
    na1 = _norm(la)
    nt2 = _norm(mt_name)
    na2 = _norm(mt_artist)

    title_score  = fuzz.token_sort_ratio(nt1, nt2)
    artist_score = fuzz.token_sort_ratio(na1, na2) if na1 and na2 else 40

    mt_dur_s = (mt_dur_ms or 0) / 1000
    if ld_s and mt_dur_s:
        delta = abs(ld_s - mt_dur_s)
        dur_score = max(0, 100 - int(delta * 12))
    else:
        dur_score = 50

    conf = int(title_score * 0.45 + artist_score * 0.35 + dur_score * 0.20)
    if ld_s and mt_dur_s and abs(ld_s - mt_dur_s) > 10:
        if title_score < 95 or artist_score < 95:
            conf = min(conf, 65)

    # Version penalty: prefer studio/original over live/remixed/chopped versions
    pen = version_penalty(
        f"{lt} {la} {local_album}",
        f"{mt_name} {mt_artist} {spotify_album}",
    )
    return max(0, conf - pen)


# ── Inverted index for fast matching ──────────────────────────────────────────

def _build_index(wanted: list[dict]) -> dict[str, list[dict]]:
    """Build a trigram-style inverted index: first 3 chars of norm title → list of wanted tracks."""
    idx: dict[str, list[dict]] = {}
    for mt in wanted:
        key = _norm(mt.get('name') or '')[:3]
        if key:
            idx.setdefault(key, []).append(mt)
    return idx


def _prenorm_wanted(wanted: list[dict]) -> list[dict]:
    """Pre-normalize wanted track fields so _score doesn't repeat regex work per comparison."""
    for mt in wanted:
        mt['_nt'] = _norm(mt.get('name') or '')
        mt['_na'] = _norm(mt.get('artist_name') or '')
        mt['_dur_s'] = (mt.get('duration_ms') or 0) / 1000
        mt['_album'] = (mt.get('album_name') or '').lower()
    return wanted


def _score_prenormed(lt: str, la: str, ld_s: float, nt1: str, na1: str, mt: dict) -> int:
    """Score against a pre-normalized wanted track. Avoids redundant _norm calls."""
    title_score  = fuzz.token_sort_ratio(nt1, mt['_nt'])
    artist_score = fuzz.token_sort_ratio(na1, mt['_na']) if na1 and mt['_na'] else 40
    mt_dur_s = mt['_dur_s']
    if ld_s and mt_dur_s:
        delta = abs(ld_s - mt_dur_s)
        dur_score = max(0, 100 - int(delta * 12))
    else:
        dur_score = 50
    conf = int(title_score * 0.45 + artist_score * 0.35 + dur_score * 0.20)
    if ld_s and mt_dur_s and abs(ld_s - mt_dur_s) > 10:
        if title_score < 95 or artist_score < 95:
            conf = min(conf, 65)
    return conf


def _compute_matches_batch(local_batch: list[dict], wanted: list[dict],
                            index: dict, threshold: int) -> list[tuple[int, str]]:
    """CPU-bound batch match using rapidfuzz bulk cdist — single C++ call per batch."""
    from rapidfuzz import process as rfprocess

    if not local_batch or not wanted:
        return []

    local_nt  = [_norm(t.get('title')  or '') for t in local_batch]
    local_na  = [_norm(t.get('artist') or '') for t in local_batch]
    local_dur = [float(t.get('duration') or 0) for t in local_batch]
    wanted_dur = [mt['_dur_s'] for mt in wanted]

    # Bulk pairwise similarity — returns list-of-lists when numpy is absent
    title_mat  = rfprocess.cdist(local_nt, [mt['_nt'] for mt in wanted], scorer=fuzz.token_sort_ratio)
    artist_mat = rfprocess.cdist(local_na, [mt['_na'] for mt in wanted], scorer=fuzz.token_sort_ratio)

    local_albums = [t.get('album') or '' for t in local_batch]

    matches = []
    for i, (ld, title_row, artist_row) in enumerate(zip(local_dur, title_mat, artist_mat)):
        if not local_nt[i]:
            continue
        local_combined = f"{local_batch[i].get('title') or ''} {local_batch[i].get('artist') or ''} {local_albums[i]}"
        best_score, best_wi = 0.0, -1
        for j, (ts, as_, wd) in enumerate(zip(title_row, artist_row, wanted_dur)):
            if ld > 0 and wd > 0:
                delta = abs(ld - wd)
                dur_s = max(0.0, 100.0 - delta * 12.0)
            else:
                dur_s = 50.0
            conf = ts * 0.45 + as_ * 0.35 + dur_s * 0.20
            if ld > 0 and wd > 0 and abs(ld - wd) > 10 and (ts < 95 or as_ < 95):
                conf = min(conf, 65.0)
            # Version penalty: local has live/remix/chopped tags that Spotify track doesn't
            spotify_combined = f"{wanted[j].get('name') or ''} {wanted[j].get('artist_name') or ''} {wanted[j].get('album_name') or ''}"
            pen = version_penalty(local_combined, spotify_combined)
            conf = max(0.0, conf - pen)
            if conf > best_score:
                best_score, best_wi = conf, j
        if best_wi >= 0 and best_score >= threshold:
            matches.append((local_batch[i]['id'], wanted[best_wi]['spotify_id'], int(best_score)))
    return matches


# ── Main matching function with SSE progress ───────────────────────────────────

async def match_local_to_monitored_stream(
    threshold: int = 85,
    chunk_size: int = 1000,
) -> AsyncIterator[dict]:
    """
    Match all unmatched local tracks against monitored_tracks.
    Yields progress dicts for SSE streaming.
    Returns total matched at end.
    """
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT spotify_id, name, artist_name, album_name, duration_ms
               FROM monitored_tracks WHERE status='wanted' AND monitored=1
               AND name IS NOT NULL AND name != ''"""
        )
        wanted = [dict(r) for r in await cur.fetchall()]

        cur = await db.execute(
            """SELECT COUNT(*) as cnt FROM tracks
               WHERE (spotify_id IS NULL OR spotify_id='')
               AND (mbid IS NULL OR mbid='')
               AND title IS NOT NULL AND title!=''"""
        )
        total = (await cur.fetchone())["cnt"] or 0
    finally:
        await db.close()

    if not wanted:
        yield {"status": "done", "matched": 0, "processed": 0, "total": 0, "message": "No wanted tracks to match against"}
        return

    yield {"status": "started", "total": total, "wanted_count": len(wanted), "processed": 0, "matched": 0}

    _prenorm_wanted(wanted)  # normalize once; reused by _compute_matches_batch via _nt/_na/_dur_s
    index = _build_index(wanted)
    wanted_set = {w['spotify_id'] for w in wanted}  # track which have been matched

    total_matched  = 0
    total_processed = 0
    offset = 0

    while True:
        db = await get_db()
        try:
            cur = await db.execute(
                """SELECT id, title, artist, album, duration FROM tracks
                   WHERE (spotify_id IS NULL OR spotify_id='')
                   AND (mbid IS NULL OR mbid='')
                   AND title IS NOT NULL AND title!=''
                   LIMIT ? OFFSET ?""",
                (chunk_size, offset)
            )
            batch = [dict(r) for r in await cur.fetchall()]
        finally:
            await db.close()

        if not batch:
            break

        # Run CPU-heavy matching in thread pool
        matched_pairs = await asyncio.to_thread(
            _compute_matches_batch, batch, wanted, index, threshold
        )

        # Apply matches to DB
        if matched_pairs:
            db = await get_db()
            try:
                for track_id, spotify_id, score in matched_pairs:
                    if spotify_id not in wanted_set:
                        continue  # already matched in a previous chunk
                    await db.execute(
                        "UPDATE tracks SET spotify_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND (spotify_id IS NULL OR spotify_id='')",
                        (spotify_id, track_id)
                    )
                    await db.execute(
                        "UPDATE monitored_tracks SET status='have', local_track_id=?, local_path=(SELECT path FROM tracks WHERE id=?), updated_at=CURRENT_TIMESTAMP WHERE spotify_id=? AND status='wanted'",
                        (track_id, track_id, spotify_id)
                    )
                    wanted_set.discard(spotify_id)
                    total_matched += 1
                await db.commit()
                # Roll up album completion for newly matched tracks
                try:
                    from tasks import _update_album_completion
                    for track_id, spotify_id, score in matched_pairs:
                        mt_cur = await db.execute(
                            "SELECT album_id FROM monitored_tracks WHERE spotify_id=?",
                            (spotify_id,)
                        )
                        mt_row = await mt_cur.fetchone()
                        if mt_row and mt_row["album_id"]:
                            await _update_album_completion(db, mt_row["album_id"])
                except Exception as _e:
                    pass  # non-fatal
            finally:
                await db.close()

        total_processed += len(batch)
        offset += len(batch)

        # Sample the last processed track for display
        last = batch[-1]
        current_label = f"{last.get('artist') or ''} — {last.get('title') or ''}".strip(" —")

        yield {
            "status": "progress",
            "processed": total_processed,
            "total":     total,
            "matched":   total_matched,
            "current":   current_label,
            "pct":       round(total_processed / max(total, 1) * 100),
        }

        await asyncio.sleep(0)  # yield to event loop

    yield {
        "status":    "done",
        "matched":   total_matched,
        "processed": total_processed,
        "total":     total,
        "message":   f"Matched {total_matched} of {total_processed} unmatched tracks",
    }


async def match_local_to_monitored(threshold: int = 85, batch_size: int = 1000) -> int:
    """Non-streaming version for use in background tasks."""
    matched = 0
    async for event in match_local_to_monitored_stream(threshold=threshold, chunk_size=batch_size):
        if event.get("status") == "done":
            matched = event.get("matched", 0)
    return matched


# ── MusicBrainz lookup (no API key, 1 req/s) ──────────────────────────────────

async def musicbrainz_search(title: str, artist: str = "") -> list[dict]:
    """
    Search MusicBrainz recordings by title+artist.
    Falls back to title-only if the combined search returns no confident results
    (handles dirty artist tags like 'Nirvana REMASTERS', 'Various Artists', etc.).
    """
    nt = _norm(title)
    na = _norm(artist) if artist else ""
    if not nt:
        return []

    def _parse_results(data: dict) -> list[dict]:
        out = []
        for rec in data.get("recordings", []):
            rec_artist = (rec.get("artist-credit") or [{}])[0].get("name", "") if rec.get("artist-credit") else ""
            out.append({
                "mbid":        rec.get("id", ""),
                "title":       rec.get("title", ""),
                "artist":      rec_artist,
                "duration_ms": rec.get("length"),
                "score":       int(rec.get("score", 0)),
            })
        return out

    try:
        async with httpx.AsyncClient(timeout=10, headers=MB_HEADERS) as client:
            # First attempt: title + artist
            if na:
                resp = await client.get(
                    f"{MB_BASE}/recording",
                    params={"query": f'recording:"{nt}" AND artist:"{na}"', "fmt": "json", "limit": 10}
                )
                if resp.status_code == 200:
                    results = _parse_results(resp.json())
                    # If we got at least one confident hit, return it
                    if results and results[0].get("score", 0) >= 80:
                        return results
                    # Otherwise fall through to title-only search
                # Rate limit: sleep is handled by the caller

            # Fallback (or no artist): title-only search
            resp = await client.get(
                f"{MB_BASE}/recording",
                params={"query": f'recording:"{nt}"', "fmt": "json", "limit": 10}
            )
            if resp.status_code != 200:
                return []
            return _parse_results(resp.json())
    except Exception:
        return []


# ── AcoustID fingerprinting ────────────────────────────────────────────────────

def _run_fpcalc(path: str, length: int = 120) -> tuple[str, int] | None:
    try:
        r = subprocess.run(
            ['fpcalc', '-length', str(length), '-json', path],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout)
        return data.get('fingerprint'), int(data.get('duration', 0))
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return None


async def lookup_acoustid(fingerprint: str, duration_s: int, api_key: str) -> list[dict]:
    if not fingerprint or not duration_s or not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.acoustid.org/v2/lookup",
                params={
                    "client": api_key,
                    "meta":   "recordings+releasegroups+compress",
                    "duration": str(duration_s),
                    "fingerprint": fingerprint,
                }
            )
            if resp.status_code != 200:
                return []
            results = []
            for match in resp.json().get("results", []):
                score = match.get("score", 0)
                for rec in match.get("recordings", []):
                    artists = rec.get("artists", [])
                    results.append({
                        "mbid":   rec.get("id", ""),
                        "title":  rec.get("title", ""),
                        "artist": artists[0].get("name", "") if artists else "",
                        "score":  score,
                    })
            return results
    except Exception:
        return []


async def _mb_fetch_artist_recordings(artist_name: str, limit: int = 100) -> list[dict]:
    """
    Fetch up to `limit` recordings from MusicBrainz for a given artist name.
    Searches by artist field; paginates if needed to cover the requested limit.
    One HTTP request per call — caller handles rate limiting.
    """
    na = _norm(artist_name)
    if not na:
        return []
    try:
        async with httpx.AsyncClient(timeout=10, headers=MB_HEADERS) as client:
            resp = await client.get(
                f"{MB_BASE}/recording",
                params={"query": f'artist:"{na}"', "fmt": "json", "limit": limit}
            )
            if resp.status_code != 200:
                return []
            out = []
            for rec in resp.json().get("recordings", []):
                ac = rec.get("artist-credit") or []
                rec_artist = ac[0].get("name", "") if ac else ""
                # Only keep recordings whose MB artist is reasonably close to our artist name
                if rec_artist and fuzz.token_sort_ratio(_norm(rec_artist), na) < 60:
                    continue
                out.append({
                    "mbid":        rec.get("id", ""),
                    "title":       rec.get("title", ""),
                    "artist":      rec_artist,
                    "duration_ms": rec.get("length"),
                    "score":       int(rec.get("score", 0)),
                })
            return out
    except Exception:
        return []


def _best_mb_match(local_track: dict, mb_recordings: list[dict],
                   check_artist: bool = True) -> tuple[int, str | None]:
    """
    Find best MBID match for a local track against a list of MB recordings.

    When check_artist=False (recordings already filtered to correct artist),
    the artist is confirmed — score on title+duration only.
    When duration is unknown for either side, fall back to title-only scoring.

    Returns (confidence 0-100, mbid or None).
    """
    lt = local_track.get("title") or ""
    la = local_track.get("artist") or ""
    ld_s = float(local_track.get("duration") or 0)
    nt1 = _norm(lt)
    na1 = _norm(la)

    best_score = 0
    best_mbid = None

    for cand in mb_recordings:
        nt2 = _norm(cand.get("title") or "")
        title_score = fuzz.token_sort_ratio(nt1, nt2)
        if title_score < 55:
            continue  # fast skip — clearly different song

        cand_dur_s = (cand.get("duration_ms") or 0) / 1000
        dur_known = ld_s > 0 and cand_dur_s > 0

        if dur_known:
            delta = abs(ld_s - cand_dur_s)
            dur_score = max(0, 100 - int(delta * 12))
        else:
            dur_score = None  # unknown — don't penalise

        if check_artist:
            na2 = _norm(cand.get("artist") or "")
            if na1 and na2:
                # Take the best of token_sort and partial — handles "Nirvana REMASTERS" vs "Nirvana"
                artist_score = max(
                    fuzz.token_sort_ratio(na1, na2),
                    fuzz.partial_ratio(na1, na2),
                    fuzz.partial_ratio(na2, na1),
                )
            else:
                artist_score = 40
            if dur_known:
                conf = int(title_score * 0.45 + artist_score * 0.35 + dur_score * 0.20)
                if delta > 10 and (title_score < 95 or artist_score < 95):
                    conf = min(conf, 65)
            else:
                # No duration info — use title+artist only
                conf = int(title_score * 0.55 + artist_score * 0.45)
        else:
            # Artist already confirmed — title is the primary discriminator
            if dur_known:
                conf = int(title_score * 0.65 + dur_score * 0.35)
                if delta > 10 and title_score < 95:
                    conf = min(conf, 65)
            else:
                # No duration info — just use title score
                conf = title_score

        if conf > best_score:
            best_score = conf
            best_mbid = cand["mbid"]

    return best_score, best_mbid


_GENERIC_ARTISTS = frozenset({"various artists", "various", "va", "unknown", "unknown artist", ""})


async def identify_via_mb_stream(threshold: int = 75) -> AsyncIterator[dict]:
    """
    Identify unrecognised local tracks via MusicBrainz, one track at a time.

    Searches MB for each track by title+artist — this is the most accurate approach
    (89%+ hit rate in practice). Rate-limited to ~2 req/s to stay within MB policy.
    Runs as a background job; progress is polled by the frontend.
    """
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT COUNT(*) as cnt FROM tracks
               WHERE (spotify_id IS NULL OR spotify_id='')
               AND (mbid IS NULL OR mbid='')
               AND title IS NOT NULL AND title!=''"""
        )
        total = (await cur.fetchone())["cnt"] or 0
    finally:
        await db.close()

    if total == 0:
        yield {"status": "done", "identified": 0, "processed": 0, "total": 0,
               "message": "No unidentified tracks to process"}
        return

    yield {"status": "started", "total": total, "processed": 0, "identified": 0}

    identified = 0
    processed = 0

    while True:
        # Always fetch from offset 0 — identified tracks drop out of the WHERE clause
        db = await get_db()
        try:
            cur = await db.execute(
                """SELECT id, title, artist, duration FROM tracks
                   WHERE (spotify_id IS NULL OR spotify_id='')
                   AND (mbid IS NULL OR mbid='')
                   AND title IS NOT NULL AND title!=''
                   LIMIT 50"""
            )
            batch = [dict(r) for r in await cur.fetchall()]
        finally:
            await db.close()

        if not batch:
            break

        for t in batch:
            candidates = await musicbrainz_search(t["title"], t.get("artist") or "")
            await asyncio.sleep(0.5)  # ~2 req/s — MB allows this for well-behaved clients

            local_artist = _norm(t.get("artist") or "")
            # For "Various Artists", empty, or clearly generic tags: skip artist check
            # (we'll rely on title + duration instead)
            check_artist = local_artist not in _GENERIC_ARTISTS
            score, mbid = _best_mb_match(t, candidates, check_artist=check_artist)

            if score >= threshold and mbid:
                db = await get_db()
                try:
                    await db.execute(
                        "UPDATE tracks SET mbid=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND (mbid IS NULL OR mbid='')",
                        (mbid, t["id"])
                    )
                    await db.commit()
                    identified += 1
                finally:
                    await db.close()

            processed += 1
            yield {
                "status":     "progress",
                "processed":  processed,
                "total":      total,
                "identified": identified,
                "current":    f"{t.get('artist') or ''} — {t.get('title') or ''}".strip(" —"),
                "pct":        round(processed / max(total, 1) * 100),
            }

    yield {
        "status":     "done",
        "processed":  processed,
        "total":      total,
        "identified": identified,
        "message":    f"Identified {identified} of {processed} tracks via MusicBrainz",
    }


async def run_acoustid_batch(batch_size: int = 20) -> int:
    """Fingerprint unmatched tracks, identify via AcoustID, match against monitored_tracks."""
    api_key   = await get_setting("acoustid_api_key", "")
    threshold = int(await get_setting("fuzzy_threshold", "85"))
    if not api_key:
        return 0

    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT id, path, title, artist, duration FROM tracks
               WHERE (spotify_id IS NULL OR spotify_id='')
               AND (acoustid_fingerprint IS NULL OR acoustid_fingerprint='')
               AND title IS NOT NULL LIMIT ?""",
            (batch_size,)
        )
        tracks = [dict(r) for r in await cur.fetchall()]
        cur = await db.execute(
            "SELECT spotify_id, name, artist_name, duration_ms FROM monitored_tracks WHERE status='wanted' AND monitored=1"
        )
        wanted = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()

    if not tracks or not wanted:
        return 0

    matched = 0
    index   = _build_index(wanted)

    for t in tracks:
        fp_result = await asyncio.to_thread(_run_fpcalc, t["path"])
        if not fp_result:
            continue
        fp, dur_s = fp_result

        db2 = await get_db()
        try:
            await db2.execute("UPDATE tracks SET acoustid_fingerprint=? WHERE id=?", (fp, t["id"]))
            await db2.commit()
        finally:
            await db2.close()

        candidates = await lookup_acoustid(fp, dur_s or t.get("duration", 0), api_key)
        best_score, best_sid = 0, None
        for cand in candidates:
            if cand["score"] < 0.5:
                continue
            for mt in index.get(_norm(cand.get("title", ""))[:3], wanted):
                s = _score(cand["title"], cand["artist"], dur_s, mt["name"], mt["artist_name"], mt["duration_ms"])
                if s > best_score:
                    best_score, best_sid = s, mt["spotify_id"]

        if best_score >= threshold and best_sid:
            db3 = await get_db()
            try:
                await db3.execute(
                    "UPDATE tracks SET spotify_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (best_sid, t["id"])
                )
                await db3.execute(
                    "UPDATE monitored_tracks SET status='have', local_track_id=?, updated_at=CURRENT_TIMESTAMP WHERE spotify_id=? AND status='wanted'",
                    (t["id"], best_sid)
                )
                await db3.commit()
                matched += 1
            finally:
                await db3.close()

        await asyncio.sleep(0.34)  # ~3 req/s AcoustID limit

    if matched:
        log.info(f"AcoustID matcher: {matched} new matches")
    return matched
