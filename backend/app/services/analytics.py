"""Read-only aggregates for the admin dashboard (Phase 5).

Everything here answers one question: "how many real users did I get this week
and what did they download". The source of truth is this project's own database
- `events` for activity, `profiles` for accounts, `downloads` for the work - not
a third-party analytics product.

Two rules shaped the code:

**Aggregate in SQL.** Every number below is produced by a `GROUP BY` or a
scalar aggregate. Nothing pulls rows into Python to count them, because the
events table grows without bound and the dashboard is loaded from a phone. The
only rows that ever cross the wire are the ones actually rendered: at most a
handful of flagged accounts, and two values in the middle of a sorted list when
a median is needed.

**Run on SQLite too.** Production is Supabase Postgres, but development and the
test suite are SQLite, and an admin endpoint that cannot be tested is an admin
endpoint that breaks quietly. The migration's `admin_signups_daily` and
`admin_downloads_daily` views are Postgres-only (they read `auth.users`), so
they are deliberately not used here. Instead, the four expressions that really
differ between the two engines - truncating a timestamp to a day, subtracting
two timestamps, reading a JSON property, splitting an email domain - are
isolated in the small helpers at the top of this file and everything else is
plain portable SQL.

Privacy: no raw IP address is ever selected (the column only holds a salted
hash, and even that is not exposed), no full URL exists in the database to
begin with, and the one place an operator needs to identify a person - the
flagged-accounts table - returns a masked address, never the real one.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Select,
    String,
    and_,
    case,
    cast,
    distinct,
    func,
    literal_column,
    or_,
    select,
)
from sqlalchemy.orm import Session, sessionmaker

from app.db import session_scope
from app.models import Download, Event, Profile

# Raw events are kept this long. Enforced by public.prune_old_events(), which
# .github/workflows/prune-events.yml calls every night. The dashboard reports
# how many rows are already past it, so a job that silently stopped is visible.
EVENT_RETENTION_DAYS = 90

DEFAULT_RANGE_DAYS = 7
MAX_RANGE_DAYS = 365

# Risk values that mean "look at this account", from profiles.email_risk.
FLAGGED_RISKS = ("disposable", "no_mx", "bounced")

# How long a user has to come back before the seven-day return window closes.
RETURN_WINDOW_DAYS = 7

_DAY = 86_400.0


# ---------------------------------------------------------------------------
# Dialect differences, in one place
# ---------------------------------------------------------------------------


def dialect_of(session: Session) -> str:
    bind = session.get_bind()
    return bind.dialect.name


def _day(col: ColumnElement, dialect: str) -> ColumnElement:
    """The UTC calendar day of a timestamp, as 'YYYY-MM-DD'.

    Postgres stores timestamptz, so the zone is pinned explicitly rather than
    left to the session's TimeZone setting. SQLite stores naive UTC text.
    """
    if dialect == "postgresql":
        return func.to_char(func.timezone(literal_column("'UTC'"), col), "YYYY-MM-DD")
    return func.strftime("%Y-%m-%d", col)


def _seconds_between(start: ColumnElement, end: ColumnElement, dialect: str) -> ColumnElement:
    """`end - start` in seconds, as a float."""
    if dialect == "postgresql":
        return func.extract("epoch", end) - func.extract("epoch", start)
    return (func.julianday(end) - func.julianday(start)) * _DAY


def _json_text(col: ColumnElement, key: str, dialect: str) -> ColumnElement:
    """A string property of the events.properties document.

    `jsonb_extract_path_text` is used rather than the `->>` operator because a
    bound parameter next to `->>` is ambiguous to Postgres (int and text
    overloads both exist); a function call is not.
    """
    if dialect == "postgresql":
        return func.jsonb_extract_path_text(col, key)
    return func.json_extract(col, f"$.{key}")


def _json_is_true(col: ColumnElement, key: str, dialect: str) -> ColumnElement:
    """A boolean property. Postgres gives back 'true'; SQLite gives back 1."""
    if dialect == "postgresql":
        return func.jsonb_extract_path_text(col, key) == "true"
    return func.json_extract(col, f"$.{key}") == 1


def _email_domain(col: ColumnElement, dialect: str) -> ColumnElement:
    if dialect == "postgresql":
        return func.lower(func.split_part(col, "@", 2))
    return func.lower(func.substr(col, func.instr(col, "@") + 1))


def _count_if(condition: ColumnElement) -> ColumnElement:
    """`count(*) filter (where ...)` without the Postgres-only syntax."""
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


def _actor(dialect: str) -> ColumnElement:
    """Who did this download: the account when signed in, the browser otherwise.

    Guests are most of the traffic before sign-up exists, so counting only
    `user_id` would report zero active users on a day that was actually busy.
    """
    return func.coalesce(cast(Download.user_id, String), Download.client_id)


def mask_email(email: str | None) -> str:
    """`john.doe@example.com` -> `j***@example.com`.

    The domain is the part an operator judges an account by; the local part is
    the part that identifies a person, so only the domain survives.
    """
    if not email or "@" not in email:
        return "(no address)"
    local, _, domain = email.partition("@")
    head = local[0] if local else "?"
    return f"{head}***@{domain.lower()}"


# ---------------------------------------------------------------------------
# Date range
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DateRange:
    """A half-open window of whole UTC days: [start, end)."""

    start: datetime
    end: datetime
    now: datetime

    @property
    def days(self) -> int:
        return max(1, round((self.end - self.start).total_seconds() / _DAY))

    @property
    def first_day(self) -> date:
        return self.start.date()

    @property
    def last_day(self) -> date:
        return (self.end - timedelta(seconds=1)).date()

    def labels(self) -> list[str]:
        """Every day in the window, so a chart has no holes where nothing happened."""
        return [(self.first_day + timedelta(days=i)).isoformat() for i in range(self.days)]

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.first_day.isoformat(),
            "end": self.last_day.isoformat(),
            "days": self.days,
        }


def _midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def resolve_range(
    days: int | None = None,
    start: date | None = None,
    end: date | None = None,
    now: datetime | None = None,
) -> DateRange:
    """Turn the query string into a window of whole UTC days.

    `from`/`to` win when given (both inclusive). Otherwise the last `days` days
    ending today. Anything longer than a year is clamped: the point of the
    dashboard is this week, and an unbounded range is an easy way to make the
    database work hard on request.
    """
    now = now or datetime.now(UTC)
    today = now.date()
    last = min(end or today, today)
    if start is not None:
        first = start
    else:
        span = min(max(days or DEFAULT_RANGE_DAYS, 1), MAX_RANGE_DAYS)
        first = last - timedelta(days=span - 1)
    if first > last:
        first = last
    if (last - first).days + 1 > MAX_RANGE_DAYS:
        first = last - timedelta(days=MAX_RANGE_DAYS - 1)
    return DateRange(start=_midnight(first), end=_midnight(last) + timedelta(days=1), now=now)


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------


class Analytics:
    """Aggregate queries behind the admin API. Reads only; writes nothing."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    # -- public sections, one session each ---------------------------------

    def signups(self, rng: DateRange) -> dict:
        with session_scope(self._sessions) as s:
            return self._signups(s, rng)

    def active_users(self, rng: DateRange) -> dict:
        with session_scope(self._sessions) as s:
            return self._active_users(s, rng)

    def downloads(self, rng: DateRange) -> dict:
        with session_scope(self._sessions) as s:
            return self._downloads(s, rng)

    def timing(self, rng: DateRange) -> dict:
        with session_scope(self._sessions) as s:
            return self._timing(s, rng)

    def accounts(self, rng: DateRange) -> dict:
        with session_scope(self._sessions) as s:
            return self._accounts(s, rng)

    def funnels(self, rng: DateRange) -> dict:
        with session_scope(self._sessions) as s:
            return self._funnels(s, rng)

    def retention(self) -> dict:
        with session_scope(self._sessions) as s:
            return self._retention(s)

    def overview(self, rng: DateRange) -> dict:
        """Everything the dashboard draws, in one round trip on one connection."""
        with session_scope(self._sessions) as s:
            signups = self._signups(s, rng)
            active = self._active_users(s, rng)
            downloads = self._downloads(s, rng)
            timing = self._timing(s, rng)
            accounts = self._accounts(s, rng)
            funnels = self._funnels(s, rng)
            retention = self._retention(s)
        return {
            "range": rng.as_dict(),
            "generated_at": rng.now.isoformat(),
            "summary": _summary(signups, active, downloads, timing, accounts),
            "signups": signups,
            "active_users": active,
            "downloads": downloads,
            "timing": timing,
            "accounts": accounts,
            "funnels": funnels,
            "retention": retention,
        }

    # -- sign-ups -----------------------------------------------------------

    def _verified_user_ids(self, dialect: str) -> Select:
        """Accounts we have seen proof of email verification for.

        The API does not write an `email_verified` event, but every token it
        checks carries the flag, so `signin` events record it and a `signup`
        that returned a session records `confirmed`. On Postgres the ground
        truth is `auth.users.email_confirmed_at`; that table is Supabase-only,
        and reading it here would make this whole module untestable, so the
        events are used on both engines and the definition stays one thing.
        """
        return (
            select(Event.user_id)
            .where(
                Event.user_id.is_not(None),
                or_(
                    and_(
                        Event.name == "signin", _json_is_true(Event.properties, "verified", dialect)
                    ),
                    and_(
                        Event.name == "signup",
                        _json_is_true(Event.properties, "confirmed", dialect),
                    ),
                ),
            )
            .distinct()
        )

    def _signups(self, s: Session, rng: DateRange) -> dict:
        d = dialect_of(s)
        day = _day(Profile.created_at, d)
        verified = self._verified_user_ids(d)

        accepted = s.execute(
            select(
                day.label("day"),
                func.count().label("total"),
                _count_if(Profile.id.in_(verified)).label("verified"),
                _count_if(Profile.email_risk.in_(FLAGGED_RISKS)).label("flagged"),
            )
            .where(Profile.created_at >= rng.start, Profile.created_at < rng.end)
            .group_by(day)
        ).all()

        # Attempts the email checks turned away at the door. They never became
        # profiles, so they only exist as events.
        reason = _json_text(Event.properties, "reason", d)
        reject_day = _day(Event.created_at, d)
        refused = s.execute(
            select(reject_day.label("day"), reason.label("reason"), func.count().label("n"))
            .where(
                Event.name == "signup_rejected",
                Event.created_at >= rng.start,
                Event.created_at < rng.end,
            )
            .group_by(reject_day, reason)
        ).all()

        by_day = {
            row.day: {
                "day": row.day,
                "total": int(row.total),
                "verified": int(row.verified),
                "unverified": int(row.total) - int(row.verified),
                "flagged": int(row.flagged),
                "disposable": 0,
                "no_mx": 0,
                "refused": 0,
            }
            for row in accepted
        }
        blank = {
            "total": 0,
            "verified": 0,
            "unverified": 0,
            "flagged": 0,
            "disposable": 0,
            "no_mx": 0,
            "refused": 0,
        }
        for row in refused:
            entry = by_day.setdefault(row.day, {"day": row.day, **blank})
            entry["refused"] += int(row.n)
            if row.reason in ("disposable", "no_mx"):
                entry[row.reason] += int(row.n)

        daily = [by_day.get(label, {"day": label, **blank}) for label in rng.labels()]
        totals = {
            key: sum(item[key] for item in daily)
            for key in (
                "total",
                "verified",
                "unverified",
                "flagged",
                "disposable",
                "no_mx",
                "refused",
            )
        }
        return {"daily": daily, "totals": totals}

    # -- active users -------------------------------------------------------

    def _active_users(self, s: Session, rng: DateRange) -> dict:
        """Who used the product, counting guests as well as accounts.

        A "user" here is whoever started a download: the account when signed in,
        otherwise the browser's client id. Weekly and monthly figures use the
        seven and thirty days ending with the range, not the range itself, so
        they mean the same thing whichever window is on screen.
        """
        d = dialect_of(s)
        actor = _actor(d)
        day = _day(Download.created_at, d)

        rows = s.execute(
            select(
                day.label("day"),
                func.count(distinct(actor)).label("total"),
                func.count(distinct(Download.user_id)).label("signed_in"),
            )
            .where(Download.created_at >= rng.start, Download.created_at < rng.end)
            .group_by(day)
        ).all()
        seen = {
            row.day: {
                "day": row.day,
                "total": int(row.total),
                "signed_in": int(row.signed_in),
                "guests": int(row.total) - int(row.signed_in),
            }
            for row in rows
        }
        daily = [
            seen.get(label, {"day": label, "total": 0, "signed_in": 0, "guests": 0})
            for label in rng.labels()
        ]

        def unique_over(days: int) -> tuple[int, int]:
            since = rng.end - timedelta(days=days)
            row = s.execute(
                select(
                    func.count(distinct(actor)),
                    func.count(distinct(Download.user_id)),
                ).where(Download.created_at >= since, Download.created_at < rng.end)
            ).one()
            return int(row[0] or 0), int(row[1] or 0)

        wau, wau_signed_in = unique_over(7)
        mau, _ = unique_over(30)
        in_range, in_range_signed_in = unique_over(rng.days)

        dau = daily[-1]["total"] if daily else 0
        avg_dau = round(sum(item["total"] for item in daily) / max(len(daily), 1), 1)
        return {
            "daily": daily,
            "dau": dau,
            "avg_dau": avg_dau,
            "wau": wau,
            "wau_signed_in": wau_signed_in,
            "mau": mau,
            "in_range": in_range,
            "in_range_signed_in": in_range_signed_in,
            "stickiness": round(avg_dau / wau, 2) if wau else 0.0,
        }

    # -- downloads ----------------------------------------------------------

    def _downloads(self, s: Session, rng: DateRange) -> dict:
        d = dialect_of(s)
        day = _day(Download.created_at, d)
        in_range = (Download.created_at >= rng.start, Download.created_at < rng.end)

        done = Download.status == "done"
        failed = Download.status == "error"
        cancelled = Download.status == "cancelled"

        rows = s.execute(
            select(
                day.label("day"),
                func.count().label("total"),
                _count_if(done).label("done"),
                _count_if(failed).label("failed"),
                _count_if(cancelled).label("cancelled"),
                _count_if(Download.mode == "audio").label("audio"),
                _count_if(Download.mode == "video").label("video"),
            )
            .where(*in_range)
            .group_by(day)
        ).all()
        seen = {
            row.day: {
                "day": row.day,
                "total": int(row.total),
                "done": int(row.done),
                "failed": int(row.failed),
                "cancelled": int(row.cancelled),
                "audio": int(row.audio),
                "video": int(row.video),
            }
            for row in rows
        }
        blank = {"total": 0, "done": 0, "failed": 0, "cancelled": 0, "audio": 0, "video": 0}
        daily = [seen.get(label, {"day": label, **blank}) for label in rng.labels()]

        by_format = [
            {
                "mode": row.mode,
                "format": row.format,
                "quality": row.quality,
                "total": int(row.total),
                "done": int(row.done),
                "bytes": int(row.bytes or 0),
            }
            for row in s.execute(
                select(
                    Download.mode,
                    Download.format,
                    Download.quality,
                    func.count().label("total"),
                    _count_if(done).label("done"),
                    func.coalesce(func.sum(case((done, Download.size_bytes), else_=0)), 0).label(
                        "bytes"
                    ),
                )
                .where(*in_range)
                .group_by(Download.mode, Download.format, Download.quality)
                .order_by(func.count().desc())
                .limit(20)
            ).all()
        ]

        errors = [
            {"code": row.error_code or "unknown", "count": int(row.n)}
            for row in s.execute(
                select(Download.error_code, func.count().label("n"))
                .where(*in_range, failed)
                .group_by(Download.error_code)
                .order_by(func.count().desc())
                .limit(8)
            ).all()
        ]

        totals_row = s.execute(
            select(
                func.count().label("total"),
                _count_if(done).label("done"),
                _count_if(failed).label("failed"),
                _count_if(cancelled).label("cancelled"),
                _count_if(Download.mode == "audio").label("audio"),
                _count_if(Download.mode == "video").label("video"),
                _count_if(Download.playlist_job_id.is_not(None)).label("from_playlists"),
                func.coalesce(func.sum(case((done, Download.size_bytes), else_=0)), 0).label(
                    "bytes"
                ),
            ).where(*in_range)
        ).one()

        settled = int(totals_row.done) + int(totals_row.failed)
        totals = {
            "total": int(totals_row.total),
            "done": int(totals_row.done),
            "failed": int(totals_row.failed),
            "cancelled": int(totals_row.cancelled),
            "audio": int(totals_row.audio),
            "video": int(totals_row.video),
            "from_playlists": int(totals_row.from_playlists),
            "bytes": int(totals_row.bytes or 0),
            # Cancelled jobs are the user changing their mind, not a failure, so
            # they are left out of the rate rather than counted against it.
            "success_rate": round(100.0 * int(totals_row.done) / settled, 1) if settled else None,
        }
        return {"daily": daily, "by_format": by_format, "errors": errors, "totals": totals}

    # -- timing -------------------------------------------------------------

    def _timing(self, s: Session, rng: DateRange) -> dict:
        """How long a finished download made someone wait, start to file ready.

        The median is taken with `ORDER BY ... LIMIT/OFFSET` rather than
        `percentile_cont`, which SQLite does not have. At most two rows are
        read, so it stays a database job on both engines.
        """
        d = dialect_of(s)
        seconds = _seconds_between(Download.created_at, Download.finished_at, d)
        where = (
            Download.created_at >= rng.start,
            Download.created_at < rng.end,
            Download.status == "done",
            Download.finished_at.is_not(None),
        )

        summary = s.execute(
            select(
                func.count().label("n"),
                func.min(seconds).label("fastest"),
                func.max(seconds).label("slowest"),
                func.avg(seconds).label("mean"),
            ).where(*where)
        ).one()
        n = int(summary.n or 0)
        if n == 0:
            return {
                "samples": 0,
                "median_sec": None,
                "p90_sec": None,
                "fastest_sec": None,
                "slowest_sec": None,
                "mean_sec": None,
            }

        ordered = select(seconds.label("s")).where(*where).order_by(seconds)

        def at(index: int, take: int = 1) -> list[float]:
            return [float(v) for v in s.scalars(ordered.offset(index).limit(take)).all()]

        middle = at((n - 1) // 2, 1 if n % 2 else 2)
        median = sum(middle) / len(middle) if middle else None
        p90_index = min(n - 1, max(0, math.ceil(0.9 * n) - 1))
        p90 = at(p90_index)

        return {
            "samples": n,
            "median_sec": round(median, 1) if median is not None else None,
            "p90_sec": round(p90[0], 1) if p90 else None,
            "fastest_sec": round(float(summary.fastest), 1),
            "slowest_sec": round(float(summary.slowest), 1),
            "mean_sec": round(float(summary.mean), 1),
        }

    # -- accounts -----------------------------------------------------------

    def _accounts(self, s: Session, rng: DateRange) -> dict:
        d = dialect_of(s)
        verified = self._verified_user_ids(d)
        domain = _email_domain(Profile.email, d)

        domains = [
            {
                "domain": row.domain or "(unknown)",
                "accounts": int(row.accounts),
                "verified": int(row.verified),
                "flagged": int(row.flagged),
            }
            for row in s.execute(
                select(
                    domain.label("domain"),
                    func.count().label("accounts"),
                    _count_if(Profile.id.in_(verified)).label("verified"),
                    _count_if(Profile.email_risk.in_(FLAGGED_RISKS)).label("flagged"),
                )
                .where(Profile.created_at >= rng.start, Profile.created_at < rng.end)
                .group_by(domain)
                .order_by(func.count().desc(), domain)
                .limit(10)
            ).all()
        ]

        # Flagged accounts are not limited to the range: a risky account matters
        # until somebody deals with it, whatever week it appeared in.
        downloads_count = (
            select(func.count())
            .select_from(Download)
            .where(Download.user_id == Profile.id)
            .correlate(Profile)
            .scalar_subquery()
        )
        flagged = [
            {
                # The id, because banning an account (backend/scripts/ban.py)
                # needs it. The address is masked: the domain is the part an
                # operator judges by, the local part only identifies a person.
                "id": str(row.id),
                "email": mask_email(row.email),
                "risk": row.email_risk,
                "verified": bool(row.verified),
                "downloads": int(row.downloads),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in s.execute(
                select(
                    Profile.id,
                    Profile.email,
                    Profile.email_risk,
                    Profile.created_at,
                    Profile.id.in_(verified).label("verified"),
                    downloads_count.label("downloads"),
                )
                .where(Profile.email_risk.in_(FLAGGED_RISKS))
                .order_by(Profile.created_at.desc())
                .limit(20)
            ).all()
        ]

        totals_row = s.execute(
            select(
                func.count().label("accounts"),
                _count_if(Profile.id.in_(verified)).label("verified"),
                _count_if(Profile.role == "admin").label("admins"),
                _count_if(Profile.email_risk.in_(FLAGGED_RISKS)).label("flagged"),
            )
        ).one()

        return {
            "domains": domains,
            "flagged": flagged,
            "totals": {
                "accounts": int(totals_row.accounts),
                "verified": int(totals_row.verified),
                "admins": int(totals_row.admins),
                "flagged": int(totals_row.flagged),
            },
        }

    # -- funnels ------------------------------------------------------------

    def _funnels(self, s: Session, rng: DateRange) -> dict:
        """Sign-up to verified, verified to first download, first download to a return.

        The cohort is everyone who signed up inside the range, followed forward
        in time - so the last step counts people who came back, even if they
        came back after the range ended. The return step also reports how many
        of the cohort have had a full seven days to come back at all; without
        that, a cohort from yesterday would always look like nobody returned.
        """
        d = dialect_of(s)
        cohort = select(Profile.id).where(
            Profile.created_at >= rng.start, Profile.created_at < rng.end
        )
        cohort_ids = cohort.scalar_subquery()
        verified = self._verified_user_ids(d)

        signed_up = int(s.scalar(select(func.count()).select_from(cohort.subquery())) or 0)
        verified_n = int(
            s.scalar(
                select(func.count())
                .select_from(Profile)
                .where(
                    Profile.created_at >= rng.start,
                    Profile.created_at < rng.end,
                    Profile.id.in_(verified),
                )
            )
            or 0
        )

        first = (
            select(
                Download.user_id.label("user_id"),
                func.min(Download.created_at).label("first_at"),
            )
            .where(Download.user_id.is_not(None), Download.user_id.in_(cohort_ids))
            .group_by(Download.user_id)
            .subquery()
        )
        downloaded = int(s.scalar(select(func.count()).select_from(first)) or 0)

        age = _seconds_between(first.c.first_at, Download.created_at, d)
        returned = int(
            s.scalar(
                select(func.count(distinct(first.c.user_id)))
                .select_from(first)
                .join(Download, Download.user_id == first.c.user_id)
                .where(age >= _DAY, age <= RETURN_WINDOW_DAYS * _DAY)
            )
            or 0
        )
        cutoff = rng.now - timedelta(days=RETURN_WINDOW_DAYS)
        eligible = int(
            s.scalar(select(func.count()).select_from(first).where(first.c.first_at <= cutoff)) or 0
        )

        def pct(part: int, whole: int) -> float | None:
            return round(100.0 * part / whole, 1) if whole else None

        return {
            "cohort": rng.as_dict(),
            "steps": [
                {
                    "key": "signed_up",
                    "label": "Signed up",
                    "count": signed_up,
                    "of_previous": None,
                    "of_start": None,
                    "note": "Accounts created in this range.",
                },
                {
                    "key": "verified",
                    "label": "Verified email",
                    "count": verified_n,
                    "of_previous": pct(verified_n, signed_up),
                    "of_start": pct(verified_n, signed_up),
                    "note": "Seen signing in with a confirmed address.",
                },
                {
                    "key": "downloaded",
                    "label": "First download",
                    "count": downloaded,
                    "of_previous": pct(downloaded, verified_n),
                    "of_start": pct(downloaded, signed_up),
                    "note": "Only verified accounts are allowed to download.",
                },
                {
                    "key": "returned",
                    "label": f"Came back within {RETURN_WINDOW_DAYS} days",
                    "count": returned,
                    "of_previous": pct(returned, eligible),
                    "of_start": pct(returned, signed_up),
                    "note": (
                        f"Of {eligible} who have had a full {RETURN_WINDOW_DAYS} days to return."
                        if eligible
                        else f"Nobody in this cohort has had {RETURN_WINDOW_DAYS} days yet."
                    ),
                    "eligible": eligible,
                },
            ],
        }

    # -- retention ----------------------------------------------------------

    def _retention(self, s: Session) -> dict:
        """Whether the 90-day pruning job is actually running.

        `overdue` should always be zero. Anything else means
        .github/workflows/prune-events.yml has not run, and the raw activity log
        is keeping personal data longer than the privacy policy promises.
        """
        cutoff = datetime.now(UTC) - timedelta(days=EVENT_RETENTION_DAYS)
        row = s.execute(
            select(
                func.count().label("total"),
                func.min(Event.created_at).label("oldest"),
                _count_if(Event.created_at < cutoff).label("overdue"),
            )
        ).one()
        oldest = row.oldest
        return {
            "keep_days": EVENT_RETENTION_DAYS,
            "events": int(row.total),
            "oldest_event": oldest.isoformat() if oldest else None,
            "overdue": int(row.overdue),
        }

    # -- access control -----------------------------------------------------

    def role_of(self, user_id: str) -> str | None:
        """The caller's role, or None when they have no profile row.

        Read-only on purpose: the admin guard must not create anything, so an
        unknown id is simply refused instead of quietly becoming a 'user'.
        """
        try:
            uid = uuid.UUID(user_id)
        except (ValueError, AttributeError, TypeError):
            return None
        with session_scope(self._sessions) as s:
            return s.scalar(select(Profile.role).where(Profile.id == uid))


def _summary(signups: dict, active: dict, downloads: dict, timing: dict, accounts: dict) -> dict:
    """The five numbers that answer the exit question, derived from the sections.

    Derived rather than queried again: the sections have already paid for these
    aggregates, and running them twice would only invite the two halves of the
    page to disagree.
    """
    return {
        "signups": signups["totals"]["total"],
        "verified_signups": signups["totals"]["verified"],
        "refused_signups": signups["totals"]["refused"],
        "active_users": active["in_range"],
        "active_signed_in": active["in_range_signed_in"],
        "wau": active["wau"],
        "downloads": downloads["totals"]["total"],
        "downloads_done": downloads["totals"]["done"],
        "downloads_failed": downloads["totals"]["failed"],
        "success_rate": downloads["totals"]["success_rate"],
        "bytes": downloads["totals"]["bytes"],
        "median_sec": timing["median_sec"],
        "flagged_accounts": accounts["totals"]["flagged"],
    }
