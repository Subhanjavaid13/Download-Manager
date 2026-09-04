"""Verify Supabase Auth JWTs.

The frontend signs users up and in with Supabase directly. Every API call then
carries `Authorization: Bearer <access_token>`. We verify the token here and
never touch passwords ourselves.

Verification order:
1. JWKS at `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` (asymmetric keys, the
   default for new projects). Keys are cached by PyJWT.
2. The legacy HS256 shared secret, when DM_SUPABASE_JWT_SECRET is set and the
   token's header says HS256.

With DM_SUPABASE_URL empty, auth is disabled and every request is anonymous.
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


class AuthError(Exception):
    pass


@lru_cache
def _jwks_client(supabase_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(
        f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json",
        cache_keys=True,
        lifespan=3600,
    )


def decode_token(token: str, settings: Settings) -> dict:
    """Return the verified claims or raise AuthError."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthError("malformed token") from exc

    alg = header.get("alg", "")
    try:
        if alg == "HS256":
            if not settings.supabase_jwt_secret:
                raise AuthError("token uses HS256 but DM_SUPABASE_JWT_SECRET is not set")
            return jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        if not settings.supabase_url:
            raise AuthError("DM_SUPABASE_URL is not set")
        key = _jwks_client(settings.supabase_url).get_signing_key_from_jwt(token)
        return jwt.decode(token, key.key, algorithms=[alg], audience="authenticated")
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc


def user_from_claims(payload: dict) -> User:
    meta = payload.get("user_metadata") or {}
    return User(
        id=payload["sub"],
        email=payload.get("email"),
        email_verified=bool(meta.get("email_verified")),
        role=payload.get("role", "authenticated"),
    )


def auth_enabled(settings: Settings) -> bool:
    return bool(settings.supabase_url or settings.supabase_jwt_secret)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> User | None:
    """Return the caller, or None when anonymous access is allowed."""
    if not auth_enabled(settings):
        return None
    if creds is None:
        return None
    try:
        return user_from_claims(decode_token(creds.credentials, settings))
    except AuthError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Your session expired. Sign in again."
        ) from exc


def require_user(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    return user


def require_verified_user(user: User = Depends(require_user)) -> User:
    if not user.email_verified:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Verify your email address first. Check your inbox."
        )
    return user
