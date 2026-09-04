"""Application settings.

Every value can be overridden with an environment variable prefixed `DM_`,
for example `DM_CORS_ORIGINS='["https://app.example.com"]'`.
Locally, put them in `backend/.env` (see `.env.example`).
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DM_", extra="ignore")

    app_name: str = "Downloader Manager API"
    environment: str = "development"  # development | production
    log_level: str = "info"

    # Frontend origins allowed to call this API.
    cors_origins: list[str] = ["http://localhost:3000"]

    # Where finished files are written before they are served or uploaded.
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

    # Auth (Phase 2). Leave empty to run the API without authentication in development.
    require_auth: bool = False
    supabase_url: str | None = None
    supabase_jwt_secret: str | None = None  # legacy HS256 secret; JWKS is used when empty

    # Database (Phase 2). SQLite locally, Supabase Postgres in production.
    database_url: str = "sqlite:///./dm.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
