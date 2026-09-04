"""JobStore lifecycle with a fake downloader (no network, no FFmpeg)."""

import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.downloader import CancelledError, MediaInfo, Progress
from app.core.formats import DownloadRequest
from app.db import init_db, make_engine, make_session_factory, session_scope
from app.jobs.store import JobStore, Owner
from app.models import Download
from app.storage import LocalStorage

INFO = MediaInfo(
    id="dQw4w9WgXcQ",
    title="Never Gonna Give You Up",
    channel="Rick Astley",
    duration_sec=213,
    thumbnail="https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    webpage_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    is_live=False,
    available_heights=[360, 720, 1080],
)


class FakeDownloader:
    """Writes a small file and reports progress like the real thing."""

    def __init__(self, *, fail: Exception | None = None, block: bool = False) -> None:
        self.fail = fail
        self.block = block
        self.started = threading.Event()

    def download(self, url, req, out_dir: Path, on_progress=None, cancel_event=None) -> Path:
        self.started.set()
        out_dir.mkdir(parents=True, exist_ok=True)
        if on_progress:
            on_progress(Progress(stage="fetching"))
            on_progress(
                Progress(stage="downloading", percent=50.0, downloaded_bytes=5, total_bytes=10)
            )
        if self.block:
            while not (cancel_event and cancel_event.is_set()):
                time.sleep(0.01)
            raise CancelledError()
        if self.fail:
            raise self.fail
        ext = "mp3" if req.mode == "audio" else "mp4"
        path = out_dir / f"Never Gonna Give You Up [dQw4w9WgXcQ].{ext}"
        path.write_bytes(b"0123456789")
        if on_progress:
            on_progress(Progress(stage="processing", percent=100.0, detail="FFmpegExtractAudio"))
        return path


def wait_for(fn, timeout: float = 5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("timed out")


@pytest.fixture
def env(tmp_path: Path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'store.db').as_posix()}")
    init_db(engine)
    factory = make_session_factory(engine)
    storage = LocalStorage(tmp_path / "files")

    def make(downloader, retention_minutes: int = 0) -> JobStore:
        return JobStore(
            downloader=downloader,
            storage=storage,
            session_factory=factory,
            work_dir=tmp_path / "work",
            concurrency=2,
            retention_minutes=retention_minutes,
            sweep_interval_sec=3600,
        )

    yield make, factory, storage
    engine.dispose()


ANON = Owner(client_id="browser-abc123")
OTHER = Owner(client_id="browser-zzz999")
AUDIO = DownloadRequest(mode="audio")


def test_job_runs_to_done_and_file_is_served(env) -> None:
    make, _factory, storage = env
    store = make(FakeDownloader())
    job = store.submit(video_id=INFO.id, req=AUDIO, owner=ANON, info=INFO)
    assert job["status"] == "queued"
    assert job["title"] == INFO.title
    assert job["label"] == "MP3 192 kbps"

    done = wait_for(lambda: (j := store.get(job["id"], ANON)) and j["status"] == "done" and j)
    assert done["file_available"] is True
    assert done["filename"].endswith(".mp3")
    assert done["size_bytes"] == 10
    assert done["file_url"] == f"/api/v1/jobs/{job['id']}/file"
    assert done["expires_at"] is None  # kept: there is no deadline to report
    assert done["progress"]["percent"] == 100.0

    path, filename = store.local_file(job["id"], ANON)
    assert path.read_bytes() == b"0123456789"
    assert filename == done["filename"]
    assert storage.local_path(done["filename"] and f"{job['id']}/{done['filename']}") == path
    store.shutdown()


def test_owner_isolation(env) -> None:
    make, _f, _s = env
    store = make(FakeDownloader())
    job = store.submit(video_id=INFO.id, req=AUDIO, owner=ANON, info=INFO)
    wait_for(lambda: store.get(job["id"], ANON)["status"] == "done")

    assert store.get(job["id"], OTHER) is None
    assert store.local_file(job["id"], OTHER) is None
    assert store.cancel(job["id"], OTHER) is False
    assert [j["id"] for j in store.list_for(ANON)] == [job["id"]]
    assert store.list_for(OTHER) == []
    assert store.list_for(Owner()) == []  # nobody at all sees nothing
    store.shutdown()


def test_failure_is_mapped_to_friendly_error(env) -> None:
    make, _f, _s = env
    store = make(FakeDownloader(fail=RuntimeError("ERROR: [youtube] abc: Private video")))
    job = store.submit(video_id=INFO.id, req=AUDIO, owner=ANON, info=INFO)
    failed = wait_for(lambda: (j := store.get(job["id"], ANON)) and j["status"] == "error" and j)
    assert failed["error"]["code"] == "private"
    assert failed["file_available"] is False
    store.shutdown()


