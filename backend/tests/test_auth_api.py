"""Accounts, quotas, and sign-up through the HTTP API with auth switched on.

Tokens are HS256 test tokens; Supabase's sign-up endpoint is mocked with httpx.
"""

import time
import uuid

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.test_api import StubDownloader

SECRET = "api-test-secret"
CLIENT = {"X-Client-Id": "browser-auth-0001"}


def _token(uid: str | None = None, verified: bool = True, email: str = "u@example.com") -> str:
    claims = {
        "sub": uid or str(uuid.uuid4()),
        "email": email,
        "aud": "authenticated",
        "role": "authenticated",
        "user_metadata": {"email_verified": verified},
        "exp": int(time.time()) + 600,
    }
    return jwt.encode(claims, SECRET, algorithm="HS256")


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", **CLIENT}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DM_SUPABASE_URL", "https://proj.supabase.test")
    monkeypatch.setenv("DM_SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("DM_SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setenv("DM_REQUIRE_AUTH", "false")
    monkeypatch.setenv("DM_ANON_DAILY_LIMIT", "2")
    monkeypatch.setenv("DM_CHECK_MX", "false")
    get_settings.cache_clear()
    with TestClient(app) as c:
        app.state.downloader = StubDownloader()
        app.state.jobs._downloader = StubDownloader()
        yield c
    get_settings.cache_clear()


def _wait_done(client: TestClient, job_id: str, headers: dict) -> dict:
    for _ in range(200):
        body = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
        if body["status"] in ("done", "error", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def _start(client: TestClient, headers: dict) -> httpx.Response:
    return client.post(
        "/api/v1/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"}, headers=headers
    )


def test_health_and_config_report_auth(client: TestClient) -> None:
    h = client.get("/health").json()
    assert h["auth_enabled"] is True
    assert h["signup_enabled"] is True
    cfg = client.get("/api/v1/auth/config").json()
    assert cfg == {
        "enabled": True,
        "signup_enabled": True,
        "require_auth": False,
        "anon_daily_limit": 2,
        "turnstile_required": False,
    }


def test_anonymous_allowance_then_429(client: TestClient) -> None:
    headers = {"X-Client-Id": f"browser-anon-{uuid.uuid4().hex[:8]}"}
    assert _start(client, headers).status_code == 202
    assert _start(client, headers).status_code == 202
    r = _start(client, headers)
    assert r.status_code == 429
    assert "free downloads" in r.json()["detail"]
    # No client id at all is refused while auth is on.
    assert _start(client, {}).status_code == 401


def test_bad_token_is_401(client: TestClient) -> None:
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401


def test_unverified_user_cannot_download_but_can_see_profile(client: TestClient) -> None:
    tok = _token(verified=False)
    r = _start(client, _bearer(tok))
    assert r.status_code == 403
    assert "Verify your email" in r.json()["detail"]
    me = client.get("/api/v1/auth/me", headers=_bearer(tok)).json()
    assert me["email_verified"] is False
    assert me["daily_quota"] == 20
    assert me["downloads_today"] == 0


def test_verified_user_downloads_and_quota_counts(client: TestClient) -> None:
    uid = str(uuid.uuid4())
    tok = _token(uid)
    r = _start(client, _bearer(tok))
    assert r.status_code == 202, r.text
    job = r.json()
    done = _wait_done(client, job["id"], _bearer(tok))
    assert done["status"] == "done"

    me = client.get("/api/v1/auth/me", headers=_bearer(tok)).json()
    assert me["id"] == uid
    assert me["downloads_today"] == 1
    assert me["email_verified"] is True

    # Owned by the user, so a stranger with only the client id cannot see it.
    assert client.get(f"/api/v1/jobs/{job['id']}", headers=CLIENT).status_code == 404
    assert client.get(f"/api/v1/jobs/{job['id']}/file", headers=_bearer(tok)).status_code == 200
    # A different signed-in user cannot see it either.
    assert client.get(f"/api/v1/jobs/{job['id']}", headers=_bearer(_token())).status_code == 404


def test_claim_moves_anonymous_history_to_the_account(client: TestClient) -> None:
    anon = {"X-Client-Id": f"browser-claim-{uuid.uuid4().hex[:8]}"}
    job = _start(client, anon).json()
    _wait_done(client, job["id"], anon)
    assert len(client.get("/api/v1/jobs", headers=anon).json()) == 1

    tok = _token()
    headers = {"Authorization": f"Bearer {tok}", **anon}
    assert client.get("/api/v1/jobs", headers=headers).json() == []  # not theirs yet
    r = client.post("/api/v1/auth/claim", headers=headers)
    assert r.status_code == 200
    assert r.json()["claimed"] == 1
    mine = client.get("/api/v1/jobs", headers=headers).json()
    assert [j["id"] for j in mine] == [job["id"]]
    # Claiming twice is harmless.
    assert client.post("/api/v1/auth/claim", headers=headers).json()["claimed"] == 0


def test_signup_rejects_disposable_and_forwards_good_emails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = client.post(
        "/api/v1/auth/signup", json={"email": "x@mailinator.com", "password": "longenough1"}
    )
    assert r.status_code == 400
    assert "Temporary" in r.json()["detail"]

    r = client.post("/api/v1/auth/signup", json={"email": "bad", "password": "longenough1"})
    assert r.status_code == 422  # pydantic EmailStr

    r = client.post("/api/v1/auth/signup", json={"email": "ok@example.com", "password": "short"})
    assert r.status_code == 422

    seen: dict = {}
    new_uid = str(uuid.uuid4())

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["apikey"] = request.headers.get("apikey")
        seen["json"] = request.read()
        return httpx.Response(
            200,
            json={"id": new_uid, "email": "ok@example.com", "confirmation_sent_at": "now"},
        )

    real_client = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    from app.api import auth as auth_api

    monkeypatch.setattr(auth_api.httpx, "AsyncClient", patched)

    r = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "ok@example.com",
            "password": "longenough1",
            "display_name": "Okay",
            "redirect_to": "http://localhost:3000/auth/callback",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["confirmation_required"] is True
    assert body["user_id"] == new_uid
    assert "inbox" in body["message"]
    assert seen["apikey"] == "anon-key"
    assert seen["url"].startswith("https://proj.supabase.test/auth/v1/signup?redirect_to=")
    assert b'"full_name": "Okay"' in seen["json"] or b'"full_name":"Okay"' in seen["json"]

    # Supabase's "already registered" answer is translated.
    def dup(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "code": 422,
                "error_code": "user_already_exists",
                "msg": "User already registered",
            },
        )

    monkeypatch.setattr(
        auth_api.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(*a, transport=httpx.MockTransport(dup), **k),
    )
    r = client.post(
        "/api/v1/auth/signup", json={"email": "ok@example.com", "password": "longenough1"}
    )
    assert r.status_code == 400
    assert "already exists" in r.json()["detail"]


def test_delete_account_removes_history(client: TestClient) -> None:
    tok = _token()
    job = _start(client, _bearer(tok)).json()
    _wait_done(client, job["id"], _bearer(tok))
    assert len(client.get("/api/v1/jobs", headers=_bearer(tok)).json()) == 1

    assert client.delete("/api/v1/auth/me", headers=_bearer(tok)).status_code == 204
    assert client.get("/api/v1/jobs", headers=_bearer(tok)).json() == []
    assert client.get(f"/api/v1/jobs/{job['id']}", headers=_bearer(tok)).status_code == 404
