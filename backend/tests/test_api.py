"""API tests that do not touch the network."""

from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "ytdlp_version" in body
    assert body["auth_enabled"] is False


def test_info_rejects_non_youtube() -> None:
    with TestClient(app) as client:
        r = client.get("/api/v1/info", params={"url": "https://vimeo.com/1"})
    assert r.status_code == 400
    assert "YouTube" in r.json()["detail"]


def test_job_rejects_playlist() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/jobs",
            json={"url": "https://www.youtube.com/playlist?list=PLabc", "mode": "audio"},
        )
    assert r.status_code == 400


def test_job_rejects_bad_quality() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/jobs",
            json={"url": "https://youtu.be/dQw4w9WgXcQ", "mode": "audio", "audio_bitrate": 999},
        )
    assert r.status_code == 422


def test_unknown_job_is_404() -> None:
    with TestClient(app) as client:
        r = client.get("/api/v1/jobs/nope")
    assert r.status_code == 404
