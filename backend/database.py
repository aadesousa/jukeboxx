import aiosqlite
import os
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "/app/data/jukeboxx.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    sha256 TEXT,
    artist TEXT, album_artist TEXT, title TEXT, album TEXT,
    track_number INTEGER, disc_number INTEGER, year INTEGER, genre TEXT,
    format TEXT, bitrate INTEGER, duration INTEGER, size INTEGER,
    mtime REAL,
    spotify_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS spotify_auth (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    access_token TEXT, refresh_token TEXT, token_type TEXT DEFAULT 'Bearer',
    expires_at INTEGER, scope TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sync_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id TEXT NOT NULL UNIQUE,
    item_type TEXT NOT NULL,
    name TEXT, last_synced_at TIMESTAMP,
    track_count INTEGER DEFAULT 0, local_count INTEGER DEFAULT 0,
    unavailable_count INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id TEXT NOT NULL, title TEXT, artist TEXT, album TEXT,
    item_type TEXT,
    status TEXT DEFAULT 'pending',
    error_message TEXT, spotizerr_task_id TEXT,
    source TEXT DEFAULT 'manual',
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS duplicate_pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_a_id INTEGER REFERENCES tracks(id) ON DELETE CASCADE,
    track_b_id INTEGER REFERENCES tracks(id) ON DELETE CASCADE,
    match_type TEXT NOT NULL,
    similarity_score REAL, status TEXT DEFAULT 'pending',
    resolution TEXT, resolved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(track_a_id, track_b_id)
);

