"""Playlist endpoints, offline (the downloader is stubbed)."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.downloader import MediaInfo, PlaylistEntry, PlaylistInfo, Progress
from app.main import app

CLIENT = {"X-Client-Id": "browser-playlist01"}
PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLtest12345"

ENTRIES = [
    PlaylistEntry(id="aaaaaaaaaaa", title="First", duration_sec=100, thumbnail="https://a"),
    PlaylistEntry(id="bbbbbbbbbbb", title="Second", duration_sec=200, thumbnail="https://b"),
]


class StubDownloader:
    """Serves a two-video playlist and writes a file per item."""

    def __init__(self, *, entries=ENTRIES, truncated: bool = False) -> None:
        self.entries = entries
        self.truncated = truncated

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

    def fetch_playlist(self, url: str, limit: int | None = None) -> PlaylistInfo:
        return PlaylistInfo(
            id="PLtest12345",
            title="Stub playlist",
            channel="Stub channel",
            entries=self.entries,
            truncated=self.truncated,
        )

    def download(self, url, req, out_dir: Path, on_progress=None, cancel_event=None) -> Path:
        video_id = url.rsplit("=", 1)[-1]
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"Song [{video_id}].mp3"
        path.write_bytes(b"stub-mp3")
        if on_progress:
            on_progress(Progress(stage="processing", percent=100.0))
        return path


@pytest.fixture
def client():
    with TestClient(app) as c:
        app.state.downloader = StubDownloader()
        app.state.jobs._downloader = StubDownloader()
        yield c


def _wait_done(client: TestClient, playlist_id: str) -> dict:
    for _ in range(300):
        body = client.get(f"/api/v1/playlists/{playlist_id}", headers=CLIENT).json()
        if body["status"] in ("done", "partial", "error", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError("playlist did not finish")


def test_create_a_playlist_and_download_every_file(client: TestClient) -> None:
    r = client.post("/api/v1/playlists", json={"url": PLAYLIST_URL}, headers=CLIENT)
    assert r.status_code == 202, r.text
    created = r.json()
    assert created["title"] == "Stub playlist"
    assert created["playlist_id"] == "PLtest12345"
    assert created["total_items"] == 2
    assert [i["title"] for i in created["items"]] == ["First", "Second"]

    done = _wait_done(client, created["id"])
    assert done["status"] == "done"
    assert done["completed_items"] == 2
    assert done["percent"] == 100.0

    # Items are ordinary jobs, so the existing file endpoint serves them.
    for item in done["items"]:
        f = client.get(f"/api/v1/jobs/{item['id']}/file", headers=CLIENT)
        assert f.status_code == 200
        assert f.content == b"stub-mp3"

    listed = client.get("/api/v1/playlists", headers=CLIENT).json()
    assert [p["id"] for p in listed][:1] == [created["id"]]
    assert listed[0]["items"] is None  # list view stays small

    # The 2 items do not bury the single-video history.
    assert client.get("/api/v1/jobs", headers=CLIENT).json() == []


def test_a_stranger_sees_nothing(client: TestClient) -> None:
    created = client.post("/api/v1/playlists", json={"url": PLAYLIST_URL}, headers=CLIENT).json()
    other = {"X-Client-Id": "browser-someoneelse"}
    assert client.get(f"/api/v1/playlists/{created['id']}", headers=other).status_code == 404
    assert client.delete(f"/api/v1/playlists/{created['id']}", headers=other).status_code == 404
    assert client.get("/api/v1/playlists", headers=other).json() == []
    _wait_done(client, created["id"])


def test_cancel_a_running_playlist(client: TestClient) -> None:
    class Slow(StubDownloader):
        def download(self, *a, **k):
            time.sleep(0.5)
            return super().download(*a, **k)

    app.state.jobs._downloader = Slow()
    created = client.post("/api/v1/playlists", json={"url": PLAYLIST_URL}, headers=CLIENT).json()
    assert client.delete(f"/api/v1/playlists/{created['id']}", headers=CLIENT).status_code == 204
    ended = _wait_done(client, created["id"])
    assert ended["status"] == "cancelled"
    assert ended["completed_items"] < 2


def test_unknown_playlist_is_404(client: TestClient) -> None:
    assert client.get("/api/v1/playlists/nope", headers=CLIENT).status_code == 404
    assert (
        client.get(
            "/api/v1/playlists/00000000-0000-0000-0000-000000000000", headers=CLIENT
        ).status_code
        == 404
    )


def test_a_single_video_link_is_refused_with_advice(client: TestClient) -> None:
    r = client.post(
        "/api/v1/playlists", json={"url": "https://youtu.be/dQw4w9WgXcQ"}, headers=CLIENT
    )
    assert r.status_code == 400
    assert "no playlist" in r.json()["detail"]


def test_a_playlist_link_on_the_jobs_endpoint_points_at_the_right_one(client: TestClient) -> None:
    r = client.post("/api/v1/jobs", json={"url": PLAYLIST_URL}, headers=CLIENT)
    assert r.status_code == 400
    assert "/api/v1/playlists" in r.json()["detail"]


def test_too_many_videos_is_refused_politely(client: TestClient) -> None:
    app.state.downloader = StubDownloader(truncated=True)
    r = client.post("/api/v1/playlists", json={"url": PLAYLIST_URL}, headers=CLIENT)
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "more than 50 videos" in detail
    assert "batches" in detail


def test_an_empty_playlist_is_refused_politely(client: TestClient) -> None:
    app.state.downloader = StubDownloader(entries=[])
    r = client.post("/api/v1/playlists", json={"url": PLAYLIST_URL}, headers=CLIENT)
    assert r.status_code == 400
    assert "no videos" in r.json()["detail"]


def test_info_previews_a_playlist(client: TestClient) -> None:
    r = client.get("/api/v1/info", params={"url": PLAYLIST_URL})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "playlist"
    assert body["playlist_id"] == "PLtest12345"
    assert body["playlist_count"] == 2
    assert body["playlist_truncated"] is False
    assert body["playlist_limit"] == 50
    assert body["duration_sec"] == 300  # the two items added up
    assert [i["title"] for i in body["items"]] == ["First", "Second"]
    assert body["available_heights"] == []
