"""Shared singletons and FastAPI dependencies."""

import re

from fastapi import Depends, Header, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth import User, get_current_user
from app.core.downloader import Downloader
from app.jobs.store import JobStore, Owner

# Per-IP rate limiting. Phase 2 switches the key to the user id when signed in.
limiter = Limiter(key_func=get_remote_address)

_CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def get_downloader(request: Request) -> Downloader:
    return request.app.state.downloader


def get_job_store(request: Request) -> JobStore:
    return request.app.state.jobs


def get_client_id(x_client_id: str | None = Header(default=None)) -> str | None:
    """Anonymous browser identity. The frontend generates it once and stores it locally."""
    if x_client_id and _CLIENT_ID.match(x_client_id):
        return x_client_id
    return None


def get_owner(
    user: User | None = Depends(get_current_user),
    client_id: str | None = Depends(get_client_id),
) -> Owner:
    return Owner(user_id=user.id if user else None, client_id=client_id)
