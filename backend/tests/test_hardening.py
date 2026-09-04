"""Phase 6 hardening: the ban list, the client-IP rule, playlist quotas, Sentry scrubbing."""

import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.config import Settings, get_settings
from app.db import init_db, make_engine, make_session_factory
from app.deps import client_ip, rate_limit_key
from app.main import app
from app.observability import init_sentry, scrub_event
from app.services.bans import Bans
from tests.test_playlists_api import PLAYLIST_URL, StubDownloader

SECRET = "hardening-test-secret"
CLIENT = {"X-Client-Id": "browser-hardening1"}


# -- the ban list ------------------------------------------------------------


@pytest.fixture
def bans(tmp_path) -> Bans:
    engine = make_engine(f"sqlite:///{(tmp_path / 'bans.db').as_posix()}")
    init_db(engine)
    yield Bans(make_session_factory(engine), ip_salt="pepper")
    engine.dispose()


def test_a_clean_caller_is_allowed(bans: Bans) -> None:
    assert bans.check(user_id=str(uuid.uuid4()), ip="203.0.113.5") is None
    assert bans.check() is None  # nothing to look up at all


def test_a_banned_user_is_recognised(bans: Bans) -> None:
    uid = str(uuid.uuid4())
    bans.add("user", uid, reason="ripping the same album 400 times", created_by="me@example.com")

    hit = bans.check(user_id=uid, ip="203.0.113.5")
    assert hit is not None
    assert hit.subject_type == "user"
    assert "ripping the same album" in hit.message
    assert "mistake" in hit.message  # tells them what to do next
    assert bans.check(user_id=str(uuid.uuid4())) is None


def test_an_ip_is_banned_by_its_hash_never_the_address(bans: Bans) -> None:
    bans.add("ip_hash", bans.hash_for("203.0.113.5"), reason="scripted abuse")
    assert bans.check(ip="203.0.113.5") is not None
    assert bans.check(ip="203.0.113.6") is None
    # The raw address is nowhere in the row.
    assert all("203.0.113.5" not in row.subject for row in bans.list_all())


def test_a_ban_can_expire(bans: Bans) -> None:
    uid = str(uuid.uuid4())
    bans.add("user", uid, days=7)
    hit = bans.check(user_id=uid)
    assert hit is not None
    assert "The block lifts on" in hit.message
    assert hit.expires_at > datetime.now(UTC) + timedelta(days=6)

    bans.add("user", uid, days=-1)  # already in the past
    assert bans.check(user_id=uid) is None


def test_bans_can_be_listed_updated_and_lifted(bans: Bans) -> None:
    uid = str(uuid.uuid4())
    bans.add("user", uid, reason="first")
    bans.add("user", uid, reason="second")  # same subject: updated, not duplicated
    assert len(bans.list_all()) == 1
    assert bans.check(user_id=uid).reason == "second"

    assert bans.remove("user", uid) is True
    assert bans.check(user_id=uid) is None
    assert bans.remove("user", uid) is False


def test_an_unknown_subject_type_is_refused(bans: Bans) -> None:
    with pytest.raises(ValueError):
        bans.add("email", "x@example.com")


