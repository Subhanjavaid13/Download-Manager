"""Verify Supabase Auth JWTs (Phase 2).

The frontend signs users up and in with Supabase directly. Every API call then
carries `Authorization: Bearer <access_token>`. We verify the token here and
never touch passwords ourselves.

Two verification paths are supported:
- Modern projects: asymmetric keys via JWKS at
  `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` (set DM_SUPABASE_URL).
- Legacy projects: the shared HS256 secret (set DM_SUPABASE_JWT_SECRET).

With neither configured, auth is disabled and every request is anonymous.
That is the development default.
"""

from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class User:
    id: str
    email: str | None
    email_verified: bool
    role: str = "authenticated"


@lru_cache
def _jwks_client(supabase_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json")


def _decode(token: str, settings: Settings) -> dict:
    if settings.supabase_jwt_secret:
        return jwt.decode(
            token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated"
        )
    if settings.supabase_url:
        key = _jwks_client(settings.supabase_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token, key.key, algorithms=["ES256", "RS256"], audience="authenticated"
        )
    raise RuntimeError("auth is not configured")


def auth_enabled(settings: Settings) -> bool:
    return bool(settings.supabase_jwt_secret or settings.supabase_url)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> User | None:
    """Return the caller, or None when anonymous access is allowed."""
    if not auth_enabled(settings):
        return None
    if creds is None:
        if settings.require_auth:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
        return None
    try:
        payload = _decode(creds.credentials, settings)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session expired. Sign in again.") from exc

    meta = payload.get("user_metadata") or {}
    return User(
        id=payload["sub"],
        email=payload.get("email"),
        email_verified=bool(meta.get("email_verified") or payload.get("email_confirmed_at")),
        role=payload.get("role", "authenticated"),
    )


def require_user(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    return user
