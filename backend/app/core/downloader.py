"""Thin wrapper around yt_dlp.YoutubeDL with progress reporting and cancellation.

No HTTP or UI code lives here. The API, a CLI, or a test can all drive this class.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yt_dlp

from app.core.errors import FileTooLargeError
from app.core.formats import DownloadRequest, build_ydl_options
from app.core.url import is_video_id

log = logging.getLogger(__name__)


class CancelledError(Exception):
    """Raised inside a yt-dlp hook to abort a running download."""


@dataclass
class Progress:
    stage: str = "queued"  # queued | fetching | downloading | processing | done | error | cancelled
    percent: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed_bps: float | None = None
    eta_sec: int | None = None
    detail: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MediaInfo:
    id: str
    title: str
    channel: str | None
    duration_sec: int | None
    thumbnail: str | None
    webpage_url: str
    is_live: bool
    available_heights: list[int] = field(default_factory=list)
    has_audio: bool = True

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PlaylistEntry:
    """One video listed in a playlist, from a flat (cheap) extraction."""

    id: str
    title: str
    duration_sec: int | None = None
    thumbnail: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PlaylistInfo:
    id: str
    title: str
    channel: str | None
    entries: list[PlaylistEntry]
    truncated: bool = False  # True when the playlist holds more than `limit` videos

    @property
    def count(self) -> int:
        return len(self.entries)

    @property
    def thumbnail(self) -> str | None:
        return self.entries[0].thumbnail if self.entries else None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "channel": self.channel,
            "count": self.count,
            "truncated": self.truncated,
            "entries": [e.as_dict() for e in self.entries],
        }


ProgressCallback = Callable[[Progress], None]


def _declared_size(info: dict, requested: list[dict]) -> int:
    """The largest size yt-dlp said this download would be; 0 when it never said."""
    sizes = [
        int(value)
        for source in [*requested, info]
        for key in ("filesize", "filesize_approx")
        if (value := source.get(key))
    ]
    return max(sizes, default=0)


def _entry_thumbnail(entry: dict, video_id: str) -> str:
    """Best thumbnail the flat listing offered, else YouTube's predictable one."""
    thumbs = entry.get("thumbnails") or []
    if thumbs and isinstance(thumbs[-1], dict) and thumbs[-1].get("url"):
        return str(thumbs[-1]["url"])
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def _summarize(info: dict) -> MediaInfo:
    heights: set[int] = set()
    has_audio = False
    for f in info.get("formats") or []:
        if f.get("vcodec") not in (None, "none") and f.get("height"):
            heights.add(int(f["height"]))
        if f.get("acodec") not in (None, "none"):
            has_audio = True
    return MediaInfo(
        id=info.get("id", ""),
        title=info.get("title") or "Untitled",
        channel=info.get("channel") or info.get("uploader"),
        duration_sec=int(info["duration"]) if info.get("duration") else None,
        thumbnail=info.get("thumbnail"),
        webpage_url=info.get("webpage_url") or info.get("original_url", ""),
        is_live=bool(info.get("is_live")),
        available_heights=sorted(heights),
        has_audio=has_audio,
    )


