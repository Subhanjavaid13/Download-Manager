"""API tests that do not touch the network."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.downloader import MediaInfo, Progress
from app.main import app

CLIENT = {"X-Client-Id": "browser-test-0001"}


class StubDownloader:
    """Replaces the yt-dlp wrapper so API tests stay offline."""

    def fetch_info(self, url: str) -> MediaInfo:
        return MediaInfo(
            id="dQw4w9WgXcQ",
            title="Stub video",
            channel="Stub channel",
            duration_sec=100,
            thumbnail=None,
            webpage_url=url,
            is_live=False,
            available_heights=[360, 720],
        )

    def download(self, url, req, out_dir: Path, on_progress=None, cancel_event=None) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "Stub video [dQw4w9WgXcQ].mp3"
        path.write_bytes(b"stub-mp3")
        if on_progress:
            on_progress(Progress(stage="processing", percent=100.0))
        return path


@pytest.fixture
def client():
    with TestClient(app) as c:
        # Swap the real engine for the stub after lifespan wired everything up.
        app.state.downloader = StubDownloader()
        app.state.jobs._downloader = StubDownloader()
        yield c


def _wait_done(client: TestClient, job_id: str) -> dict:
    import time

    for _ in range(200):
        body = client.get(f"/api/v1/jobs/{job_id}", headers=CLIENT).json()
        if body["status"] in ("done", "error", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["auth_enabled"] is False
    assert body["storage"] == "local"
    assert body["database"] == "sqlite"
    assert body["database_ok"] is True  # a real "select 1", not a cached flag


def test_info_rejects_non_youtube(client: TestClient) -> None:
    r = client.get("/api/v1/info", params={"url": "https://vimeo.com/1"})
    assert r.status_code == 400
    assert "YouTube" in r.json()["detail"]


def test_job_rejects_playlist(client: TestClient) -> None:
    r = client.post(
        "/api/v1/jobs",
        json={"url": "https://www.youtube.com/playlist?list=PLabc", "mode": "audio"},
        headers=CLIENT,
    )
    assert r.status_code == 400


def test_job_rejects_bad_quality(client: TestClient) -> None:
    r = client.post(
        "/api/v1/jobs",
        json={"url": "https://youtu.be/dQw4w9WgXcQ", "mode": "audio", "audio_bitrate": 999},
        headers=CLIENT,
    )
    assert r.status_code == 422


def test_unknown_job_is_404(client: TestClient) -> None:
    assert client.get("/api/v1/jobs/nope", headers=CLIENT).status_code == 404
    assert client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000").status_code == 404


def test_full_job_flow_with_client_id(client: TestClient) -> None:
    r = client.post(
        "/api/v1/jobs",
        json={"url": "https://youtu.be/dQw4w9WgXcQ", "mode": "audio"},
        headers=CLIENT,
    )
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["title"] == "Stub video"
    assert job["video_id"] == "dQw4w9WgXcQ"

    # Not ready yet or done: either way the file endpoint must not leak to strangers.
    assert client.get(f"/api/v1/jobs/{job['id']}").status_code == 404
    assert (
        client.get(
            f"/api/v1/jobs/{job['id']}", headers={"X-Client-Id": "someone-else1"}
        ).status_code
        == 404
    )

    done = _wait_done(client, job["id"])
    assert done["status"] == "done"
    assert done["file_available"] is True
    assert done["filename"].endswith(".mp3")

    f = client.get(f"/api/v1/jobs/{job['id']}/file", headers=CLIENT)
    assert f.status_code == 200
    assert f.content == b"stub-mp3"
    assert "attachment" in f.headers["content-disposition"]

    listed = client.get("/api/v1/jobs", headers=CLIENT).json()
    assert [j["id"] for j in listed][:1] == [job["id"]]
    assert client.get("/api/v1/jobs").json() == []  # anonymous with no client id sees nothing


def test_file_not_ready_is_409(client: TestClient) -> None:
    # Create a job whose worker never runs by pointing at a downloader that raises.
    class Slow(StubDownloader):
        def download(self, *a, **k):
            import time

            time.sleep(0.3)
            return super().download(*a, **k)

    app.state.jobs._downloader = Slow()
    r = client.post("/api/v1/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"}, headers=CLIENT)
    job_id = r.json()["id"]
    assert client.get(f"/api/v1/jobs/{job_id}/file", headers=CLIENT).status_code == 409
    _wait_done(client, job_id)
