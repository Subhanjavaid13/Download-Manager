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

    # Where finished files are kept. Point it at a real folder you can open,
    # for example C:/Users/you/Music or /home/you/Music. See .env.example.
    download_dir: Path = Path("./downloads")

    # Abuse and cost controls (free tiers are small; keep these tight).
    max_duration_sec: int = 3 * 60 * 60  # refuse videos longer than 3 hours
    max_file_mb: int = 500  # a download is aborted as soon as it passes this
    max_playlist_items: int = 50  # largest playlist accepted in one request
    # How long a finished file is kept before the janitor deletes it.
    # 0 (the default) keeps it forever: the file is yours. Set a number of
    # minutes only on a shared server, where a disk that never empties is a
    # real problem, and tell your users about it.
    file_retention_minutes: int = 0
    worker_concurrency: int = 2
    rate_limit_info: str = "30/minute"
    rate_limit_jobs: str = "10/minute"

    # Optional explicit path to ffmpeg (directory or binary). Auto-detected if empty.
    ffmpeg_location: str | None = None

    # Optional cookies file (Netscape format) handed to yt-dlp. Set it when YouTube
    # starts asking the server to "sign in to confirm you're not a bot". See
    # .env.example for how to export one. Never commit the file itself.
    cookies_file: Path | None = None

    # Database. SQLite locally, Supabase Postgres in production
    # (use the "Transaction pooler" URI, port 6543, with the postgresql+psycopg driver).
    database_url: str = "sqlite:///./dm.db"

    # Auth (Phase 2). Leave supabase_url empty to run the API without authentication.
    require_auth: bool = False  # true: every download needs a signed-in, verified user
    supabase_url: str | None = None
    supabase_anon_key: str | None = None  # public "anon"/publishable key; needed for sign-up
    supabase_jwt_secret: str | None = None  # legacy HS256 secret; JWKS is used when empty

    # Quotas. Signed-in users get profiles.daily_quota (20 by default, editable per user).
    anon_daily_limit: int = 3  # downloads per day per anonymous browser while auth is on

    # Sign-up hardening.
    check_disposable_email: bool = True
    check_mx: bool = True
    turnstile_secret: str | None = None  # Cloudflare Turnstile; verified only when set
    ip_hash_salt: str = "change-me-in-production"  # IPs are stored as salted hashes only

    # Which client IP to trust for rate limits, bans, and event logs.
    #   client_ip_header: a header written by a proxy the client cannot bypass,
    #     e.g. "cf-connecting-ip" behind Cloudflare or "x-real-ip" behind nginx.
    #     Leave empty and no header is trusted at all.
    #   trusted_proxy_hops: how many proxies of your own append to X-Forwarded-For.
    #     0 (the default) means X-Forwarded-For is ignored entirely.
    # See app/deps.py:client_ip for the reasoning behind both.
    client_ip_header: str | None = None
    trusted_proxy_hops: int = 0

    # Error tracking. Sentry starts only when a DSN is set; PII is scrubbed either way.
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
