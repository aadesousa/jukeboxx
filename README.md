# jukeboxx

A self-hosted music library manager with Spotify integration and multi-source automatic downloading. Monitors your Spotify library (artists, albums, playlists) and automatically acquires music through torrents, Usenet, Soulseek, YouTube, or Spotizerr — whichever finds it first.

Heavily inspired by Lidarr's architecture but with track-level monitoring and Spotify as the source of truth.

![Screenshot placeholder](https://via.placeholder.com/900x500?text=jukeboxx)

---

## Features

- **Spotify-first** — connect your Spotify account and monitor artists, albums, liked songs, saved albums, or playlists
- **Multi-source dispatch** — tries download sources in configurable priority order: torrent → Usenet → Soulseek → YouTube → Spotizerr
- **Track-level monitoring** — tracks individual song status (wanted / downloading / have), not just albums
- **Soulseek album dedup** — when grabbing one track from an album via Soulseek, pre-marks all sibling tracks to avoid duplicate folder downloads
- **Automatic library scanning** — watches your music folder, reads tags, matches files back to Spotify IDs
- **Playlist sync** — syncs Spotify and SoundCloud playlists to M3U files, optionally pushed to Jellyfin
- **Quality profiles** — score and filter search results by format, bitrate, and custom word lists
- **Activity monitoring** — live view of active downloads across all clients (qBittorrent, SABnzbd, Soulseek, YouTube)
- **Scheduler** — automatic periodic dispatch, sync, and library scanning
- **Discord notifications** — dispatch results, new releases, download completions
- **Single-page frontend** — vanilla JS, no build step required

---

## Stack

| Component | Role |
|---|---|
| FastAPI (Python) | Backend API |
| aiosqlite | Database |
| Vanilla JS | Frontend |
| nginx | Frontend serving |
| MeTube | YouTube downloads |
| qBittorrent | Torrent client |
| SABnzbd | Usenet client |
| slskd | Soulseek client |
| Prowlarr | Torrent/NZB indexer aggregation |
| Spotizerr *(optional)* | Direct Spotify source |

---

## Quick Start

### 1. Create a Spotify app

Go to [developer.spotify.com](https://developer.spotify.com/dashboard) → Create App → set the redirect URI to:
```
http://<your-server-ip>:6160/api/spotify/callback
```

### 2. Configure environment

Create a `.env` file in the project root:

```env
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
JWT_SECRET=some-long-random-string
```

### 3. Edit `docker-compose.yml`

Update these values for your setup:

```yaml
environment:
  - MUSIC_PATH=/music                          # path inside container
  - SPOTIFY_REDIRECT_URI=http://<ip>:6160/api/spotify/callback
  - SPOTIZERR_URL=http://<spotizerr-host>:7171 # optional
  - JELLYFIN_PATH_PREFIX=/your/music/path      # optional, for M3U compatibility
  - TZ=America/New_York

volumes:
  - /your/music/library:/music                 # your actual music folder
```

### 4. Start

```bash
docker compose up -d
```

Open `http://<your-server-ip>:6160` in your browser.

---

## Configuration

All settings are managed through the **Settings** page in the UI. Key areas:

- **Spotify** — connect/disconnect your account, view rate limit status
- **Download Clients** — add qBittorrent, SABnzbd, slskd, MeTube, Spotizerr instances with connection testing
- **Indexers** — add Prowlarr and individual indexers with priority ordering
- **Quality Profiles** — define preferred formats, minimum bitrate, and word filters (ignored/required/preferred)
- **Media Management** — library path, monitoring behavior
- **Notifications** — Discord webhook

---

## Download Source Priority

Sources are tried in the order you configure under Settings → Media Management. Default: `torrent → usenet → soulseek → youtube`.

For each wanted track, jukeboxx:
1. Searches the first source
2. Scores results by format quality and seeders
3. Grabs the best result if one passes the quality profile filter
4. If the grab fails or returns no usable results, moves to the next source
5. Marks the track as `downloading` and records it in the unified download queue

---

## Development

### Prerequisites

- Docker
- Python 3.12+ (for running tests locally)

### Running tests

Tests run against the container:

```bash
docker exec jukeboxx-backend python3 -m pytest tests/ -q
```

Or run locally (requires backend deps):

```bash
cd backend
pip install -r requirements.txt
pytest ../tests/ -q
```

### Project structure

```
backend/        FastAPI app, all business logic
frontend/       Vanilla JS single-page app, served by nginx
tests/          pytest test suite
data/           SQLite database (runtime, gitignored)
scripts/        Utility scripts
docker-compose.yml
```

---

## Notes

- **No build step** — the frontend is plain HTML/CSS/JS. Edit files and reload.
- **Database** — single SQLite file at `data/jukeboxx.db`. Back it up before upgrades.
- **Jellyfin** — set `JELLYFIN_PATH_PREFIX` to the path Jellyfin uses for your music folder if it differs from the host path. This ensures M3U playlists have correct file paths.
- **SoundCloud** — paste a SoundCloud profile URL under the SoundCloud page to import and sync playlists.
