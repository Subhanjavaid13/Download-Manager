"""Whole-playlist downloads in the JobStore, with a fake downloader (offline)."""

import threading
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.downloader import CancelledError, PlaylistEntry, PlaylistInfo, Progress
from app.core.formats import DownloadRequest
from app.db import init_db, make_engine, make_session_factory, session_scope
from app.jobs.store import JobStore, Owner
from app.models import Download, Playlist
from app.storage import LocalStorage
from tests.test_store import wait_for

ANON = Owner(client_id="browser-abc123")
OTHER = Owner(client_id="browser-zzz999")
AUDIO = DownloadRequest(mode="audio")

ENTRIES = [
    PlaylistEntry(id="aaaaaaaaaaa", title="First song", duration_sec=100, thumbnail="https://a"),
    PlaylistEntry(id="bbbbbbbbbbb", title="Second song", duration_sec=200, thumbnail="https://b"),
    PlaylistEntry(id="ccccccccccc", title="Third song", duration_sec=300, thumbnail="https://c"),
]


class FakePlaylistDownloader:
    """One file per video, with hooks to make chosen items fail or hang."""

    def __init__(self, *, fail_ids: tuple[str, ...] = (), block_ids: tuple[str, ...] = ()) -> None:
        self.fail_ids = fail_ids
        self.block_ids = block_ids
        self.order: list[str] = []
        self.blocked = threading.Event()

    def fetch_playlist(self, url: str, limit: int | None = None) -> PlaylistInfo:
        return PlaylistInfo(id="PL1234", title="Road trip", channel="Someone", entries=ENTRIES)

    def download(self, url, req, out_dir: Path, on_progress=None, cancel_event=None) -> Path:
        video_id = url.rsplit("=", 1)[-1]
        self.order.append(video_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "partial.part").write_bytes(b"half a file")
        if on_progress:
            on_progress(Progress(stage="downloading", percent=50.0, downloaded_bytes=5))
        if video_id in self.block_ids:
            self.blocked.set()
            while not (cancel_event and cancel_event.is_set()):
                time.sleep(0.01)
            raise CancelledError()
        if video_id in self.fail_ids:
            raise RuntimeError("ERROR: [youtube] xyz: Private video")
        path = out_dir / f"Song [{video_id}].mp3"
        path.write_bytes(b"0123456789")
        return path


@pytest.fixture
def env(tmp_path: Path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'playlists.db').as_posix()}")
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

    yield make, factory, tmp_path
    engine.dispose()


def submit(store: JobStore, owner: Owner = ANON, req: DownloadRequest = AUDIO) -> dict:
    return store.submit_playlist(
        playlist_id="PL1234", entries=ENTRIES, req=req, owner=owner, title="Road trip"
    )


def finished(store: JobStore, playlist_id: str, owner: Owner = ANON) -> dict:
    terminal = {"done", "partial", "error", "cancelled"}
    return wait_for(
        lambda: (p := store.get_playlist(playlist_id, owner)) and p["status"] in terminal and p
    )


def test_every_item_downloads_in_order_and_each_gets_its_own_file(env) -> None:
    make, _f, _t = env
    downloader = FakePlaylistDownloader()
    store = make(downloader)

    created = submit(store)
    assert created["status"] == "queued"
    assert created["total_items"] == 3
    assert created["title"] == "Road trip"
    assert created["label"] == "MP3 192 kbps"
    assert [i["title"] for i in created["items"]] == ["First song", "Second song", "Third song"]
    assert [i["playlist_index"] for i in created["items"]] == [0, 1, 2]

    done = finished(store, created["id"])
    assert done["status"] == "done"
    assert done["completed_items"] == 3
    assert done["failed_items"] == 0
    assert done["percent"] == 100.0
    assert done["error"] is None
    assert downloader.order == ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]

    files = [i["filename"] for i in done["items"]]
    assert files == ["Song [aaaaaaaaaaa].mp3", "Song [bbbbbbbbbbb].mp3", "Song [ccccccccccc].mp3"]
    assert all(i["file_available"] for i in done["items"])
    for item in done["items"]:
        path, _name = store.local_file(item["id"], ANON)
        assert path.read_bytes() == b"0123456789"
        assert item["playlist_job_id"] == created["id"]
    store.shutdown()


