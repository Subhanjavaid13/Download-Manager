"""Shared singletons and FastAPI dependencies."""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.downloader import Downloader
from app.jobs.store import JobStore

# Per-IP rate limiting. Phase 2 switches the key to the user id when signed in.
limiter = Limiter(key_func=get_remote_address)


def get_downloader(request: Request) -> Downloader:
    return request.app.state.downloader


def get_job_store(request: Request) -> JobStore:
    return request.app.state.jobs
