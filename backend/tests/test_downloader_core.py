"""Downloader behaviour that needs no network: the size cap, cookies, playlist listing.

yt_dlp.YoutubeDL is swapped for a fake that drives the real progress hooks, so
these tests exercise the shipping code path instead of a copy of it.
"""

from pathlib import Path

import pytest
import yt_dlp

from app.core.downloader import Downloader, PlaylistEntry
from app.core.errors import FileTooLargeError, to_friendly
from app.core.formats import DownloadRequest, build_ydl_options

AUDIO = DownloadRequest(mode="audio")
MB = 1024 * 1024


class FakeYDL:
    """Replays a script of progress events, then writes a file like yt-dlp would."""

    script: list[dict] = []
    file_bytes: int = 10
    info: dict | None = None
    last_opts: dict = {}

    def __init__(self, opts: dict) -> None:
        self.opts = opts
        FakeYDL.last_opts = opts

    def __enter__(self) -> "FakeYDL":
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def extract_info(self, url: str, download: bool = False) -> dict:
        if self.info is not None:
            return self.info
        for event in self.script:
            for hook in self.opts.get("progress_hooks", []):
                hook(event)
        out_dir = Path(self.opts["outtmpl"]).parent
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "Fake video [dQw4w9WgXcQ].mp3"
        path.write_bytes(b"x" * self.file_bytes)
        return {"id": "dQw4w9WgXcQ", "requested_downloads": [{"filepath": str(path)}]}

    def prepare_filename(self, info: dict) -> str:
        return str(Path(self.opts["outtmpl"]).parent / "Never written [dQw4w9WgXcQ].webm")


@pytest.fixture
def fake_ydl(monkeypatch: pytest.MonkeyPatch):
    def install(**attrs) -> type[FakeYDL]:
        cls = type("ScriptedYDL", (FakeYDL,), {"script": [], "file_bytes": 10, "info": None})
        for key, value in attrs.items():
            setattr(cls, key, value)
        monkeypatch.setattr(yt_dlp, "YoutubeDL", cls)
        return cls

    return install


# -- the file size cap -------------------------------------------------------


def test_option_carries_the_cap_to_yt_dlp(tmp_path: Path) -> None:
    opts = build_ydl_options(AUDIO, tmp_path, max_bytes=5 * MB)
    assert opts["max_filesize"] == 5 * MB
    assert "max_filesize" not in build_ydl_options(AUDIO, tmp_path)


def test_declared_size_over_the_cap_stops_the_download(fake_ydl, tmp_path: Path) -> None:
    fake_ydl(script=[{"status": "downloading", "downloaded_bytes": 1, "total_bytes": 90 * MB}])
    with pytest.raises(FileTooLargeError) as exc:
        Downloader(max_file_mb=50).download("u", AUDIO, tmp_path)
    assert "50 MB" in str(exc.value)
    assert "lower quality" in str(exc.value)


def test_streams_are_measured_together_not_one_at_a_time(fake_ydl, tmp_path: Path) -> None:
    """A 30 MB video plus a 30 MB audio track is 60 MB, and the cap is 50."""
    half = {"status": "downloading", "downloaded_bytes": 30 * MB, "total_bytes": 30 * MB}
    fake_ydl(
        script=[
            half,
            {"status": "finished", "downloaded_bytes": 30 * MB},
            half,  # the second stream: on its own it fits, together it does not
        ]
    )
    with pytest.raises(FileTooLargeError):
        Downloader(max_file_mb=50).download("u", DownloadRequest(mode="video"), tmp_path)


def test_a_stream_that_declares_no_size_is_still_stopped(fake_ydl, tmp_path: Path) -> None:
    fake_ydl(
        script=[
            {"status": "downloading", "downloaded_bytes": 1 * MB, "total_bytes": None},
            {"status": "downloading", "downloaded_bytes": 60 * MB, "total_bytes": None},
        ]
    )
    with pytest.raises(FileTooLargeError):
        Downloader(max_file_mb=50).download("u", AUDIO, tmp_path)


def test_a_file_that_grows_during_conversion_is_caught(fake_ydl, tmp_path: Path) -> None:
    fake_ydl(script=[], file_bytes=3 * MB)
    with pytest.raises(FileTooLargeError):
        Downloader(max_file_mb=1).download("u", AUDIO, tmp_path)


def test_yt_dlps_own_abort_is_reported_as_a_size_problem(fake_ydl, tmp_path: Path) -> None:
    """yt-dlp aborts an oversized download itself and still returns success.

    Without translation the user would get "the download failed, please try
    again" and retry forever on a video that can never fit.
    """
    fake_ydl(info={"filesize": 90 * MB, "requested_downloads": [{"filepath": None}]})
    with pytest.raises(FileTooLargeError) as exc:
        Downloader(max_file_mb=50).download("u", AUDIO, tmp_path)
    assert "50 MB" in str(exc.value)


