"""The admin dashboard's data (Phase 5).

One rule governs this whole module: **every route is closed unless the caller
holds a valid Supabase token whose profile row says `role = 'admin'`.** There is
no second way in - no shared secret, no header, no `?admin=1`, no "allow when
auth is off" escape hatch for development. `require_admin` below is the only
door, it is declared once as a router-level dependency so a new route cannot
forget it, and it answers 401 for a caller with no session and 403 for everyone
else. The role is read from the database on every request, so revoking somebody
takes one UPDATE and no redeploy.

The numbers themselves live in `app.services.analytics`, which aggregates in SQL
and works on SQLite as well as Postgres. Nothing here returns a raw IP address, a
full URL, or an unmasked email address.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.auth import User, require_user
from app.services.analytics import (
    DEFAULT_RANGE_DAYS,
    MAX_RANGE_DAYS,
    Analytics,
    DateRange,
    resolve_range,
)


def get_analytics(request: Request) -> Analytics:
    return request.app.state.analytics


async def require_admin(
    user: Annotated[User, Depends(require_user)],
    analytics: Annotated[Analytics, Depends(get_analytics)],
) -> User:
    """Signed in, and an admin. Anything else is refused.

    `require_user` has already answered 401 when there is no usable token, so
    reaching here means the token verified. The role lookup is deliberately
    read-only: an unknown id is refused rather than quietly given a profile,
    which keeps a probe against this endpoint from writing anything at all.
    """
    role = await run_in_threadpool(analytics.role_of, user.id)
    if role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins only.")
    return user


router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
    responses={
        401: {"description": "Not signed in."},
        403: {"description": "Signed in, but not an admin."},
    },
)


# ---------------------------------------------------------------------------
# The date range every route accepts
# ---------------------------------------------------------------------------


async def date_range(
    days: Annotated[
        int,
        Query(
            ge=1, le=MAX_RANGE_DAYS, description="Days back from today, when from/to are absent."
        ),
    ] = DEFAULT_RANGE_DAYS,
    start: Annotated[date | None, Query(alias="from", description="First day, inclusive.")] = None,
    end: Annotated[date | None, Query(alias="to", description="Last day, inclusive.")] = None,
) -> DateRange:
    return resolve_range(days=days, start=start, end=end)


RangeDep = Annotated[DateRange, Depends(date_range)]
AnalyticsDep = Annotated[Analytics, Depends(get_analytics)]


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------


class RangeOut(BaseModel):
    start: str
    end: str
    days: int


class SignupDay(BaseModel):
    day: str
    total: int
    verified: int
    unverified: int
    flagged: int
    disposable: int
    no_mx: int
    refused: int


class SignupsOut(BaseModel):
    daily: list[SignupDay]
    totals: dict[str, int]


class ActiveDay(BaseModel):
    day: str
    total: int
    signed_in: int
    guests: int


class ActiveUsersOut(BaseModel):
    daily: list[ActiveDay]
    dau: int
    avg_dau: float
    wau: int
    wau_signed_in: int
    mau: int
    in_range: int
    in_range_signed_in: int
    stickiness: float


class DownloadDay(BaseModel):
    day: str
    total: int
    done: int
    failed: int
    cancelled: int
    audio: int
    video: int


class FormatRow(BaseModel):
    mode: str
    format: str
    quality: str | None
    total: int
    done: int
    bytes: int


class ErrorRow(BaseModel):
    code: str
    count: int


class DownloadTotals(BaseModel):
    total: int
    done: int
    failed: int
    cancelled: int
    audio: int
    video: int
    from_playlists: int
    bytes: int
    success_rate: float | None


class DownloadsOut(BaseModel):
    daily: list[DownloadDay]
    by_format: list[FormatRow]
    errors: list[ErrorRow]
    totals: DownloadTotals


class TimingOut(BaseModel):
    """Seconds from the moment a job was created to the moment its file was ready."""

    samples: int
    median_sec: float | None
    p90_sec: float | None
    fastest_sec: float | None
    slowest_sec: float | None
    mean_sec: float | None


class DomainRow(BaseModel):
    domain: str
    accounts: int
    verified: int
    flagged: int


class FlaggedAccount(BaseModel):
    id: str
    #: Masked: `j***@example.com`. The real address is never sent to the browser.
    email: str
    risk: str
    verified: bool
    downloads: int
    created_at: str | None


class AccountTotals(BaseModel):
    accounts: int
    verified: int
    admins: int
    flagged: int


class AccountsOut(BaseModel):
    domains: list[DomainRow]
    flagged: list[FlaggedAccount]
    totals: AccountTotals


class FunnelStep(BaseModel):
    key: str
    label: str
    count: int
    of_previous: float | None = None
    of_start: float | None = None
    note: str | None = None
    eligible: int | None = None


class FunnelsOut(BaseModel):
    cohort: RangeOut
    steps: list[FunnelStep]


class RetentionOut(BaseModel):
    keep_days: int
    events: int
    oldest_event: str | None
    #: Rows already older than `keep_days`. Anything but 0 means the nightly
    #: prune job has not run.
    overdue: int


class SummaryOut(BaseModel):
    signups: int
    verified_signups: int
    refused_signups: int
    active_users: int
    active_signed_in: int
    wau: int
    downloads: int
    downloads_done: int
    downloads_failed: int
    success_rate: float | None
    bytes: int
    median_sec: float | None
    flagged_accounts: int


class OverviewOut(BaseModel):
    range: RangeOut
    generated_at: str
    summary: SummaryOut
    signups: SignupsOut
    active_users: ActiveUsersOut
    downloads: DownloadsOut
    timing: TimingOut
    accounts: AccountsOut
    funnels: FunnelsOut
    retention: RetentionOut


class WhoAmI(BaseModel):
    id: str
    email: str | None
    role: str = Field("admin", description="Always 'admin'; the route refuses anyone else.")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/whoami", response_model=WhoAmI, summary="Confirm this token is an admin")
async def whoami(user: Annotated[User, Depends(require_admin)]) -> WhoAmI:
    """A cheap probe the dashboard uses to decide whether to render at all."""
    return WhoAmI(id=user.id, email=user.email)


@router.get("/overview", response_model=OverviewOut, summary="Everything, in one request")
async def overview(rng: RangeDep, analytics: AnalyticsDep) -> OverviewOut:
    """The whole dashboard on one connection.

    The page asks one question and gets one answer, so its halves cannot show
    numbers from two different moments.
    """
    data = await run_in_threadpool(analytics.overview, rng)
    return OverviewOut.model_validate(data)


@router.get("/signups", response_model=SignupsOut, summary="Sign-ups per day, by quality")
async def signups(rng: RangeDep, analytics: AnalyticsDep) -> SignupsOut:
    """Accounts created per day, split verified / unverified, plus attempts the
    disposable-domain and MX checks refused before an account existed."""
    return SignupsOut.model_validate(await run_in_threadpool(analytics.signups, rng))


@router.get("/active-users", response_model=ActiveUsersOut, summary="Daily and weekly actives")
async def active_users(rng: RangeDep, analytics: AnalyticsDep) -> ActiveUsersOut:
    """Anyone who started a download: the account when signed in, the browser otherwise."""
    return ActiveUsersOut.model_validate(await run_in_threadpool(analytics.active_users, rng))


@router.get("/downloads", response_model=DownloadsOut, summary="Downloads, success rate, errors")
async def downloads(rng: RangeDep, analytics: AnalyticsDep) -> DownloadsOut:
    return DownloadsOut.model_validate(await run_in_threadpool(analytics.downloads, rng))


@router.get("/timing", response_model=TimingOut, summary="How long people waited")
async def timing(rng: RangeDep, analytics: AnalyticsDep) -> TimingOut:
    return TimingOut.model_validate(await run_in_threadpool(analytics.timing, rng))


@router.get("/accounts", response_model=AccountsOut, summary="Top email domains, flagged accounts")
async def accounts(rng: RangeDep, analytics: AnalyticsDep) -> AccountsOut:
    return AccountsOut.model_validate(await run_in_threadpool(analytics.accounts, rng))


@router.get(
    "/funnels", response_model=FunnelsOut, summary="Sign-up to verified to download to return"
)
async def funnels(rng: RangeDep, analytics: AnalyticsDep) -> FunnelsOut:
    return FunnelsOut.model_validate(await run_in_threadpool(analytics.funnels, rng))


@router.get("/retention", response_model=RetentionOut, summary="Is the 90-day prune running?")
async def retention(analytics: AnalyticsDep) -> RetentionOut:
    return RetentionOut.model_validate(await run_in_threadpool(analytics.retention))