def test_one_bad_video_does_not_stop_the_others(env) -> None:
    make, _f, _t = env
    store = make(FakePlaylistDownloader(fail_ids=("bbbbbbbbbbb",)))
    created = submit(store)

    done = finished(store, created["id"])
    assert done["status"] == "partial"
    assert done["completed_items"] == 2
    assert done["failed_items"] == 1
    assert "1 of 3 videos could not be downloaded" in done["error"]["message"]
    assert "ready to save" in done["error"]["message"]
    assert done["error"]["code"] == "private"  # the most common reason among the failures

    by_title = {i["title"]: i for i in done["items"]}
    assert by_title["Second song"]["status"] == "error"
    assert by_title["Second song"]["error"]["code"] == "private"
    assert by_title["First song"]["status"] == "done"
    assert by_title["Third song"]["status"] == "done"
    store.shutdown()


def test_a_playlist_where_everything_fails_ends_as_error(env) -> None:
    make, _f, _t = env
    store = make(FakePlaylistDownloader(fail_ids=tuple(e.id for e in ENTRIES)))
    done = finished(store, submit(store)["id"])
    assert done["status"] == "error"
    assert done["completed_items"] == 0
    assert done["failed_items"] == 3
    assert "Check the link is public" in done["error"]["message"]
    store.shutdown()