def test_a_missing_file_for_any_other_reason_still_says_so(fake_ydl, tmp_path: Path) -> None:
    fake_ydl(info={"requested_downloads": [{"filepath": None}]})
    with pytest.raises(FileNotFoundError):
        Downloader(max_file_mb=50).download("u", AUDIO, tmp_path)


def test_a_normal_download_is_untouched(fake_ydl, tmp_path: Path) -> None:
    fake_ydl(script=[{"status": "downloading", "downloaded_bytes": 500, "total_bytes": 1000}])
    path = Downloader(max_file_mb=50).download("u", AUDIO, tmp_path)
    assert path.read_bytes() == b"x" * 10


def test_no_cap_configured_means_no_cap(fake_ydl, tmp_path: Path) -> None:
    fake_ydl(script=[{"status": "downloading", "downloaded_bytes": 1, "total_bytes": 900 * MB}])
    assert Downloader().download("u", AUDIO, tmp_path).exists()


def test_the_cap_is_reported_in_plain_english() -> None:
    friendly = to_friendly(FileTooLargeError(500))
    assert friendly.code == "file_too_large"
    assert friendly.http_status == 413
    assert "500 MB" in friendly.message


# -- cookies -----------------------------------------------------------------


def test_cookies_file_reaches_yt_dlp(fake_ydl, tmp_path: Path) -> None:
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    fake_ydl(script=[])
    dl = Downloader(cookies_file=cookies)
    dl.download("u", AUDIO, tmp_path / "out")
    assert FakeYDL.last_opts["cookiefile"] == str(cookies)

    fake_ydl(info={"id": "dQw4w9WgXcQ", "title": "t", "formats": []})
    dl.fetch_info("u")
    assert FakeYDL.last_opts["cookiefile"] == str(cookies)


def test_no_cookies_file_means_no_option(fake_ydl, tmp_path: Path) -> None:
    fake_ydl(script=[])
    Downloader().download("u", AUDIO, tmp_path)
    assert "cookiefile" not in FakeYDL.last_opts


# -- playlist listing --------------------------------------------------------


PLAYLIST = {
    "id": "PL1234",
    "title": "Road trip",
    "channel": "Someone",
    "entries": [
        {"id": "dQw4w9WgXcQ", "title": "One", "duration": 213.0},
        {"id": "aaaaaaaaaaa", "title": "Two", "thumbnails": [{"url": "https://img/two.jpg"}]},
        None,  # yt-dlp yields None for an entry it could not read
        {"id": "PLnested", "title": "A nested playlist"},  # not a video: skipped
        {"id": "ccccccccccc", "title": "Three", "duration": 100},
    ],
}


def test_playlist_listing_keeps_only_real_videos(fake_ydl) -> None:
    fake_ydl(info=PLAYLIST)
    info = Downloader().fetch_playlist("https://www.youtube.com/playlist?list=PL1234")
    assert info.title == "Road trip"
    assert info.channel == "Someone"
    assert [e.id for e in info.entries] == ["dQw4w9WgXcQ", "aaaaaaaaaaa", "ccccccccccc"]
    assert info.count == 3
    assert info.truncated is False
    assert info.entries[0].duration_sec == 213
    assert info.entries[1].thumbnail == "https://img/two.jpg"
    # No thumbnail in the listing: YouTube's predictable one keeps the UI populated.
    assert info.entries[0].thumbnail.endswith("dQw4w9WgXcQ/hqdefault.jpg")


def test_playlist_over_the_limit_is_flagged_and_trimmed(fake_ydl) -> None:
    fake_ydl(info=PLAYLIST)
    info = Downloader().fetch_playlist("https://www.youtube.com/playlist?list=PL1234", limit=2)
    assert info.truncated is True
    assert info.count == 2
    assert FakeYDL.last_opts["playlistend"] == 3  # one more than the cap, to see past it
    assert FakeYDL.last_opts["extract_flat"] == "in_playlist"


def test_playlist_exactly_at_the_limit_is_not_flagged(fake_ydl) -> None:
    fake_ydl(info=PLAYLIST)
    info = Downloader().fetch_playlist("https://www.youtube.com/playlist?list=PL1234", limit=3)
    assert info.truncated is False
    assert info.count == 3


def test_playlist_entry_serialises_for_the_api() -> None:
    entry = PlaylistEntry(id="dQw4w9WgXcQ", title="One", duration_sec=1, thumbnail=None)
    assert entry.as_dict() == {
        "id": "dQw4w9WgXcQ",
        "title": "One",
        "duration_sec": 1,
        "thumbnail": None,
    }
