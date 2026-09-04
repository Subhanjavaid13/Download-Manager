"""Thin wrapper around yt_dlp.YoutubeDL with progress reporting and cancellation.

No HTTP or UI code lives here. The API, a CLI, or a test can all drive this class.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yt_dlp

from app.core.formats import DownloadRequest, build_ydl_options

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


ProgressCallback = Callable[[Progress], None]


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
    def __init__(self, ffmpeg_location: str | None = None) -> None:
        self.ffmpeg_location = ffmpeg_location

    def fetch_info(self, url: str) -> MediaInfo:
        """Metadata preview without downloading anything."""
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return _summarize(info)

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
        opts = build_ydl_options(req, out_dir, self.ffmpeg_location)
        progress = Progress(stage="fetching")

        def emit() -> None:
            if on_progress:
                on_progress(progress)

        def check_cancel() -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError()

        def progress_hook(d: dict) -> None:
            check_cancel()
            status = d.get("status")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                done = d.get("downloaded_bytes") or 0
                progress.stage = "downloading"
                progress.downloaded_bytes = int(done)
                progress.total_bytes = int(total) if total else None
                progress.percent = round(100.0 * done / total, 1) if total else 0.0
                progress.speed_bps = d.get("speed")
                progress.eta_sec = d.get("eta")
                emit()
            elif status == "finished":
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
        path = Path(final)
        if not path.exists():
            raise FileNotFoundError(f"yt-dlp reported success but {path} is missing")

        progress.stage = "done"
        progress.percent = 100.0
        progress.detail = None
        emit()
        return path
