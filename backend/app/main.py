"""Downloader Manager API.

Run locally:
    uv run uvicorn app.main:app --reload
Docs: http://localhost:8000/docs
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import yt_dlp.version
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.api import admin, info, jobs, playlists
from app.api import auth as auth_api
from app.auth import auth_enabled
from app.config import Settings, get_settings
from app.core.downloader import Downloader
from app.core.ffmpeg import find_ffmpeg
from app.db import init_db, make_engine, make_session_factory
from app.deps import limiter
from app.jobs.store import JobStore
from app.observability import init_sentry
from app.schemas import HealthResponse
from app.services.accounts import Accounts
from app.services.analytics import Analytics
from app.services.bans import Bans
from app.storage import LocalStorage

log = logging.getLogger("app")


def _cookies_file(settings: Settings) -> Path | None:
    """The cookies file, only when it is really there.

    A missing file would make yt-dlp fail every download, which is a far worse
    failure than the bot check it was meant to solve, so a wrong path is a
    warning and the server carries on without cookies.
    """
    path = settings.cookies_file
    if path is None:
        return None
    if not path.is_file():
        log.warning("DM_COOKIES_FILE points at %s, which does not exist. Ignoring it.", path)
        return None
    log.info("using the cookies file at %s for yt-dlp", path)
    return path


def _ping_database(engine) -> bool:  # noqa: ANN001
    """One cheap round-trip. Never raises: the caller reports the result instead."""
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception:  # noqa: BLE001
        log.warning("health check: database unreachable", exc_info=True)
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    ffmpeg = find_ffmpeg(settings.ffmpeg_location)
    if not ffmpeg.available:
        log.warning("FFmpeg not found. MP3 conversion and video merging will fail.")
    app.state.ffmpeg = ffmpeg
    app.state.downloader = Downloader(
        ffmpeg_location=ffmpeg.path if ffmpeg.available else None,
        cookies_file=_cookies_file(settings),
        max_file_mb=settings.max_file_mb,
    )

    engine = make_engine(settings.database_url)
    init_db(engine)
    app.state.engine = engine

    storage = LocalStorage(settings.download_dir)
    app.state.storage = storage

    session_factory = make_session_factory(engine)
    accounts = Accounts(session_factory, ip_salt=settings.ip_hash_salt)
    app.state.accounts = accounts
    app.state.bans = Bans(session_factory, ip_salt=settings.ip_hash_salt)
    # Read-only aggregates for /api/v1/admin. Also the source of the role check
    # that guards those routes, so it is built whether or not auth is configured.
    app.state.analytics = Analytics(session_factory)

    def on_finish(job: dict) -> None:
        name = {"done": "download_completed", "error": "download_failed"}.get(
            job["status"], "download_cancelled"
        )
        props = {"mode": job["mode"], "format": job["format"], "quality": job["quality"]}
        if job["playlist_job_id"]:
            props["playlist_job_id"] = job["playlist_job_id"]
        if job["status"] == "done":
            props["size_bytes"] = job["size_bytes"]
        elif job["error"]:
            props["error_code"] = job["error"]["code"]
        accounts.record(name, user_id=job.get("user_id"), properties=props)

    def on_playlist_finish(playlist: dict) -> None:
        accounts.record(
            "playlist_finished",
            user_id=playlist.get("user_id"),
            properties={
                "status": playlist["status"],
                "mode": playlist["mode"],
                "total": playlist["total_items"],
                "completed": playlist["completed_items"],
                "failed": playlist["failed_items"],
                "cancelled": playlist["cancelled_items"],
            },
        )

    app.state.jobs = JobStore(
        downloader=app.state.downloader,
        storage=storage,
        session_factory=session_factory,
        work_dir=settings.download_dir / "_work",
        concurrency=settings.worker_concurrency,
        retention_minutes=settings.file_retention_minutes,
        on_finish=on_finish,
        on_playlist_finish=on_playlist_finish,
    )
    requeued = app.state.jobs.recover()
    app.state.jobs.sweep()
    keep = (
        f"{settings.file_retention_minutes} min"
        if settings.file_retention_minutes > 0
        else "forever"
    )
    log.info(
        "ready: ffmpeg=%s yt-dlp=%s files=%s (kept %s) db=%s requeued=%d",
        ffmpeg.version,
        yt_dlp.version.__version__,
        storage.root,
        keep,
        engine.dialect.name,
        requeued,
    )
    yield
    app.state.jobs.shutdown()
    engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    init_sentry(settings)  # no DSN, no Sentry: development and CI stay untouched
    app = FastAPI(
        title=settings.app_name,
        version="0.3.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Client-Id"],
        expose_headers=["Content-Disposition"],
    )
    app.include_router(info.router)
    app.include_router(jobs.router)
    app.include_router(playlists.router)
    app.include_router(auth_api.router)
    app.include_router(admin.router)

    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    async def health() -> HealthResponse:
        """Liveness plus a real database round-trip.

        Always answers 200 while the process is up, so a brief database blip does
        not make the platform restart a container that is otherwise fine; the
        database result is reported as a field instead. That round-trip matters
        for more than reporting: an uptime monitor hitting this endpoint is what
        keeps a free-tier Supabase project from pausing after 7 idle days.
        """
        settings = get_settings()  # read fresh so config changes show up without a restart
        ff = app.state.ffmpeg
        dialect = app.state.engine.dialect.name
        database_ok = await run_in_threadpool(_ping_database, app.state.engine)
        return HealthResponse(
            status="ok",
            environment=settings.environment,
            ffmpeg=ff.available,
            ffmpeg_version=ff.version,
            ytdlp_version=yt_dlp.version.__version__,
            auth_enabled=auth_enabled(settings),
            require_auth=settings.require_auth,
            signup_enabled=bool(settings.supabase_url and settings.supabase_anon_key),
            database=dialect if dialect in ("sqlite", "postgresql") else "other",
            database_ok=database_ok,
        )

    return app


app = create_app()
