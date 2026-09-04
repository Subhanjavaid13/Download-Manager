"""Account endpoints.

Sign-in, password reset, and sessions are handled by Supabase directly from the
browser. Sign-up goes through this API so the email checks and the CAPTCHA are
enforced server-side, then the API forwards the request to Supabase Auth.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from app.auth import User, auth_enabled, require_user
from app.config import Settings, get_settings
from app.deps import get_accounts, get_client_id, get_job_store, limiter
from app.jobs.store import JobStore
from app.services.accounts import Accounts, hash_ip
from app.services.emailcheck import check_email

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

TURNSTILE_VERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str | None = Field(None, max_length=80)
    turnstile_token: str | None = None
    redirect_to: str | None = Field(None, max_length=512)


class SignupResponse(BaseModel):
    user_id: str | None
    email: str
    confirmation_required: bool
    session: dict | None = None
    message: str


class ProfileResponse(BaseModel):
    id: str
    email: str | None
    display_name: str | None
    role: str
    daily_quota: int
    downloads_today: int
    email_verified: bool
    email_risk: str
    created_at: str | None


class ClaimResponse(BaseModel):
    claimed: int


class AuthConfig(BaseModel):
    enabled: bool
    signup_enabled: bool
    require_auth: bool
    anon_daily_limit: int
    turnstile_required: bool


async def _verify_turnstile(token: str | None, ip: str | None, settings: Settings) -> None:
    if not settings.turnstile_secret:
        return
    if not token:
        raise HTTPException(400, "Please complete the human check and try again.")
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            TURNSTILE_VERIFY,
            data={"secret": settings.turnstile_secret, "response": token, "remoteip": ip or ""},
        )
    if not (r.status_code == 200 and r.json().get("success")):
        raise HTTPException(400, "The human check failed. Reload the page and try again.")


@router.get("/config", response_model=AuthConfig)
async def auth_config(settings: Settings = Depends(get_settings)) -> AuthConfig:
    return AuthConfig(
        enabled=auth_enabled(settings),
        signup_enabled=bool(settings.supabase_url and settings.supabase_anon_key),
        require_auth=settings.require_auth,
        anon_daily_limit=settings.anon_daily_limit,
        turnstile_required=bool(settings.turnstile_secret),
    )


@router.post("/signup", response_model=SignupResponse)
@limiter.limit("5/minute")
async def signup(
    request: Request,
    body: SignupRequest,
    settings: Settings = Depends(get_settings),
    accounts: Accounts = Depends(get_accounts),
) -> SignupResponse:
    if not (settings.supabase_url and settings.supabase_anon_key):
        raise HTTPException(503, "Sign-up is not configured on this server yet.")

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    await _verify_turnstile(body.turnstile_token, ip, settings)

    result = check_email(
        str(body.email),
        check_disposable=settings.check_disposable_email,
        check_mx=settings.check_mx,
    )
    domain = str(body.email).rsplit("@", 1)[1].lower()
    if not result.ok:
        accounts.record(
            "signup_rejected",
            properties={"reason": result.risk, "domain": domain},
            ip=ip,
            user_agent=ua,
        )
        raise HTTPException(400, result.message or "That email address cannot be used.")

    payload: dict = {"email": str(body.email), "password": body.password}
    if body.display_name:
        payload["data"] = {"full_name": body.display_name.strip()}
    params = {"redirect_to": body.redirect_to} if body.redirect_to else None
    headers = {
        "apikey": settings.supabase_anon_key,
        "Authorization": f"Bearer {settings.supabase_anon_key}",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/signup",
            json=payload,
            params=params,
            headers=headers,
        )

    if r.status_code >= 400:
        detail = _supabase_error(r)
        accounts.record(
            "signup_failed", properties={"status": r.status_code, "domain": domain}, ip=ip
        )
        raise HTTPException(400 if r.status_code < 500 else 502, detail)

    data = r.json()
    user = data.get("user") or (data if "id" in data else {})
    user_id = user.get("id")
    session = {
        k: data[k]
        for k in ("access_token", "refresh_token", "expires_in", "expires_at")
        if k in data
    }
    confirmation_required = not session

    if user_id:
        accounts.set_email_risk(user_id, result.risk, hash_ip(ip, settings.ip_hash_salt), ua)
        accounts.record(
            "signup",
            user_id=user_id,
            properties={
                "risk": result.risk,
                "domain": domain,
                "confirmed": not confirmation_required,
            },
            ip=ip,
            user_agent=ua,
        )

    return SignupResponse(
        user_id=user_id,
        email=str(body.email),
        confirmation_required=confirmation_required,
        session=session or None,
        message=(
            "Check your inbox and tap the link to verify your email."
            if confirmation_required
            else "Account created."
        ),
    )


def _supabase_error(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return "Sign-up failed. Please try again."
    code = body.get("error_code") or body.get("code") or ""
    msg = body.get("msg") or body.get("message") or body.get("error_description") or ""
    if code == "user_already_exists" or "already registered" in msg.lower():
        return "An account with that email already exists. Sign in instead."
    if code == "weak_password" or "password" in msg.lower():
        return msg or "That password is too weak."
    if code == "over_email_send_rate_limit" or "rate limit" in msg.lower():
        return "Too many sign-ups right now. Please try again in a few minutes."
    return msg or "Sign-up failed. Please try again."


@router.get("/me", response_model=ProfileResponse)
async def me(
    user: User = Depends(require_user),
    accounts: Accounts = Depends(get_accounts),
) -> ProfileResponse:
    return ProfileResponse(**accounts.get_profile(user).as_dict())


@router.post("/claim", response_model=ClaimResponse)
async def claim_history(
    request: Request,
    user: User = Depends(require_user),
    client_id: str | None = Depends(get_client_id),
    accounts: Accounts = Depends(get_accounts),
) -> ClaimResponse:
    """Called once after sign-in: attach this browser's anonymous downloads to the account."""
    accounts.ensure_profile(user)
    claimed = accounts.claim_anonymous_history(user, client_id)
    accounts.record(
        "signin",
        user_id=user.id,
        properties={"claimed": claimed, "verified": user.email_verified},
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return ClaimResponse(claimed=claimed)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    user: User = Depends(require_user),
    accounts: Accounts = Depends(get_accounts),
    store: JobStore = Depends(get_job_store),
) -> None:
    for key in accounts.storage_keys_for(user):
        store.delete_stored(key)
    accounts.record("account_deleted", user_id=user.id)
    accounts.delete_account(user)