CREATE TABLE IF NOT EXISTS scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP, completed_at TIMESTAMP,
    tracks_found INTEGER DEFAULT 0, tracks_added INTEGER DEFAULT 0,
    tracks_updated INTEGER DEFAULT 0, tracks_removed INTEGER DEFAULT 0,
    duplicates_found INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running', error_message TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auth (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT,
    read INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    detail TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS spotify_cache (
    cache_key TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    fetched_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS wanted_artists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    image_url TEXT,
    genres TEXT,
    monitor_new_albums INTEGER DEFAULT 1,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS wanted_albums (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id TEXT NOT NULL UNIQUE,
    artist_spotify_id TEXT NOT NULL,
    name TEXT NOT NULL,
    album_type TEXT,
    release_date TEXT,
    track_count INTEGER DEFAULT 0,
    image_url TEXT,
    status TEXT DEFAULT 'wanted',
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (artist_spotify_id) REFERENCES wanted_artists(spotify_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS match_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER REFERENCES tracks(id) ON DELETE CASCADE,
    spotify_id TEXT,
    match_score REAL,
    score_breakdown TEXT,
    status TEXT DEFAULT 'pending',
    resolved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS youtube_downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    title TEXT,
    status TEXT DEFAULT 'pending',
    metube_id TEXT,
    output_path TEXT,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS youtube_review_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitored_track_id INTEGER NOT NULL UNIQUE,
    video_id TEXT NOT NULL,
    video_url TEXT NOT NULL,
    video_title TEXT,
    video_channel TEXT,
    video_duration_s INTEGER DEFAULT 0,
    score REAL DEFAULT 0,
    artist TEXT,
    title TEXT,
    reviewed INTEGER DEFAULT 0,
    accepted INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS quality_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    preferred_format TEXT DEFAULT 'any',
    min_bitrate INTEGER DEFAULT 0,
    upgrade_allowed INTEGER DEFAULT 1,
    is_default INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS monitored_artists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    image_url TEXT,
    fanart_url TEXT,
    genres TEXT DEFAULT '[]',
    followers INTEGER DEFAULT 0,
    popularity INTEGER DEFAULT 0,
    monitored INTEGER DEFAULT 1,
    monitor_new_releases INTEGER DEFAULT 1,
    quality_profile_id INTEGER REFERENCES quality_profiles(id),
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS monitored_albums (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id TEXT NOT NULL UNIQUE,
    artist_id INTEGER REFERENCES monitored_artists(id) ON DELETE CASCADE,
    artist_spotify_id TEXT NOT NULL,
    name TEXT NOT NULL,
    album_type TEXT DEFAULT 'album',
    release_date TEXT,
    release_date_precision TEXT,
    track_count INTEGER DEFAULT 0,
    image_url TEXT,
    label TEXT,
    status TEXT DEFAULT 'wanted',
    monitored INTEGER DEFAULT 1,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS monitored_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id TEXT NOT NULL UNIQUE,
    album_id INTEGER REFERENCES monitored_albums(id) ON DELETE SET NULL,
    artist_id INTEGER REFERENCES monitored_artists(id) ON DELETE SET NULL,
    album_spotify_id TEXT,
    artist_spotify_id TEXT,
    name TEXT NOT NULL,
    artist_name TEXT,
    album_name TEXT,
    track_number INTEGER,
    disc_number INTEGER DEFAULT 1,
    duration_ms INTEGER,
    image_url TEXT,
    monitored INTEGER DEFAULT 1,
    status TEXT DEFAULT 'wanted',
    local_path TEXT,
    local_track_id INTEGER REFERENCES tracks(id) ON DELETE SET NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS unified_downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id TEXT,
    item_type TEXT NOT NULL,
    title TEXT NOT NULL,
    artist TEXT,
    album TEXT,
    image_url TEXT,
    status TEXT DEFAULT 'queued',
    source TEXT DEFAULT 'spotizerr',
    source_url TEXT,
    quality_profile TEXT,
    file_path TEXT,
    error_message TEXT,
    spotizerr_task_id TEXT,
    metube_job_id TEXT,
    retry_count INTEGER DEFAULT 0,
    monitored_track_id INTEGER REFERENCES monitored_tracks(id) ON DELETE SET NULL,
    monitored_album_id INTEGER REFERENCES monitored_albums(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS release_calendar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artist_id INTEGER REFERENCES monitored_artists(id) ON DELETE CASCADE,
    album_id INTEGER REFERENCES monitored_albums(id) ON DELETE CASCADE,
    release_date TEXT NOT NULL,
    notified INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tracks_spotify_id ON tracks(spotify_id);
CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read);
CREATE INDEX IF NOT EXISTS idx_activity_log_created ON activity_log(created_at);
CREATE INDEX IF NOT EXISTS idx_tracks_artist_title ON tracks(artist, title);
CREATE INDEX IF NOT EXISTS idx_tracks_sha256 ON tracks(sha256);
CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status);
CREATE INDEX IF NOT EXISTS idx_downloads_spotify_id ON downloads(spotify_id);
CREATE INDEX IF NOT EXISTS idx_sync_items_enabled ON sync_items(enabled);
CREATE INDEX IF NOT EXISTS idx_duplicate_pairs_status ON duplicate_pairs(status);
CREATE INDEX IF NOT EXISTS idx_monitored_artists_spotify ON monitored_artists(spotify_id);
CREATE INDEX IF NOT EXISTS idx_monitored_albums_artist ON monitored_albums(artist_id);
CREATE INDEX IF NOT EXISTS idx_monitored_albums_spotify ON monitored_albums(spotify_id);
CREATE INDEX IF NOT EXISTS idx_monitored_tracks_album ON monitored_tracks(album_id);
CREATE INDEX IF NOT EXISTS idx_monitored_tracks_spotify ON monitored_tracks(spotify_id);
CREATE INDEX IF NOT EXISTS idx_unified_downloads_status ON unified_downloads(status);
CREATE INDEX IF NOT EXISTS idx_release_calendar_date ON release_calendar(release_date);

CREATE TABLE IF NOT EXISTS download_clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    priority INTEGER DEFAULT 0,
    host TEXT DEFAULT '',
    port INTEGER DEFAULT 0,
    username TEXT DEFAULT '',
    password TEXT DEFAULT '',
    url_base TEXT DEFAULT '',
    api_key TEXT DEFAULT '',
    use_ssl INTEGER DEFAULT 0,
    extra_config TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS indexers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    priority INTEGER DEFAULT 0,
    url TEXT DEFAULT '',
    api_key TEXT DEFAULT '',
    categories TEXT DEFAULT '[]',
    extra_config TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS download_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    artist TEXT,
    album TEXT,
    source_url TEXT,
    client_type TEXT,
    client_id INTEGER REFERENCES download_clients(id) ON DELETE SET NULL,
    quality TEXT,
    file_path TEXT,
    file_size INTEGER DEFAULT 0,
    status TEXT DEFAULT 'completed',
    error_message TEXT,
    monitored_track_id INTEGER REFERENCES monitored_tracks(id) ON DELETE SET NULL,
    monitored_album_id INTEGER REFERENCES monitored_albums(id) ON DELETE SET NULL,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_download_clients_priority ON download_clients(priority);
CREATE INDEX IF NOT EXISTS idx_indexers_priority ON indexers(priority);
CREATE INDEX IF NOT EXISTS idx_download_history_imported ON download_history(imported_at);

CREATE TABLE IF NOT EXISTS metadata_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    include_albums INTEGER DEFAULT 1,
    include_singles INTEGER DEFAULT 0,
    include_eps INTEGER DEFAULT 1,
    include_compilations INTEGER DEFAULT 0,
    include_live INTEGER DEFAULT 0,
    is_default INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS release_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    required_words TEXT DEFAULT '',
    ignored_words TEXT DEFAULT '',
    preferred_words TEXT DEFAULT '',
    score_boost INTEGER DEFAULT 0,
    is_default INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

DEFAULT_SETTINGS = {
    "sync_interval_minutes": "360",
    "fuzzy_threshold": "85",
    "m3u_path_prefix": "/mnt/storage/MUSIC",
    "scan_interval_hours": "6",
    "max_retries": "3",
    "account_sync_enabled": "0",
    "music_path": "/music",
    "library_ready": "0",
    "spotify_cache_ttl_hours": "24",
    "spotizerr_concurrent_limit": "20",
    "dispatch_batch_size": "10",
    "stale_hours": "2",
    "metube_url": "http://metube:8081",
    "youtube_audio_format": "mp3",
    "youtube_audio_quality": "0",
    "match_review_threshold": "75",
    "monitor_new_releases": "1",
    "slsk_album_download": "1",
    "download_source_priority": '["torrent","usenet","soulseek","youtube","spotizerr"]',
    "youtube_search_mode": "studio",
    "discord_webhook_url": "",
    "discord_notify_download_complete": "1",
    "discord_notify_new_release": "1",
    "discord_notify_dispatch": "0",
    "queue_paused": "0",
    "jukeboxx_api_key": "",
    "torrent_save_path": "",
    "torrent_hardlink_enabled": "0",
    "torrent_hardlinked_hashes": "[]",
    "calendar_enabled": "0",
}


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = await get_db()
    try:
        await db.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        # Migration: add mtime column if missing (existing DBs)
        cur = await db.execute("PRAGMA table_info(tracks)")
        columns = {row[1] for row in await cur.fetchall()}
        if "mtime" not in columns:
            await db.execute("ALTER TABLE tracks ADD COLUMN mtime REAL")
        if "mbid" not in columns:
            await db.execute("ALTER TABLE tracks ADD COLUMN mbid TEXT")
        if "isrc" not in columns:
            await db.execute("ALTER TABLE tracks ADD COLUMN isrc TEXT")
        if "acoustid_fingerprint" not in columns:
            await db.execute("ALTER TABLE tracks ADD COLUMN acoustid_fingerprint TEXT")
        if "acoustid_id" not in columns:
            await db.execute("ALTER TABLE tracks ADD COLUMN acoustid_id TEXT")
        # Migration: add unavailable_count column to sync_items
        cur = await db.execute("PRAGMA table_info(sync_items)")
        si_cols = {row[1] for row in await cur.fetchall()}
        if "unavailable_count" not in si_cols:
            await db.execute("ALTER TABLE sync_items ADD COLUMN unavailable_count INTEGER DEFAULT 0")
        # Migration: create spotify_cache table if missing
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS spotify_cache (
                cache_key TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                fetched_at TIMESTAMP NOT NULL
            );
        """)
        # Migration: create notifications/activity_log tables if missing
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL, title TEXT NOT NULL, message TEXT,
                read INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL, detail TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read);
            CREATE INDEX IF NOT EXISTS idx_activity_log_created ON activity_log(created_at);
        """)
        # Migration: add index for cooling status if not exists
        await db.executescript("""
            CREATE INDEX IF NOT EXISTS idx_downloads_status_updated ON downloads(status, updated_at);
        """)
        # Migration: Phase 2 — monitored_artists/albums/tracks, quality_profiles, unified_downloads
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS quality_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                preferred_format TEXT DEFAULT 'any',
                min_bitrate INTEGER DEFAULT 0,
                upgrade_allowed INTEGER DEFAULT 1,
                is_default INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS monitored_artists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spotify_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                image_url TEXT,
                fanart_url TEXT,
                genres TEXT DEFAULT '[]',
                followers INTEGER DEFAULT 0,
                popularity INTEGER DEFAULT 0,
                monitored INTEGER DEFAULT 1,
                monitor_new_releases INTEGER DEFAULT 1,
                quality_profile_id INTEGER REFERENCES quality_profiles(id),
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS monitored_albums (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spotify_id TEXT NOT NULL UNIQUE,
                artist_id INTEGER REFERENCES monitored_artists(id) ON DELETE CASCADE,
                artist_spotify_id TEXT NOT NULL,
                name TEXT NOT NULL,
                album_type TEXT DEFAULT 'album',
                release_date TEXT,
                release_date_precision TEXT,
                track_count INTEGER DEFAULT 0,
                image_url TEXT,
                label TEXT,
                status TEXT DEFAULT 'wanted',
                monitored INTEGER DEFAULT 1,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS monitored_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spotify_id TEXT NOT NULL UNIQUE,
                album_id INTEGER REFERENCES monitored_albums(id) ON DELETE SET NULL,
                artist_id INTEGER REFERENCES monitored_artists(id) ON DELETE SET NULL,
                album_spotify_id TEXT,
                artist_spotify_id TEXT,
                name TEXT NOT NULL,
                artist_name TEXT,
                album_name TEXT,
                track_number INTEGER,
                disc_number INTEGER DEFAULT 1,
                duration_ms INTEGER,
                image_url TEXT,
                monitored INTEGER DEFAULT 1,
                status TEXT DEFAULT 'wanted',
                local_path TEXT,
                local_track_id INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS unified_downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spotify_id TEXT,
                item_type TEXT NOT NULL,
                title TEXT NOT NULL,
                artist TEXT,
                album TEXT,
                image_url TEXT,
                status TEXT DEFAULT 'queued',
                source TEXT DEFAULT 'spotizerr',
                source_url TEXT,
                quality_profile TEXT,
                file_path TEXT,
                error_message TEXT,
                spotizerr_task_id TEXT,
                metube_job_id TEXT,
                retry_count INTEGER DEFAULT 0,
                monitored_track_id INTEGER,
                monitored_album_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS release_calendar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist_id INTEGER,
                album_id INTEGER,
                release_date TEXT NOT NULL,
                notified INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_monitored_artists_spotify ON monitored_artists(spotify_id);
            CREATE INDEX IF NOT EXISTS idx_monitored_albums_artist ON monitored_albums(artist_id);
            CREATE INDEX IF NOT EXISTS idx_monitored_albums_spotify ON monitored_albums(spotify_id);
            CREATE INDEX IF NOT EXISTS idx_monitored_tracks_album ON monitored_tracks(album_id);
            CREATE INDEX IF NOT EXISTS idx_monitored_tracks_spotify ON monitored_tracks(spotify_id);
            CREATE INDEX IF NOT EXISTS idx_unified_downloads_status ON unified_downloads(status);
            CREATE INDEX IF NOT EXISTS idx_release_calendar_date ON release_calendar(release_date);
        """)
        # Seed default quality profiles if not present
        await db.execute("""
            INSERT OR IGNORE INTO quality_profiles (name, preferred_format, min_bitrate, upgrade_allowed, is_default)
            VALUES ('Any', 'any', 0, 1, 1)
        """)
        await db.execute("""
            INSERT OR IGNORE INTO quality_profiles (name, preferred_format, min_bitrate, upgrade_allowed, is_default)
            VALUES ('Lossless (FLAC)', 'flac', 0, 1, 0)
        """)
        await db.execute("""
            INSERT OR IGNORE INTO quality_profiles (name, preferred_format, min_bitrate, upgrade_allowed, is_default)
            VALUES ('High (MP3 320)', 'mp3_320', 320, 0, 0)
        """)

        # Migration: wanted system tables
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS wanted_artists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spotify_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                image_url TEXT,
                genres TEXT,
                monitor_new_albums INTEGER DEFAULT 1,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS wanted_albums (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spotify_id TEXT NOT NULL UNIQUE,
                artist_spotify_id TEXT NOT NULL,
                name TEXT NOT NULL,
                album_type TEXT,
                release_date TEXT,
                track_count INTEGER DEFAULT 0,
                image_url TEXT,
                status TEXT DEFAULT 'wanted',
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS match_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id INTEGER,
                spotify_id TEXT,
                match_score REAL,
                score_breakdown TEXT,
                status TEXT DEFAULT 'pending',
                resolved_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS youtube_downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT,
                status TEXT DEFAULT 'pending',
                metube_id TEXT,
                output_path TEXT,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS youtube_review_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                monitored_track_id INTEGER NOT NULL UNIQUE,
                video_id TEXT NOT NULL,
                video_url TEXT NOT NULL,
                video_title TEXT,
                video_channel TEXT,
                video_duration_s INTEGER DEFAULT 0,
                score REAL DEFAULT 0,
                artist TEXT,
                title TEXT,
                reviewed INTEGER DEFAULT 0,
                accepted INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Migration: download_clients, indexers, download_history
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS download_clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                priority INTEGER DEFAULT 0,
                host TEXT DEFAULT '',
                port INTEGER DEFAULT 0,
                username TEXT DEFAULT '',
                password TEXT DEFAULT '',
                url_base TEXT DEFAULT '',
                api_key TEXT DEFAULT '',
                use_ssl INTEGER DEFAULT 0,
                extra_config TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS indexers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                priority INTEGER DEFAULT 0,
                url TEXT DEFAULT '',
                api_key TEXT DEFAULT '',
                categories TEXT DEFAULT '[]',
                extra_config TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS download_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                artist TEXT,
                album TEXT,
                source_url TEXT,
                client_type TEXT,
                client_id INTEGER,
                quality TEXT,
                file_path TEXT,
                file_size INTEGER DEFAULT 0,
                status TEXT DEFAULT 'completed',
                error_message TEXT,
                monitored_track_id INTEGER,
                monitored_album_id INTEGER,
                imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_download_clients_priority ON download_clients(priority);
            CREATE INDEX IF NOT EXISTS idx_indexers_priority ON indexers(priority);
            CREATE INDEX IF NOT EXISTS idx_download_history_imported ON download_history(imported_at);
        """)
        # Migration: metadata_profiles table
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                include_albums INTEGER DEFAULT 1,
                include_singles INTEGER DEFAULT 0,
                include_eps INTEGER DEFAULT 1,
                include_compilations INTEGER DEFAULT 0,
                include_live INTEGER DEFAULT 0,
                is_default INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_metadata_profiles_default ON metadata_profiles(is_default);
        """)
        # Seed default metadata profiles
        await db.execute("""
            INSERT OR IGNORE INTO metadata_profiles (name, include_albums, include_singles, include_eps, include_compilations, include_live, is_default)
            VALUES ('Standard', 1, 0, 1, 0, 0, 1)
        """)
        await db.execute("""
            INSERT OR IGNORE INTO metadata_profiles (name, include_albums, include_singles, include_eps, include_compilations, include_live, is_default)
            VALUES ('All', 1, 1, 1, 1, 1, 0)
        """)
        await db.execute("""
            INSERT OR IGNORE INTO metadata_profiles (name, include_albums, include_singles, include_eps, include_compilations, include_live, is_default)
            VALUES ('Albums Only', 1, 0, 0, 0, 0, 0)
        """)
        # Migration: add mbid column to tracks if missing
        cur = await db.execute("PRAGMA table_info(tracks)")
        tracks_cols = {row[1] for row in await cur.fetchall()}
        if "mbid" not in tracks_cols:
            try:
                await db.execute("ALTER TABLE tracks ADD COLUMN mbid TEXT")
                await db.commit()
            except Exception:
                pass
        # Migration: add metadata_profile_id to monitored_artists if missing
        cur = await db.execute("PRAGMA table_info(monitored_artists)")
        ma_cols = {row[1] for row in await cur.fetchall()}
        if "metadata_profile_id" not in ma_cols:
            await db.execute("ALTER TABLE monitored_artists ADD COLUMN metadata_profile_id INTEGER REFERENCES metadata_profiles(id)")
        # Migration: release_profiles table
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS release_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                required_words TEXT DEFAULT '',
                ignored_words TEXT DEFAULT '',
                preferred_words TEXT DEFAULT '',
                score_boost INTEGER DEFAULT 0,
                is_default INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_release_profiles_default ON release_profiles(is_default);
        """)
        await db.execute("""
            INSERT OR IGNORE INTO release_profiles (name, required_words, ignored_words, preferred_words, score_boost, is_default)
            VALUES ('Default', '', '', '', 0, 1)
        """)

        # Migration: Phase 6 — blocklist table
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS blocklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL DEFAULT 'url',
                value TEXT NOT NULL UNIQUE,
                title TEXT,
                reason TEXT,
                source TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_blocklist_value ON blocklist(value);
        """)

        await db.commit()
    finally:
        await db.close()


async def get_setting(key: str, default: str = "") -> str:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else default
    finally:
        await db.close()


async def get_auth_user() -> dict | None:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM auth WHERE id = 1")
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def set_setting(key: str, value: str):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            (key, value),
        )
        await db.commit()
    finally:
        await db.close()


async def add_notification(type: str, title: str, message: str = ""):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO notifications (type, title, message) VALUES (?, ?, ?)",
            (type, title, message),
        )
        await db.commit()
    finally:
        await db.close()


async def add_activity(action: str, detail: str = ""):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO activity_log (action, detail) VALUES (?, ?)",
            (action, detail),
        )
        await db.commit()
    finally:
        await db.close()
