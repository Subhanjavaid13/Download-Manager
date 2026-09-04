"""Downloader Manager API.

Run locally:
    uv run uvicorn app.main:app --reload
Docs: http://localhost:8000/docs
"""

import logging
from contextlib import asynccontextmanager

import yt_dlp.version
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.api import auth as auth_api
from app.api import info, jobs
from app.auth import auth_enabled
from app.config import get_settings
from app.core.downloader import Downloader
from app.core.ffmpeg import find_ffmpeg
from app.db import init_db, make_engine, make_session_factory
from app.deps import limiter
from app.jobs.store import JobStore
from app.schemas import HealthResponse
from app.services.accounts import Accounts
from app.storage import build_storage

log = logging.getLogger("app")


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
    app.state.downloader = Downloader(ffmpeg_location=ffmpeg.path if ffmpeg.available else None)

    engine = make_engine(settings.database_url)
    init_db(engine)
    app.state.engine = engine

    settings.download_dir.mkdir(parents=True, exist_ok=True)
    storage = build_storage(settings)
    app.state.storage = storage

    session_factory = make_session_factory(engine)
    accounts = Accounts(session_factory, ip_salt=settings.ip_hash_salt)
    app.state.accounts = accounts

    def on_finish(job: dict) -> None:
        name = {"done": "download_completed", "error": "download_failed"}.get(
            job["status"], "download_cancelled"
        )
        props = {"mode": job["mode"], "format": job["format"], "quality": job["quality"]}
        if job["status"] == "done":
            props["size_bytes"] = job["size_bytes"]
        elif job["error"]:
            props["error_code"] = job["error"]["code"]
        accounts.record(name, user_id=job.get("user_id"), properties=props)

    app.state.jobs = JobStore(
        downloader=app.state.downloader,
        storage=storage,
        session_factory=session_factory,
        work_dir=settings.download_dir / "_work",
        concurrency=settings.worker_concurrency,
        ttl_minutes=settings.job_ttl_minutes,
        on_finish=on_finish,
    )
    requeued = app.state.jobs.recover()
    app.state.jobs.sweep()
    log.info(
        "ready: ffmpeg=%s yt-dlp=%s storage=%s db=%s requeued=%d",
        ffmpeg.version,
        yt_dlp.version.__version__,
        storage.kind,
        engine.dialect.name,
        requeued,
    )
    yield
    app.state.jobs.shutdown()
    engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
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
    app.include_router(auth_api.router)

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
            storage=app.state.storage.kind,
            database=dialect if dialect in ("sqlite", "postgresql") else "other",
            database_ok=database_ok,
        )

    return app


app = create_app()
