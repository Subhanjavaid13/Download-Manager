"""Application settings.

Every value can be overridden with an environment variable prefixed `DM_`,
for example `DM_CORS_ORIGINS='["https://app.example.com"]'`.
Locally, put them in `backend/.env` (see `.env.example`).
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DM_", extra="ignore")

    app_name: str = "Downloader Manager API"
    environment: str = "development"  # development | production
    log_level: str = "info"

    # Frontend origins allowed to call this API.
    cors_origins: list[str] = ["http://localhost:3000"]

    # Where files are written while a job runs (and kept, with local storage).
    download_dir: Path = Path("./downloads")

    # Abuse and cost controls (free tiers are small; keep these tight).
    max_duration_sec: int = 3 * 60 * 60  # refuse videos longer than 3 hours
    max_file_mb: int = 500
    job_ttl_minutes: int = 60  # finished files are deleted after this
    worker_concurrency: int = 2
    rate_limit_info: str = "30/minute"
    rate_limit_jobs: str = "10/minute"

    # Optional explicit path to ffmpeg (directory or binary). Auto-detected if empty.
    ffmpeg_location: str | None = None

    # Database. SQLite locally, Supabase Postgres in production
    # (use the "Transaction pooler" URI, port 6543, with the postgresql+psycopg driver).
    database_url: str = "sqlite:///./dm.db"

    # File storage for finished downloads.
    #   local: files stay in download_dir and the API streams them.
    #   r2:    files are uploaded to Cloudflare R2 and served by a signed link (zero egress).
    storage: Literal["local", "r2"] = "local"
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket: str | None = None
    r2_endpoint_url: str | None = None  # defaults to https://<account_id>.r2.cloudflarestorage.com

    # Auth (Phase 2). Leave empty to run the API without authentication in development.
    require_auth: bool = False
    supabase_url: str | None = None
    supabase_jwt_secret: str | None = None  # legacy HS256 secret; JWKS is used when empty


@lru_cache
def get_settings() -> Settings:
    return Settings()
