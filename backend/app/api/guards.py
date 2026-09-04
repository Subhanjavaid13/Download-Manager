"""Checks every download request passes before a row is created.

Kept in one place because a playlist has to answer exactly the same questions as
a single video, only with a larger price tag.
"""

from fastapi import HTTPException, status

from app.auth import User, auth_enabled
from app.config import Settings
from app.jobs.store import Owner
from app.services.accounts import Accounts
from app.services.bans import Bans


def enforce_not_banned(bans: Bans, user: User | None, ip: str | None) -> None:
    """Block listed users and addresses before anything expensive happens."""
    ban = bans.check(user_id=user.id if user else None, ip=ip)
    if ban is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, ban.message)


def enforce_quota(
    user: User | None,
    owner: Owner,
    accounts: Accounts,
    settings: Settings,
    cost: int = 1,
) -> None:
    """Who may start a download right now, and how many today.

    Auth off (development): anyone, unlimited.
    Auth on, anonymous:     DM_ANON_DAILY_LIMIT per browser, unless DM_REQUIRE_AUTH.
    Auth on, signed in:     must be email-verified; profiles.daily_quota per day.

    `cost` is the number of files the request will produce, so a 12-video
    playlist costs 12. A playlist is refused unless the whole of it fits in
    what is left today: half a playlist is not a useful thing to hand someone,
    and counting a playlist as one download would let a guest with 3 a day walk
    off with 200 files.
    """
    if not auth_enabled(settings):
        return
    if user is None:
        if settings.require_auth:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to download.")
        if owner.client_id is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to download.")
        used = accounts.anonymous_downloads_today(owner.client_id)
        limit = settings.anon_daily_limit
        if used + cost > limit:
            accounts.record("quota_hit", properties={"anonymous": True, "used": used, "cost": cost})
            if cost > 1:
                advice = "Sign in for a bigger daily allowance, or pick a shorter playlist."
                message = _playlist_message(cost, max(limit - used, 0), advice)
            else:
                message = f"You have used today's {limit} free downloads. Sign in for more."
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, message)
        return
    if not user.email_verified:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Verify your email address first. Check your inbox."
        )
    quota = accounts.quota_for(user)
    used = accounts.downloads_today(user.id)
    if used + cost > quota:
        accounts.record(
            "quota_hit", user_id=user.id, properties={"used": used, "quota": quota, "cost": cost}
        )
        if cost > 1:
            advice = "Try again tomorrow, or pick a shorter playlist."
            message = _playlist_message(cost, max(quota - used, 0), advice)
        else:
            message = f"Daily limit of {quota} downloads reached. Try again tomorrow."
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, message)


def _playlist_message(cost: int, remaining: int, advice: str) -> str:
    left = "no downloads left" if remaining == 0 else f"only {remaining} left"
    return f"This playlist needs {cost} downloads and you have {left} today. {advice}"
