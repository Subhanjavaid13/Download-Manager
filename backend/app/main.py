"""Downloader Manager API.

Run locally:
    uv run uvicorn app.main:app --reload
Docs: http://localhost:8000/docs
"""

import logging
from contextlib import asynccontextmanager

import yt_dlp.version
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api import info, jobs
from app.auth import auth_enabled
from app.config import get_settings
from app.core.downloader import Downloader
from app.core.ffmpeg import find_ffmpeg
from app.deps import limiter
from app.jobs.store import JobStore
from app.schemas import HealthResponse

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    ffmpeg = find_ffmpeg(settings.ffmpeg_location)
    if not ffmpeg.available:
        log.warning("FFmpeg not found. MP3 conversion and video merging will fail.")
    app.state.ffmpeg = ffmpeg

    ffmpeg_dir = str(ffmpeg.path) if ffmpeg.available else None
    app.state.downloader = Downloader(ffmpeg_location=ffmpeg_dir)
    settings.download_dir.mkdir(parents=True, exist_ok=True)
    app.state.jobs = JobStore(
        app.state.downloader,
        settings.download_dir,
        concurrency=settings.worker_concurrency,
        ttl_minutes=settings.job_ttl_minutes,
    )
    log.info("ready: ffmpeg=%s yt-dlp=%s", ffmpeg.version, yt_dlp.version.__version__)
    yield
    app.state.jobs.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
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
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Content-Disposition"],
    )
    app.include_router(info.router)
    app.include_router(jobs.router)

    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    async def health() -> HealthResponse:
        ff = app.state.ffmpeg
        return HealthResponse(
            status="ok",
            environment=settings.environment,
            ffmpeg=ff.available,
            ffmpeg_version=ff.version,
            ytdlp_version=yt_dlp.version.__version__,
            auth_enabled=auth_enabled(settings),
        )

    return app


app = create_app()
