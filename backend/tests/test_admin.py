"""The admin API: who may open it, and whether the numbers are right.

Two halves. The first proves the door: a stranger, a guest, an ordinary signed-in
user and a user whose profile row does not exist are all refused, and only
`role = 'admin'` gets in. The second seeds a known set of profiles, downloads and
events and checks that every figure the dashboard renders comes back exactly as
counted by hand - including the medians, the funnels, and the privacy promise
that no unmasked email address leaves the server.

Everything runs on SQLite, which is the point: the Postgres-only admin views in
supabase/migrations are deliberately unused so these endpoints stay testable.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import Base, make_engine, make_session_factory, session_scope
from app.main import app
from app.models import Download, Event, Profile
from app.services.analytics import Analytics, mask_email, resolve_range
from tests.test_api import StubDownloader

SECRET = "admin-test-secret"

ADMIN_ID = "11111111-1111-4111-8111-111111111111"
USER_ID = "22222222-2222-4222-8222-222222222222"
GHOST_ID = "33333333-3333-4333-8333-333333333333"  # a token with no profile row

# The seeded world is placed relative to the real clock, because the endpoints
# resolve "the last 7 days" against it and a frozen date would drift out of range.
NOW = datetime.now(UTC)


def _token(uid: str, verified: bool = True, email: str = "someone@example.com") -> str:
    return jwt.encode(
        {
            "sub": uid,
            "email": email,
            "aud": "authenticated",
            "role": "authenticated",
            "user_metadata": {"email_verified": verified},
            "exp": int(time.time()) + 600,
        },
        SECRET,
        algorithm="HS256",
    )


def _bearer(uid: str, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(uid, **kw)}"}


def _day(offset: int) -> datetime:
    """`offset` days before NOW, at 09:00 UTC so the day never rolls over."""
    return (NOW - timedelta(days=offset)).replace(hour=9, minute=0, second=0, microsecond=0)


def _seed(session_factory) -> None:
    """A small world with one of everything the dashboard reports.

    Laid out relative to NOW so the assertions below can be read as sentences:
    two accounts sign up 2 days ago, one of them verifies and downloads and comes
    back on day 0; a disposable address is turned away; a guest browser does most
    of the downloading; one download fails and one is cancelled.
    """
    with session_scope(session_factory) as s:
        s.add_all(
            [
                Profile(
                    id=uuid.UUID(ADMIN_ID),
                    email="Boss@Example.com",
                    role="admin",
                    created_at=_day(2),
                ),
                Profile(
                    id=uuid.UUID(USER_ID),
                    email="normal@example.com",
                    role="user",
                    email_risk="ok",
                    created_at=_day(2),
                ),
                # Signed up outside the default 7-day window, and flagged.
                Profile(
                    id=uuid.UUID("44444444-4444-4444-8444-444444444444"),
                    email="spammer@mailinator.com",
                    role="user",
                    email_risk="disposable",
                    created_at=_day(40),
                ),
            ]
        )

        # Only the admin ever proved a verified email (a signin event carrying it).
        s.add_all(
            [
                Event(
                    user_id=uuid.UUID(ADMIN_ID),
                    name="signin",
                    properties={"verified": True, "claimed": 0},
                    created_at=_day(2),
                ),
                Event(
                    user_id=uuid.UUID(USER_ID),
                    name="signin",
                    properties={"verified": False, "claimed": 0},
                    created_at=_day(2),
                ),
                # An attempt the disposable-domain check refused: no profile exists.
                Event(
                    name="signup_rejected",
                    properties={"reason": "disposable", "domain": "trashmail.test"},
                    created_at=_day(1),
                ),
                Event(
                    name="signup_rejected",
                    properties={"reason": "no_mx", "domain": "nowhere.invalid"},
                    created_at=_day(1),
                ),
                # Older than the 90-day retention promise: proves `overdue` works.
                Event(name="download_started", properties={}, created_at=NOW - timedelta(days=200)),
            ]
        )

        def dl(**kw) -> Download:
            base = dict(
                video_id="dQw4w9WgXcQ",
                mode="audio",
                format="mp3",
                quality="192",
                status="done",
                size_bytes=1000,
            )
            base.update(kw)
            return Download(id=uuid.uuid4(), **base)

        s.add_all(
            [
                # The admin: first download 2 days ago, back again today. That is
                # the whole seven-day-return funnel step in two rows.
                dl(
                    user_id=uuid.UUID(ADMIN_ID),
                    created_at=_day(2),
                    finished_at=_day(2) + timedelta(seconds=10),
                ),
                dl(
                    user_id=uuid.UUID(ADMIN_ID),
                    created_at=_day(0),
                    finished_at=_day(0) + timedelta(seconds=30),
                ),
                # A guest browser: three jobs, one of each ending.
                dl(
                    client_id="guest-browser-1",
                    created_at=_day(1),
                    finished_at=_day(1) + timedelta(seconds=20),
                    mode="video",
                    format="mp4",
                    quality="1080",
                    size_bytes=5000,
                ),
                dl(
                    client_id="guest-browser-1",
                    created_at=_day(1),
                    finished_at=_day(1) + timedelta(seconds=5),
                    status="error",
                    error_code="network",
                    size_bytes=None,
                ),
                dl(
                    client_id="guest-browser-2",
                    created_at=_day(1),
                    finished_at=_day(1),
                    status="cancelled",
                    size_bytes=None,
                ),
                # Outside the default 7-day window but inside the month, so the
                # range handling and the monthly figure are both exercised.
                dl(client_id="guest-browser-3", created_at=_day(20), finished_at=_day(20)),
            ]
        )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("DM_SUPABASE_URL", "https://proj.supabase.test")
    monkeypatch.setenv("DM_SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setenv("DM_REQUIRE_AUTH", "false")
    get_settings.cache_clear()
    with TestClient(app) as c:
        app.state.downloader = StubDownloader()
        app.state.jobs._downloader = StubDownloader()
        # A private database file per test, so the seeded world is exactly this
        # world. A file rather than `sqlite://`: the routes hand their queries to
        # a worker thread, and an in-memory database is not shared across threads.
        engine = make_engine(f"sqlite:///{(tmp_path / 'admin.db').as_posix()}")
        Base.metadata.create_all(engine)
        factory = make_session_factory(engine)
        _seed(factory)
        app.state.analytics = Analytics(factory)
        yield c
        engine.dispose()
    get_settings.cache_clear()


def _get(client: TestClient, path: str, uid: str = ADMIN_ID, **params) -> dict:
    r = client.get(f"/api/v1/admin/{path}", headers=_bearer(uid), params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# The door
# ---------------------------------------------------------------------------

ROUTES = [
    "overview",
    "signups",
    "active-users",
    "downloads",
    "timing",
    "accounts",
    "funnels",
    "retention",
    "whoami",
]


@pytest.mark.parametrize("route", ROUTES)
def test_anonymous_is_401(client: TestClient, route: str) -> None:
    assert client.get(f"/api/v1/admin/{route}").status_code == 401


@pytest.mark.parametrize("route", ROUTES)
def test_ordinary_user_is_403(client: TestClient, route: str) -> None:
    """A perfectly valid, verified, signed-in account is still not an admin."""
    r = client.get(f"/api/v1/admin/{route}", headers=_bearer(USER_ID))
    assert r.status_code == 403
    assert r.json()["detail"] == "Admins only."


def test_unknown_profile_is_403(client: TestClient) -> None:
    """A real token for someone with no profile row gets in nowhere, and stays a stranger."""
    assert client.get("/api/v1/admin/overview", headers=_bearer(GHOST_ID)).status_code == 403
    assert app.state.analytics.role_of(GHOST_ID) is None  # the check created nothing


def test_bad_token_is_401(client: TestClient) -> None:
    r = client.get("/api/v1/admin/overview", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401


def test_client_id_header_is_not_a_way_in(client: TestClient) -> None:
    """The anonymous browser identity carries no authority at all."""
    r = client.get("/api/v1/admin/overview", headers={"X-Client-Id": "guest-browser-1"})
    assert r.status_code == 401


def test_admin_gets_in(client: TestClient) -> None:
    body = _get(client, "whoami")
    assert body == {"id": ADMIN_ID, "email": "someone@example.com", "role": "admin"}


def test_demoting_an_admin_closes_the_door_immediately(client: TestClient) -> None:
    """The role is read per request, so no redeploy or new token is needed."""
    assert client.get("/api/v1/admin/whoami", headers=_bearer(ADMIN_ID)).status_code == 200
    with session_scope(app.state.analytics._sessions) as s:
        s.get(Profile, uuid.UUID(ADMIN_ID)).role = "user"
    assert client.get("/api/v1/admin/whoami", headers=_bearer(ADMIN_ID)).status_code == 403


# ---------------------------------------------------------------------------
# The numbers
# ---------------------------------------------------------------------------


def test_overview_is_one_coherent_answer(client: TestClient) -> None:
    body = _get(client, "overview", days=7)
    assert body["range"]["days"] == 7
    # The summary is derived from the sections, so the two must agree.
    assert body["summary"]["downloads"] == body["downloads"]["totals"]["total"]
    assert body["summary"]["signups"] == body["signups"]["totals"]["total"]
    assert body["summary"]["wau"] == body["active_users"]["wau"]
    assert body["summary"]["median_sec"] == body["timing"]["median_sec"]


def test_signups_split_by_quality(client: TestClient) -> None:
    body = _get(client, "signups", days=7)
    totals = body["totals"]
    assert totals["total"] == 2  # the 40-day-old spammer is outside the window
    assert totals["verified"] == 1  # only the admin has a verified signin event
    assert totals["unverified"] == 1
    assert totals["disposable"] == 1  # refused before an account existed
    assert totals["no_mx"] == 1
    assert totals["refused"] == 2
    # Every day in the range is present, so a chart has no holes.
    assert len(body["daily"]) == 7
    assert [d["day"] for d in body["daily"]] == sorted(d["day"] for d in body["daily"])
    assert sum(d["total"] for d in body["daily"]) == 2


def test_a_longer_range_reaches_the_older_signup(client: TestClient) -> None:
    assert _get(client, "signups", days=60)["totals"]["total"] == 3


def test_explicit_from_and_to_win_over_days(client: TestClient) -> None:
    day1 = (NOW - timedelta(days=1)).date().isoformat()
    body = _get(client, "downloads", days=365, **{"from": day1, "to": day1})
    assert body["totals"]["total"] == 3  # the three guest jobs on that one day
    assert len(body["daily"]) == 1


def test_downloads_success_rate_and_errors(client: TestClient) -> None:
    body = _get(client, "downloads", days=7)
    totals = body["totals"]
    assert totals["total"] == 5
    assert (totals["done"], totals["failed"], totals["cancelled"]) == (3, 1, 1)
    # Cancelled is the user changing their mind, so it is out of the rate: 3/4.
    assert totals["success_rate"] == 75.0
    assert totals["audio"] == 4 and totals["video"] == 1
    assert totals["bytes"] == 1000 + 1000 + 5000
    assert body["errors"] == [{"code": "network", "count": 1}]
    formats = {(r["mode"], r["format"]): r for r in body["by_format"]}
    assert formats[("video", "mp4")]["total"] == 1
    assert formats[("audio", "mp3")]["total"] == 4


def test_active_users_count_guests_as_well_as_accounts(client: TestClient) -> None:
    body = _get(client, "active-users", days=7)
    # In range: the admin plus two guest browsers.
    assert body["in_range"] == 3
    assert body["in_range_signed_in"] == 1
    assert body["wau"] == 3
    assert body["mau"] == 4  # plus the browser that only appears 20 days back
    by_day = {d["day"]: d for d in body["daily"]}
    yesterday = (NOW - timedelta(days=1)).date().isoformat()
    assert by_day[yesterday] == {
        "day": yesterday,
        "total": 2,
        "signed_in": 0,
        "guests": 2,
    }


def test_median_time_to_file_ready(client: TestClient) -> None:
    """Three finished jobs in range at 10s, 20s and 30s: the median is the middle one."""
    body = _get(client, "timing", days=7)
    assert body["samples"] == 3
    assert body["median_sec"] == 20.0
    assert body["fastest_sec"] == 10.0
    assert body["slowest_sec"] == 30.0
    assert body["p90_sec"] == 30.0


def test_median_of_an_even_number_of_samples(client: TestClient) -> None:
    """Two finished jobs, 10s and 20s: the median is the average of the pair."""
    body = _get(
        client,
        "timing",
        **{
            "from": (NOW - timedelta(days=2)).date().isoformat(),
            "to": (NOW - timedelta(days=1)).date().isoformat(),
        },
    )
    assert body["samples"] == 2
    assert body["median_sec"] == 15.0


def test_timing_with_nothing_finished_is_empty_not_an_error(client: TestClient) -> None:
    old = (NOW - timedelta(days=300)).date().isoformat()
    body = _get(client, "timing", **{"from": old, "to": old})
    assert body == {
        "samples": 0,
        "median_sec": None,
        "p90_sec": None,
        "fastest_sec": None,
        "slowest_sec": None,
        "mean_sec": None,
    }


def test_accounts_mask_addresses_and_list_domains(client: TestClient) -> None:
    body = _get(client, "accounts", days=60)
    assert body["totals"] == {"accounts": 3, "verified": 1, "admins": 1, "flagged": 1}
    domains = {d["domain"]: d for d in body["domains"]}
    assert domains["example.com"]["accounts"] == 2
    assert domains["example.com"]["verified"] == 1
    assert domains["mailinator.com"]["flagged"] == 1
    flagged = body["flagged"]
    assert len(flagged) == 1
    assert flagged[0]["risk"] == "disposable"
    assert flagged[0]["email"] == "s***@mailinator.com"
    assert flagged[0]["downloads"] == 0


def test_no_raw_email_or_ip_ever_reaches_the_client(client: TestClient) -> None:
    """The privacy promise, checked against the whole serialised payload."""
    raw = client.get("/api/v1/admin/overview", headers=_bearer(ADMIN_ID), params={"days": 365}).text
    assert "spammer@mailinator.com" not in raw
    assert "normal@example.com" not in raw
    assert "ip_hash" not in raw
    assert "s***@mailinator.com" in raw


def test_flagged_accounts_are_not_hidden_by_the_date_range(client: TestClient) -> None:
    """A risky account matters until somebody deals with it, whatever week it arrived."""
    assert len(_get(client, "accounts", days=1)["flagged"]) == 1


def test_funnel_follows_the_cohort_forward(client: TestClient) -> None:
    steps = {s["key"]: s for s in _get(client, "funnels", days=7)["steps"]}
    assert steps["signed_up"]["count"] == 2
    assert steps["verified"]["count"] == 1
    assert steps["verified"]["of_previous"] == 50.0
    assert steps["downloaded"]["count"] == 1
    assert steps["downloaded"]["of_previous"] == 100.0
    # The admin's first download was 2 days ago and they came back today, but
    # the seven-day window has not closed, so nobody is eligible yet.
    assert steps["returned"]["eligible"] == 0
    assert steps["returned"]["count"] == 1


def test_funnel_with_an_empty_cohort_does_not_divide_by_zero(client: TestClient) -> None:
    old = (NOW - timedelta(days=300)).date().isoformat()
    steps = {s["key"]: s for s in _get(client, "funnels", **{"from": old, "to": old})["steps"]}
    assert steps["signed_up"]["count"] == 0
    assert steps["verified"]["of_previous"] is None


def test_retention_reports_events_past_the_90_day_promise(client: TestClient) -> None:
    body = _get(client, "retention")
    assert body["keep_days"] == 90
    assert body["events"] == 5
    assert body["overdue"] == 1  # the seeded 200-day-old row; the prune job clears it


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------


def test_mask_email_keeps_the_domain_and_drops_the_person() -> None:
    assert mask_email("john.doe@Example.COM") == "j***@example.com"
    assert mask_email("a@b.io") == "a***@b.io"
    assert mask_email(None) == "(no address)"
    assert mask_email("not-an-address") == "(no address)"


def test_resolve_range_defaults_to_seven_whole_days() -> None:
    anchor = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    rng = resolve_range(now=anchor)
    assert rng.days == 7
    assert rng.first_day.isoformat() == "2026-09-04"
    assert rng.last_day.isoformat() == "2026-09-10"
    assert rng.labels()[0] == "2026-09-04"
    assert len(rng.labels()) == 7


def test_resolve_range_clamps_the_future_and_the_far_past() -> None:
    ahead = resolve_range(start=NOW.date(), end=(NOW + timedelta(days=40)).date(), now=NOW)
    assert ahead.last_day == NOW.date()  # tomorrow has no data; do not draw it
    huge = resolve_range(start=(NOW - timedelta(days=5000)).date(), now=NOW)
    assert huge.days == 365
    backwards = resolve_range(start=NOW.date(), end=(NOW - timedelta(days=5)).date(), now=NOW)
    assert backwards.days == 1


def test_range_query_is_validated(client: TestClient) -> None:
    r = client.get("/api/v1/admin/overview", headers=_bearer(ADMIN_ID), params={"days": 0})
    assert r.status_code == 422
    r = client.get("/api/v1/admin/overview", headers=_bearer(ADMIN_ID), params={"days": 100000})
    assert r.status_code == 422