def test_a_broken_database_does_not_lock_everyone_out(bans: Bans, tmp_path) -> None:
    """A ban lookup failing must not take downloads down with it."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'gone.db').as_posix()}")
    broken = Bans(make_session_factory(engine), ip_salt="pepper")
    engine.dispose()
    (tmp_path / "gone.db").write_bytes(b"not a database")
    assert broken.check(user_id=str(uuid.uuid4())) is None


# -- the ban list, through the API -------------------------------------------


@pytest.fixture
def client():
    with TestClient(app) as c:
        app.state.downloader = StubDownloader()
        app.state.jobs._downloader = StubDownloader()
        yield c
        # Leave no bans behind for the other test modules.
        for row in app.state.bans.list_all():
            app.state.bans.remove(row.subject_type, row.subject)


def test_a_banned_address_cannot_start_a_job_or_a_playlist(client: TestClient) -> None:
    ip_hash = app.state.bans.hash_for("testclient")  # what TestClient's socket reports
    app.state.bans.add("ip_hash", ip_hash, reason="testing")

    r = client.post("/api/v1/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"}, headers=CLIENT)
    assert r.status_code == 403
    assert "blocked" in r.json()["detail"]

    r = client.post("/api/v1/playlists", json={"url": PLAYLIST_URL}, headers=CLIENT)
    assert r.status_code == 403

    app.state.bans.remove("ip_hash", ip_hash)
    assert (
        client.post(
            "/api/v1/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"}, headers=CLIENT
        ).status_code
        == 202
    )


# -- which IP we hold a caller responsible for -------------------------------


def _request(headers: dict[str, str], peer: str = "10.0.0.9") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "scheme": "http",
            "query_string": b"",
            "server": ("test", 80),
            "client": (peer, 51234),
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
    )


def test_by_default_a_forged_forwarded_header_is_ignored() -> None:
    settings = Settings(client_ip_header=None, trusted_proxy_hops=0)
    request = _request({"x-forwarded-for": "1.2.3.4"})
    assert client_ip(request, settings) == "10.0.0.9"


def test_a_platform_header_is_used_when_configured() -> None:
    settings = Settings(client_ip_header="cf-connecting-ip")
    request = _request({"cf-connecting-ip": "198.51.100.7", "x-forwarded-for": "1.2.3.4"})
    assert client_ip(request, settings) == "198.51.100.7"
    # Missing on this request: fall back rather than trust the forgeable header.
    assert client_ip(_request({"x-forwarded-for": "1.2.3.4"}), settings) == "10.0.0.9"


def test_trusted_hops_read_from_the_right_end_of_the_chain() -> None:
    settings = Settings(trusted_proxy_hops=1)
    # The client claims 1.2.3.4; our own load balancer appended the real 198.51.100.7.
    request = _request({"x-forwarded-for": "1.2.3.4, 198.51.100.7"})
    assert client_ip(request, settings) == "198.51.100.7"

    two = Settings(trusted_proxy_hops=2)
    chain = _request({"x-forwarded-for": "1.2.3.4, 198.51.100.7, 203.0.113.9"})
    assert client_ip(chain, two) == "198.51.100.7"
    # More hops configured than the header holds: take the leftmost real entry.
    assert client_ip(_request({"x-forwarded-for": "203.0.113.9"}), two) == "203.0.113.9"


def test_rate_limits_key_on_the_token_when_signed_in() -> None:
    signed_in = _request({"authorization": "Bearer abc.def.ghi"})
    assert rate_limit_key(signed_in).startswith("tok:")
    assert rate_limit_key(_request({})).startswith("ip:")


# -- playlists and the daily quota -------------------------------------------


def _token(uid: str | None = None) -> str:
    return jwt.encode(
        {
            "sub": uid or str(uuid.uuid4()),
            "email": "u@example.com",
            "aud": "authenticated",
            "role": "authenticated",
            "user_metadata": {"email_verified": True},
            "exp": int(time.time()) + 600,
        },
        SECRET,
        algorithm="HS256",
    )


@pytest.fixture
def quota_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DM_SUPABASE_URL", "https://proj.supabase.test")
    monkeypatch.setenv("DM_SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setenv("DM_REQUIRE_AUTH", "false")
    monkeypatch.setenv("DM_ANON_DAILY_LIMIT", "3")
    get_settings.cache_clear()
    with TestClient(app) as c:
        app.state.downloader = StubDownloader()
        app.state.jobs._downloader = StubDownloader()
        yield c
    get_settings.cache_clear()


def test_a_guest_cannot_pull_a_playlist_bigger_than_the_daily_allowance(
    quota_client: TestClient,
) -> None:
    """Three free downloads a day must mean three files, not three playlists."""
    from app.core.downloader import PlaylistEntry

    entries = [PlaylistEntry(id=f"{i:011d}"[:11], title=f"Song {i}") for i in range(5)]
    app.state.downloader = StubDownloader(entries=entries)
    headers = {"X-Client-Id": f"browser-quota-{uuid.uuid4().hex[:8]}"}

    r = quota_client.post("/api/v1/playlists", json={"url": PLAYLIST_URL}, headers=headers)
    assert r.status_code == 429
    detail = r.json()["detail"]
    assert "needs 5 downloads" in detail
    assert "only 3 left" in detail
    assert "Sign in" in detail


def test_a_playlist_that_fits_is_allowed_and_uses_up_the_allowance(
    quota_client: TestClient,
) -> None:
    from app.core.downloader import PlaylistEntry

    entries = [PlaylistEntry(id=f"aaaaaaaaa{i:02d}", title=f"Song {i}") for i in range(3)]
    app.state.downloader = StubDownloader(entries=entries)
    headers = {"X-Client-Id": f"browser-quota-{uuid.uuid4().hex[:8]}"}

    assert (
        quota_client.post(
            "/api/v1/playlists", json={"url": PLAYLIST_URL}, headers=headers
        ).status_code
        == 202
    )
    # Those three items count, so a single video afterwards is over the line.
    r = quota_client.post(
        "/api/v1/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"}, headers=headers
    )
    assert r.status_code == 429
    assert "free downloads" in r.json()["detail"]


def test_a_signed_in_user_gets_the_same_rule_with_their_own_quota(
    quota_client: TestClient,
) -> None:
    from app.core.downloader import PlaylistEntry

    entries = [PlaylistEntry(id=f"bbbbbbbbb{i:02d}", title=f"Song {i}") for i in range(25)]
    app.state.downloader = StubDownloader(entries=entries)
    headers = {"Authorization": f"Bearer {_token()}", **CLIENT}

    r = quota_client.post("/api/v1/playlists", json={"url": PLAYLIST_URL}, headers=headers)
    assert r.status_code == 429
    assert "needs 25 downloads" in r.json()["detail"]  # the default quota is 20
    assert "tomorrow" in r.json()["detail"]


# -- Sentry ------------------------------------------------------------------


def test_sentry_stays_off_without_a_dsn() -> None:
    assert init_sentry(Settings(sentry_dsn=None)) is False


def test_personal_data_is_scrubbed_from_events() -> None:
    event = scrub_event(
        {
            "request": {
                "url": "https://api.example.com/api/v1/info?url=https://youtu.be/dQw4w9WgXcQ",
                "query_string": "url=https://youtu.be/dQw4w9WgXcQ",
                "headers": {
                    "Authorization": "Bearer secret-token",
                    "Cookie": "session=abc",
                    "X-Client-Id": "browser-1234",
                    "CF-Connecting-IP": "203.0.113.5",
                    "User-Agent": "Firefox",
                },
                "cookies": {"session": "abc"},
                "env": {"REMOTE_ADDR": "203.0.113.5"},
                "data": {"url": "https://youtu.be/dQw4w9WgXcQ"},
            },
            "user": {"id": "uuid-1", "email": "person@example.com", "ip_address": "203.0.113.5"},
            "server_name": "worker-7",
            "message": "boom",
        }
    )

    request = event["request"]
    assert request["headers"] == {"User-Agent": "Firefox"}
    assert request["url"] == "https://api.example.com/api/v1/info"
    for gone in ("cookies", "env", "data", "query_string"):
        assert gone not in request
    assert event["user"] == {"id": "uuid-1"}
    assert "server_name" not in event
    assert event["message"] == "boom"  # the useful part survives


def test_scrubbing_copes_with_odd_events() -> None:
    assert scrub_event({}) == {}
    assert scrub_event({"request": "not-a-dict", "user": None}) == {
        "request": "not-a-dict",
        "user": None,
    }
    assert scrub_event({"user": {"email": "person@example.com"}})["user"] == {}
