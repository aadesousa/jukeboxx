from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class SetupRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TrackOut(BaseModel):
    id: int
    path: str
    sha256: Optional[str] = None
    artist: Optional[str] = None
    album_artist: Optional[str] = None
    title: Optional[str] = None
    album: Optional[str] = None
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    year: Optional[int] = None
    genre: Optional[str] = None
    format: Optional[str] = None
    bitrate: Optional[int] = None
    duration: Optional[int] = None
    size: Optional[int] = None
    mtime: Optional[float] = None
    spotify_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DownloadOut(BaseModel):
    id: int
    spotify_id: str
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    item_type: Optional[str] = None
    status: str = "pending"
    error_message: Optional[str] = None
    spotizerr_task_id: Optional[str] = None
    source: str = "manual"
    retry_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SyncItemOut(BaseModel):
    id: int
    spotify_id: str
    item_type: str
    name: Optional[str] = None
    last_synced_at: Optional[str] = None
    track_count: int = 0
    local_count: int = 0
    enabled: bool = True
    created_at: Optional[str] = None


class SyncItemCreate(BaseModel):
    spotify_id: str
    item_type: str = "playlist"
    name: Optional[str] = None


class SyncItemUpdate(BaseModel):
    enabled: Optional[bool] = None


class DuplicatePairOut(BaseModel):
    id: int
    track_a: Optional[TrackOut] = None
    track_b: Optional[TrackOut] = None
    match_type: str
    similarity_score: Optional[float] = None
    status: str = "pending"
    resolution: Optional[str] = None
    resolved_at: Optional[str] = None
    created_at: Optional[str] = None


class DuplicateResolve(BaseModel):
    action: str  # 'keep_a', 'keep_b', 'keep_both', 'skip'


class ScanStatusOut(BaseModel):
    id: Optional[int] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    tracks_found: int = 0
    tracks_added: int = 0
    tracks_updated: int = 0
    tracks_removed: int = 0
    duplicates_found: int = 0
    status: str = "idle"
    error_message: Optional[str] = None


class StatsOut(BaseModel):
    total_tracks: int = 0
    total_artists: int = 0
    total_albums: int = 0
    total_missing: int = 0
    total_size_gb: float = 0.0
    format_breakdown: dict = {}
    sync_items: int = 0
    pending_downloads: int = 0
    failed_downloads: int = 0
    pending_duplicates: int = 0
    last_scan: Optional[ScanStatusOut] = None
    spotizerr_reachable: bool = False
    spotify_connected: bool = False
    failed_imports: Optional[dict] = None


class SettingsOut(BaseModel):
    spotify_connected: bool = False
    spotify_scopes: Optional[str] = None
    spotify_client_id: str = ""
    spotify_client_secret_set: bool = False
    spotify_redirect_uri: str = ""
    spotizerr_url: str = ""
    sync_interval_minutes: int = 60
    fuzzy_threshold: int = 85
    m3u_path_prefix: str = ""
    scan_interval_hours: int = 6
    account_sync_enabled: bool = False
    music_path: str = "/music"
    jellyfin_url: str = ""
    jellyfin_api_key: str = ""
    metube_url: str = "http://metube:8081"
    youtube_audio_format: str = "mp3"
    youtube_audio_quality: str = "0"
    match_review_threshold: int = 75
    spotizerr_concurrent_limit: int = 20
    dispatch_batch_size: int = 10
    youtube_api_key_set: bool = False
    youtube_fallback_enabled: bool = False
    youtube_auto_threshold: int = 85
    calendar_enabled: bool = False
    slsk_album_download: bool = True
    download_source_priority: str = '["torrent","usenet","soulseek","youtube","spotizerr"]'
    youtube_search_mode: str = "studio"
    discord_webhook_url: str = ""
    discord_notify_download_complete: bool = True
    discord_notify_new_release: bool = True
    discord_notify_dispatch: bool = False
    queue_paused: bool = False
    torrent_save_path: str = ""
    torrent_hardlink_enabled: bool = False


class SettingsUpdate(BaseModel):
    spotify_client_id: Optional[str] = None
    spotify_client_secret: Optional[str] = None
    spotify_redirect_uri: Optional[str] = None
    spotizerr_url: Optional[str] = None
    sync_interval_minutes: Optional[int] = None
    fuzzy_threshold: Optional[int] = None
    m3u_path_prefix: Optional[str] = None
    scan_interval_hours: Optional[int] = None
    account_sync_enabled: Optional[bool] = None
    music_path: Optional[str] = None
    jellyfin_url: Optional[str] = None
    jellyfin_api_key: Optional[str] = None
    metube_url: Optional[str] = None
    youtube_audio_format: Optional[str] = None
    youtube_audio_quality: Optional[str] = None
    match_review_threshold: Optional[int] = None
    spotizerr_concurrent_limit: Optional[int] = None
    dispatch_batch_size: Optional[int] = None
    youtube_api_key: Optional[str] = None
    youtube_fallback_enabled: Optional[bool] = None
    youtube_auto_threshold: Optional[int] = None
    calendar_enabled: Optional[bool] = None
    slsk_album_download: Optional[bool] = None
    download_source_priority: Optional[str] = None
    youtube_search_mode: Optional[str] = None
    discord_webhook_url: Optional[str] = None
    discord_notify_download_complete: Optional[bool] = None
    discord_notify_new_release: Optional[bool] = None
    discord_notify_dispatch: Optional[bool] = None
    torrent_save_path: Optional[str] = None
    torrent_hardlink_enabled: Optional[bool] = None


class DownloadPreview(BaseModel):
    to_download: int = 0
    already_local: int = 0
    already_queued: int = 0
    fuzzy_matched: int = 0
    tracks: list = []


class NotificationOut(BaseModel):
    id: int
    type: str
    title: str
    message: Optional[str] = None
    read: bool = False
    created_at: Optional[str] = None


class ActivityOut(BaseModel):
    id: int
    action: str
    detail: Optional[str] = None
    created_at: Optional[str] = None


class ScanProgressOut(BaseModel):
    phase: str = "idle"
    total_files: int = 0
    processed: int = 0
    progress_percent: float = 0.0
    eta_seconds: Optional[float] = None
    started_at: Optional[str] = None


class MatchScoreOut(BaseModel):
    total: float
    title: float
    artist: float
    duration: float
    album: float
    track_number: float
    year: float
    is_confident: bool
    is_fuzzy: bool
    is_no_match: bool


class MatchRequest(BaseModel):
    local: dict
    spotify: dict