def test_cancel_running_job(env, tmp_path: Path) -> None:
    make, _f, _s = env
    dl = FakeDownloader(block=True)
    store = make(dl)
    job = store.submit(video_id=INFO.id, req=AUDIO, owner=ANON, info=INFO)
    assert dl.started.wait(5)
    assert store.cancel(job["id"], ANON) is True
    cancelled = wait_for(
        lambda: (j := store.get(job["id"], ANON)) and j["status"] == "cancelled" and j
    )
    assert cancelled["file_available"] is False
    assert not (tmp_path / "work" / job["id"]).exists()
    assert store.cancel(job["id"], ANON) is False  # already final
    store.shutdown()


def test_sweep_removes_expired_files_but_keeps_history(env) -> None:
    make, factory, _s = env
    store = make(FakeDownloader())
    job = store.submit(video_id=INFO.id, req=AUDIO, owner=ANON, info=INFO)
    wait_for(lambda: store.get(job["id"], ANON)["status"] == "done")
    path, _ = store.local_file(job["id"], ANON)
    assert path.exists()

    with session_scope(factory) as s:
        row = s.scalars(select(Download)).one()
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)

    assert store.sweep() == 1
    after = store.get(job["id"], ANON)
    assert after["status"] == "done"  # history row stays
    assert after["file_available"] is False
    assert after["file_url"] is None
    assert not path.exists()
    assert store.local_file(job["id"], ANON) is None
    store.shutdown()


def test_recover_marks_inflight_as_interrupted_and_requeues_queued(env) -> None:
    make, factory, _s = env
    # Simulate rows left behind by a crashed process.
    with session_scope(factory) as s:
        s.add(
            Download(
                client_id=ANON.client_id,
                video_id=INFO.id,
                mode="audio",
                format="mp3",
                quality="192",
                status="downloading",
                percent=40.0,
            )
        )
        s.add(
            Download(
                client_id=ANON.client_id,
                video_id=INFO.id,
                mode="video",
                format="mp4",
                quality="720",
                status="queued",
            )
        )
    store = make(FakeDownloader())
    assert store.recover() == 1

    terminal = {"done", "error", "cancelled"}
    jobs = wait_for(
        lambda: (js := store.list_for(ANON)) and all(j["status"] in terminal for j in js) and js
    )
    by_mode = {j["mode"]: j for j in jobs}
    assert by_mode["audio"]["status"] == "error"
    assert by_mode["audio"]["error"]["code"] == "interrupted"
    assert by_mode["video"]["status"] == "done"  # re-queued and completed with the fake
    assert by_mode["video"]["label"] == "MP4 720p"
    store.shutdown()


def test_files_are_kept_by_default(env) -> None:
    """The point of the app: the file is the user's, so nothing takes it away."""
    make, _f, _s = env
    store = make(FakeDownloader())  # no retention configured, which is the default
    assert store._retention is None
    assert store._janitor is None  # nothing to sweep, so no janitor thread at all

    job = store.submit(video_id=INFO.id, req=AUDIO, owner=ANON, info=INFO)
    done = wait_for(lambda: (j := store.get(job["id"], ANON)) and j["status"] == "done" and j)
    assert done["expires_at"] is None

    path, _ = store.local_file(job["id"], ANON)
    assert store.sweep() == 0
    assert path.exists()
    assert store.get(job["id"], ANON)["file_available"] is True
    store.shutdown()


def test_a_retention_period_still_expires_files(env) -> None:
    """A shared server can still opt in to a deadline, and then it is reported."""
    make, _f, _s = env
    store = make(FakeDownloader(), retention_minutes=60)
    job = store.submit(video_id=INFO.id, req=AUDIO, owner=ANON, info=INFO)
    done = wait_for(lambda: (j := store.get(job["id"], ANON)) and j["status"] == "done" and j)
    assert done["expires_at"] is not None
    store.shutdown()


def test_delete_removes_the_file_and_the_row(env, tmp_path: Path) -> None:
    make, _f, _s = env
    store = make(FakeDownloader())
    job = store.submit(video_id=INFO.id, req=AUDIO, owner=ANON, info=INFO)
    wait_for(lambda: store.get(job["id"], ANON)["status"] == "done")
    path, _ = store.local_file(job["id"], ANON)
    assert path.exists()

    assert store.delete(job["id"], OTHER) is False  # not yours
    assert path.exists()

    assert store.delete(job["id"], ANON) is True
    assert not path.exists()
    assert not path.parent.exists()  # the job folder goes too
    assert store.get(job["id"], ANON) is None
    assert store.list_for(ANON) == []
    assert store.delete(job["id"], ANON) is False  # already gone
    store.shutdown()


def test_delete_refuses_while_the_download_is_running(env) -> None:
    make, _f, _s = env
    dl = FakeDownloader(block=True)
    store = make(dl)
    job = store.submit(video_id=INFO.id, req=AUDIO, owner=ANON, info=INFO)
    assert dl.started.wait(5)
    assert store.delete(job["id"], ANON) is False
    assert store.get(job["id"], ANON) is not None

    store.cancel(job["id"], ANON)
    wait_for(lambda: store.get(job["id"], ANON)["status"] == "cancelled")
    assert store.delete(job["id"], ANON) is True  # cancelled rows can be tidied away
    store.shutdown()
