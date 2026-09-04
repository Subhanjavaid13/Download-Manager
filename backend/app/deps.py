"""Shared singletons and FastAPI dependencies."""

import hashlib
import re

from fastapi import Depends, Header, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth import User, get_current_user
from app.config import Settings, get_settings
from app.core.downloader import Downloader
from app.jobs.store import JobStore, Owner
from app.services.accounts import Accounts
from app.services.bans import Bans


def client_ip(request: Request, settings: Settings | None = None) -> str:
    """The address we hold a caller responsible for: rate limits, bans, event logs.

    The tradeoff, and why this is not just `get_remote_address`:

    Production runs uvicorn with `--proxy-headers` and `FORWARDED_ALLOW_IPS=*`,
    which is what makes the socket address (always the load balancer) turn back
    into a real client address. The cost is that uvicorn will then believe any
    `X-Forwarded-For` it is handed, and that header is client-supplied: anyone
    can send `X-Forwarded-For: 1.2.3.4` and get a fresh rate-limit bucket, or
    walk straight around an IP ban, by changing one number per request.

    So we do not trust X-Forwarded-For by default. In order:

    1. `DM_CLIENT_IP_HEADER` (e.g. `cf-connecting-ip` behind Cloudflare,
       `x-real-ip` behind your own nginx). These are written by the edge on
       every request and *overwrite* whatever the client sent, so they cannot be
       forged from outside. Only set this when such an edge is actually in front
       of the API, otherwise it becomes the easiest header in the world to fake.
    2. `DM_TRUSTED_PROXY_HOPS` > 0: take the entry that many positions from the
       right of X-Forwarded-For, i.e. the last address your own infrastructure
       appended. Values further left are attacker-controlled and ignored.
    3. Otherwise the peer address, which is unforgeable but collapses every
       caller behind a proxy into one bucket.

    Default is 0 hops and no header, which is the safe reading for local
    development and for a backend exposed directly.
    """
    settings = settings or get_settings()
    if settings.client_ip_header:
        value = request.headers.get(settings.client_ip_header)
        if value:
            return value.split(",")[0].strip()
    if settings.trusted_proxy_hops > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            hops = [part.strip() for part in forwarded.split(",") if part.strip()]
            if hops:
                index = max(len(hops) - settings.trusted_proxy_hops, 0)
                return hops[index]
    return get_remote_address(request) or "unknown"


def rate_limit_key(request: Request) -> str:
    """Signed-in callers are limited per token, anonymous callers per IP."""
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return "tok:" + hashlib.sha256(auth[7:].encode()).hexdigest()[:24]
    return "ip:" + client_ip(request)


limiter = Limiter(key_func=rate_limit_key)

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


def get_accounts(request: Request) -> Accounts:
    return request.app.state.accounts


def get_bans(request: Request) -> Bans:
    return request.app.state.bans
