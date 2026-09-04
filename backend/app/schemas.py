"""Request and response models for the HTTP API."""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"]
    environment: str
    ffmpeg: bool
    ffmpeg_version: str | None
    ytdlp_version: str
    auth_enabled: bool
    require_auth: bool
    signup_enabled: bool
    database: Literal["sqlite", "postgresql", "other"]
    database_ok: bool


class PlaylistItemPreview(BaseModel):
    """One video listed in a playlist preview, before anything is downloaded."""

    id: str
    title: str
    duration_sec: int | None = None
    thumbnail: str | None = None


class InfoResponse(BaseModel):
    id: str
    title: str
    channel: str | None
    duration_sec: int | None
    thumbnail: str | None
    webpage_url: str
    is_live: bool
    available_heights: list[int]
    has_audio: bool
    kind: Literal["video", "playlist"]
    playlist_id: str | None
    # Playlist previews only. `playlist_truncated` means the playlist holds more
    # videos than DM_MAX_PLAYLIST_ITEMS, so a download would be refused.
    playlist_count: int | None = None
    playlist_truncated: bool = False
    playlist_limit: int | None = None
    items: list[PlaylistItemPreview] | None = None


class JobCreate(BaseModel):
    url: str = Field(..., max_length=2048)
    mode: Literal["audio", "video"] = "audio"
    audio_format: Literal["mp3", "m4a", "opus"] = "mp3"
    audio_bitrate: Literal[128, 192, 320] = 192
    video_height: Literal[360, 480, 720, 1080, 1440, 2160] | None = 1080


class ProgressOut(BaseModel):
    stage: str
    percent: float
    downloaded_bytes: int
    total_bytes: int | None
    speed_bps: float | None
    eta_sec: int | None
    detail: str | None


class ErrorOut(BaseModel):
    code: str
    message: str


class JobResponse(BaseModel):
    id: str
    video_id: str
    url: str
    title: str | None
    channel: str | None
    thumbnail: str | None
    duration_sec: int | None
    mode: str
    format: str
    quality: str | None
    label: str
    status: str
    progress: ProgressOut
    filename: str | None
    size_bytes: int | None
    file_available: bool
    file_url: str | None = Field(None, description="API path that streams the file")
    expires_at: str | None = Field(
        None, description="When the server will delete the file. Null when it is kept."
    )
    error: ErrorOut | None
    created_at: str
    finished_at: str | None
    playlist_job_id: str | None = Field(None, description="Parent playlist, when this is an item")
    playlist_index: int | None = None


class PlaylistCreate(JobCreate):
    """Same options as a single download; the URL must carry a `list=` id."""


class PlaylistResponse(BaseModel):
    id: str
    playlist_id: str
    url: str
    title: str | None
    channel: str | None
    thumbnail: str | None
    mode: str
    format: str
    quality: str | None
    label: str
    status: str  # queued | running | done | partial | error | cancelled
    total_items: int
    completed_items: int
    failed_items: int
    cancelled_items: int
    percent: float
    error: ErrorOut | None
    created_at: str
    finished_at: str | None
    items: list[JobResponse] | None = Field(
        None, description="The videos, in order. Null in list views: fetch the playlist by id."
    )