class Downloader:
    def __init__(
        self,
        ffmpeg_location: str | None = None,
        cookies_file: Path | None = None,
        max_file_mb: int | None = None,
    ) -> None:
        self.ffmpeg_location = ffmpeg_location
        self.cookies_file = cookies_file
        self.max_file_mb = max_file_mb

    @property
    def max_bytes(self) -> int | None:
        return self.max_file_mb * 1024 * 1024 if self.max_file_mb else None

    def _read_opts(self) -> dict:
        """Options shared by the two metadata calls."""
        opts: dict = {"quiet": True, "no_warnings": True, "skip_download": True}
        if self.cookies_file:
            opts["cookiefile"] = str(self.cookies_file)
        return opts

    def fetch_info(self, url: str) -> MediaInfo:
        """Metadata preview without downloading anything."""
        opts = self._read_opts() | {"noplaylist": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return _summarize(info)

    def fetch_playlist(self, url: str, limit: int | None = None) -> PlaylistInfo:
        """List the videos in a playlist without resolving each one.

        Flat extraction asks YouTube for the index only, so a 50-item playlist
        costs about one request instead of fifty. `limit` fetches one extra entry
        so the caller can tell "exactly at the cap" from "over the cap".
        """
        opts = self._read_opts() | {"extract_flat": "in_playlist", "noplaylist": False}
        if limit is not None:
            opts["playlistend"] = limit + 1
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        entries: list[PlaylistEntry] = []
        for raw in info.get("entries") or []:
            if not raw:
                continue  # yt-dlp yields None for entries it could not read
            video_id = raw.get("id") or ""
            if not is_video_id(video_id):
                continue  # nested playlists and channel rows are not downloadable items
            duration = raw.get("duration")
            entries.append(
                PlaylistEntry(
                    id=video_id,
                    title=raw.get("title") or "Untitled",
                    duration_sec=int(duration) if duration else None,
                    thumbnail=_entry_thumbnail(raw, video_id),
                )
            )

        truncated = limit is not None and len(entries) > limit
        if truncated:
            entries = entries[:limit]
        return PlaylistInfo(
            id=info.get("id") or "",
            title=info.get("title") or "Playlist",
            channel=info.get("channel") or info.get("uploader"),
            entries=entries,
            truncated=truncated,
        )

    def download(
        self,
        url: str,
        req: DownloadRequest,
        out_dir: Path,
        on_progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        """Download + post-process. Returns the path of the finished file."""
        out_dir.mkdir(parents=True, exist_ok=True)
        max_bytes = self.max_bytes
        opts = build_ydl_options(req, out_dir, self.ffmpeg_location, self.cookies_file, max_bytes)
        progress = Progress(stage="fetching")
        # A video job downloads two streams (video, then audio) before merging, so
        # the cap has to be measured against their running total, not one stream.
        finished_bytes = 0

        def emit() -> None:
            if on_progress:
                on_progress(progress)

        def check_cancel() -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError()

        def check_size(consumed: int) -> None:
            if max_bytes and consumed > max_bytes:
                raise FileTooLargeError(self.max_file_mb or 0)

        def progress_hook(d: dict) -> None:
            nonlocal finished_bytes
            check_cancel()
            status = d.get("status")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                done = d.get("downloaded_bytes") or 0
                # Stop as soon as the size is known to be over, and again on the
                # bytes actually written, for streams that declare no size at all.
                check_size(finished_bytes + int(total or 0))
                check_size(finished_bytes + int(done))
                progress.stage = "downloading"
                progress.downloaded_bytes = int(done)
                progress.total_bytes = int(total) if total else None
                progress.percent = round(100.0 * done / total, 1) if total else 0.0
                progress.speed_bps = d.get("speed")
                progress.eta_sec = d.get("eta")
                emit()
            elif status == "finished":
                finished_bytes += int(d.get("downloaded_bytes") or 0)
                check_size(finished_bytes)
                progress.stage = "processing"
                progress.percent = 100.0
                progress.detail = "Converting"
                emit()

        def postprocessor_hook(d: dict) -> None:
            check_cancel()
            if d.get("status") == "started":
                progress.stage = "processing"
                progress.detail = d.get("postprocessor")
                emit()

        opts["progress_hooks"] = [progress_hook]
        opts["postprocessor_hooks"] = [postprocessor_hook]

        emit()
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

        requested = info.get("requested_downloads") or []
        final = requested[0].get("filepath") if requested else None
        if not final:
            final = ydl.prepare_filename(info)
        path = Path(final) if final else None
        if path is None or not path.exists():
            # yt-dlp aborts a download whose declared size is over max_filesize and
            # still returns "success", so translate that into the size error the
            # user can act on instead of a puzzling missing file.
            check_size(_declared_size(info, requested))
            raise FileNotFoundError(f"yt-dlp reported success but {path} is missing")
        # Last word on the cap: re-encoding can grow a file past a limit the
        # download itself never reached.
        check_size(path.stat().st_size)

        progress.stage = "done"
        progress.percent = 100.0
        progress.detail = None
        emit()
        return path
