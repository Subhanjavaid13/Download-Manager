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
    storage: Literal["local", "r2"]
    database: Literal["sqlite", "postgresql", "other"]


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
    file_url: str | None = Field(None, description="API path that streams or redirects to the file")
    direct_url: str | None = Field(None, description="Signed storage link when R2 is active")
    expires_at: str | None
    error: ErrorOut | None
    created_at: str
    finished_at: str | None