def test_cancel_stops_the_whole_run_and_removes_partial_files(env) -> None:
    make, _f, tmp_path = env
    downloader = FakePlaylistDownloader(block_ids=("aaaaaaaaaaa",))
    store = make(downloader)
    created = submit(store)
    assert downloader.blocked.wait(5)

    assert store.cancel_playlist(created["id"], ANON) is True
    cancelled = finished(store, created["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["completed_items"] == 0
    assert cancelled["cancelled_items"] == 3
    assert all(i["status"] == "cancelled" for i in cancelled["items"])
    # The half-written file of the item that was running is gone, and the two
    # items that never started were never touched.
    assert not (tmp_path / "work" / cancelled["items"][0]["id"]).exists()
    assert downloader.order == ["aaaaaaaaaaa"]
    assert store.cancel_playlist(created["id"], ANON) is False  # already final
    store.shutdown()


def test_cancel_keeps_the_files_that_already_finished(env) -> None:
    make, _f, _t = env
    downloader = FakePlaylistDownloader(block_ids=("bbbbbbbbbbb",))
    store = make(downloader)
    created = submit(store)
    assert downloader.blocked.wait(5)

    store.cancel_playlist(created["id"], ANON)
    cancelled = finished(store, created["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["completed_items"] == 1
    assert cancelled["items"][0]["status"] == "done"
    assert cancelled["items"][0]["file_available"] is True
    store.shutdown()


def test_cancelling_a_single_item_leaves_the_rest_running(env) -> None:
    make, _f, _t = env
    downloader = FakePlaylistDownloader(block_ids=("aaaaaaaaaaa",))
    store = make(downloader)
    created = submit(store)
    assert downloader.blocked.wait(5)

    first = created["items"][0]["id"]
    assert store.cancel(first, ANON) is True
    done = finished(store, created["id"])
    assert done["status"] == "partial"
    assert done["cancelled_items"] == 1
    assert done["completed_items"] == 2
    assert done["items"][0]["status"] == "cancelled"
    assert done["error"] is None  # a cancel is not a failure
    store.shutdown()


def test_a_second_playlist_can_be_cancelled_while_the_first_holds_a_worker(env) -> None:
    make, factory, _t = env
    downloader = FakePlaylistDownloader(block_ids=("aaaaaaaaaaa",))
    store = make(downloader)
    blocker = submit(store)  # holds the only item slot we care about
    assert downloader.blocked.wait(5)

    second = submit(store)
    with session_scope(factory) as s:
        # Second playlist is still queued behind the first on this worker.
        assert s.get(Playlist, uuid.UUID(second["id"])).status in ("queued", "running")
    store.cancel_playlist(second["id"], ANON)
    store.cancel_playlist(blocker["id"], ANON)

    ended = finished(store, second["id"])
    assert ended["status"] == "cancelled"
    assert ended["completed_items"] == 0
    store.shutdown()


def test_owner_isolation(env) -> None:
    make, _f, _t = env
    store = make(FakePlaylistDownloader())
    created = submit(store)
    finished(store, created["id"])

    assert store.get_playlist(created["id"], OTHER) is None
    assert store.cancel_playlist(created["id"], OTHER) is False
    assert [p["id"] for p in store.list_playlists(ANON)] == [created["id"]]
    assert store.list_playlists(OTHER) == []
    assert store.list_playlists(Owner()) == []
    assert store.get_playlist("not-a-uuid", ANON) is None
    store.shutdown()


def test_list_view_leaves_the_items_out(env) -> None:
    make, _f, _t = env
    store = make(FakePlaylistDownloader())
    created = submit(store)
    finished(store, created["id"])

    listed = store.list_playlists(ANON)
    assert listed[0]["items"] is None  # not loaded: fetch the playlist by id for those
    assert listed[0]["total_items"] == 3


def test_playlist_items_stay_out_of_the_plain_history(env) -> None:
    make, _f, _t = env
    store = make(FakePlaylistDownloader())
    created = submit(store)
    finished(store, created["id"])
    single = store.submit(video_id="ddddddddddd", req=AUDIO, owner=ANON)
    wait_for(lambda: store.get(single["id"], ANON)["status"] == "done")

    history = store.list_for(ANON)
    assert [j["id"] for j in history] == [single["id"]]
    everything = store.list_for(ANON, include_playlist_items=True)
    assert len(everything) == 4
    store.shutdown()


def test_a_restart_resumes_the_rest_of_the_playlist(env) -> None:
    make, factory, _t = env
    # Rows left behind by a crash: one item done, one mid-flight, one queued.
    with session_scope(factory) as s:
        pl = Playlist(
            client_id=ANON.client_id,
            playlist_id="PL1234",
            title="Road trip",
            mode="audio",
            format="mp3",
            quality="192",
            status="running",
            total_items=3,
            completed_items=1,
        )
        s.add(pl)
        s.flush()
        for index, (entry, status) in enumerate(
            zip(ENTRIES, ["done", "downloading", "queued"], strict=True)
        ):
            s.add(
                Download(
                    client_id=ANON.client_id,
                    video_id=entry.id,
                    title=entry.title,
                    mode="audio",
                    format="mp3",
                    quality="192",
                    status=status,
                    playlist_job_id=pl.id,
                    playlist_index=index,
                )
            )
        playlist_id = str(pl.id)

    downloader = FakePlaylistDownloader()
    store = make(downloader)
    assert store.recover() == 1

    done = finished(store, playlist_id)
    assert done["status"] == "done"
    assert done["completed_items"] == 3
    # The finished item was not downloaded again; the other two were.
    assert downloader.order == ["bbbbbbbbbbb", "ccccccccccc"]
    store.shutdown()


def test_an_empty_playlist_is_refused_before_a_row_is_written(env) -> None:
    make, factory, _t = env
    store = make(FakePlaylistDownloader())
    with pytest.raises(ValueError):
        store.submit_playlist(playlist_id="PL1234", entries=[], req=AUDIO, owner=ANON)
    with session_scope(factory) as s:
        assert s.scalars(select(Playlist)).all() == []
    store.shutdown()


def test_delete_playlist_removes_every_file_and_every_row(env) -> None:
    make, factory, _t = env
    store = make(FakePlaylistDownloader())
    created = submit(store)
    done = finished(store, created["id"])
    paths = [store.local_file(i["id"], ANON)[0] for i in done["items"]]
    assert all(p.exists() for p in paths)

    assert store.delete_playlist(created["id"], OTHER) is False  # not yours
    assert all(p.exists() for p in paths)

    assert store.delete_playlist(created["id"], ANON) is True
    assert not any(p.exists() for p in paths)
    assert store.get_playlist(created["id"], ANON) is None
    assert store.list_playlists(ANON) == []
    with session_scope(factory) as s:
        assert s.scalars(select(Download)).all() == []
        assert s.scalars(select(Playlist)).all() == []
    store.shutdown()


def test_a_single_item_cannot_be_deleted_on_its_own(env) -> None:
    """Removing one row would make the parent's "3 of 3 done" a lie."""
    make, _f, _t = env
    store = make(FakePlaylistDownloader())
    done = finished(store, submit(store)["id"])
    assert store.delete(done["items"][0]["id"], ANON) is False
    assert store.local_file(done["items"][0]["id"], ANON) is not None
    store.shutdown()


def test_delete_refuses_while_the_playlist_is_running(env) -> None:
    make, _f, _t = env
    downloader = FakePlaylistDownloader(block_ids=("aaaaaaaaaaa",))
    store = make(downloader)
    created = submit(store)
    assert downloader.blocked.wait(5)
    assert store.delete_playlist(created["id"], ANON) is False

    store.cancel_playlist(created["id"], ANON)
    finished(store, created["id"])
    assert store.delete_playlist(created["id"], ANON) is True
    store.shutdown()
