"""The download folder: moving finished files in, serving them, deleting them.

There is only one storage backend now. Everything a job produces lands on the
disk of whoever runs the API, so these tests are about the folder itself and
about the guard that stops a crafted key reaching outside it.
"""

from pathlib import Path

from app.storage import LocalStorage, content_disposition


def _make_file(tmp_path: Path, name: str = "Song [abc].mp3") -> Path:
    job_dir = tmp_path / "work" / "job1"
    job_dir.mkdir(parents=True)
    path = job_dir / name
    path.write_bytes(b"abc")
    return path


def test_content_disposition_handles_unicode() -> None:
    header = content_disposition('Naïve "quote" 🎵.mp3')
    assert header.startswith("attachment; filename=\"Na?ve 'quote' ")
    assert "filename*=UTF-8''Na%C3%AFve%20%22quote%22%20%F0%9F%8E%B5.mp3" in header


def test_local_storage_moves_file_and_serves_it(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "files")
    src = _make_file(tmp_path)
    stored = storage.store("job1", src)
    assert stored.key == "job1/Song [abc].mp3"
    assert stored.size_bytes == 3
    assert not src.exists()  # moved, not copied
    served = storage.local_path(stored.key)
    assert served and served.read_bytes() == b"abc"
    assert served.parent == (tmp_path / "files" / "job1")
    storage.delete(stored.key)
    assert storage.local_path(stored.key) is None


def test_the_file_stays_until_something_deletes_it(tmp_path: Path) -> None:
    """Nothing in the storage layer removes a file on its own."""
    storage = LocalStorage(tmp_path / "files")
    stored = storage.store("job1", _make_file(tmp_path))
    for _ in range(3):
        assert storage.local_path(stored.key) is not None
    assert (tmp_path / "files" / "job1" / "Song [abc].mp3").exists()


def test_delete_removes_the_whole_job_folder(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "files")
    stored = storage.store("job1", _make_file(tmp_path))
    (tmp_path / "files" / "job1" / "leftover.part").write_bytes(b"x")
    storage.delete(stored.key)
    assert not (tmp_path / "files" / "job1").exists()
    assert (tmp_path / "files").exists()  # the root itself survives


def test_local_storage_refuses_path_traversal(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "files")
    (tmp_path / "secret.txt").write_text("nope")
    assert storage.local_path("../secret.txt") is None
    assert storage.local_path("job1/../../secret.txt") is None
    assert storage.local_path("") is None


def test_delete_refuses_to_escape_the_download_folder(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "files")
    keep = tmp_path / "elsewhere"
    keep.mkdir()
    (keep / "important.txt").write_text("still here")
    storage.delete("../elsewhere/important.txt")
    assert (keep / "important.txt").exists()
    storage.delete("")  # would name the root itself
    assert (tmp_path / "files").exists()
