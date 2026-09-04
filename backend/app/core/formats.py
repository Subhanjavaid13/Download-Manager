"""Translate a user's choice (audio/video + quality) into yt-dlp options.

This module is the heart of the product. Everything else is wrapping.

Notes on quality:
- YouTube's source audio is ~128 kbps AAC or ~130-160 kbps Opus. A 320 kbps MP3
  is not better than the source, only bigger. 192 kbps is the sensible default.
- M4A and Opus are copied without re-encoding when the source already matches,
  so they are the highest-fidelity choices.
- Video above 1080p is usually VP9/AV1 in WebM. We still ask for MP4 first and
  fall back to whatever exists, then merge into an MP4 container.

Notes on cookies:
- `cookies_file` is optional and off by default. When YouTube starts answering
  "Sign in to confirm you're not a bot", an operator exports the cookies of a
  throwaway YouTube account in Netscape format and points DM_COOKIES_FILE at it.
  yt-dlp then makes requests as that account. The file is a credential: it is
  git-ignored, must never be committed, and should be readable only by the
  service user. See backend/.env.example for the export steps.

Notes on playlists:
- `noplaylist` stays True on purpose. A playlist is expanded into its video ids
  first (Downloader.fetch_playlist) and each item is then downloaded as its own
  single-video job, which is what gives per-item progress, per-item files, and a
  failure that stops one item instead of the whole run.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Mode = Literal["audio", "video"]
AudioFormat = Literal["mp3", "m4a", "opus"]

AUDIO_BITRATES: tuple[int, ...] = (128, 192, 320)
VIDEO_HEIGHTS: tuple[int, ...] = (360, 480, 720, 1080, 1440, 2160)

OUTPUT_TEMPLATE = "%(title).150B [%(id)s].%(ext)s"


@dataclass(frozen=True)
class DownloadRequest:
    mode: Mode
    audio_format: AudioFormat = "mp3"
    audio_bitrate: int = 192
    video_height: int | None = 1080  # None means best available
    embed_metadata: bool = True
    embed_thumbnail: bool = True

    def validate(self) -> None:
        if self.mode == "audio" and self.audio_bitrate not in AUDIO_BITRATES:
            raise ValueError(f"audio_bitrate must be one of {AUDIO_BITRATES}")
        if self.mode == "video" and self.video_height is not None:
            if self.video_height not in VIDEO_HEIGHTS:
                raise ValueError(f"video_height must be one of {VIDEO_HEIGHTS} or null")

    @property
    def label(self) -> str:
        if self.mode == "audio":
            if self.audio_format == "mp3":
                return f"MP3 {self.audio_bitrate} kbps"
            return self.audio_format.upper()
        return f"MP4 {self.video_height}p" if self.video_height else "MP4 best"


def audio_format_selector(fmt: AudioFormat) -> str:
    if fmt == "m4a":
        return "bestaudio[ext=m4a]/bestaudio/best"
    if fmt == "opus":
        return "bestaudio[acodec=opus]/bestaudio/best"
    return "bestaudio/best"


def video_format_selector(height: int | None) -> str:
    if height is None:
        return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
    return (
        f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
        f"/bestvideo[height<={height}]+bestaudio"
        f"/best[height<={height}]/best"
    )


def build_ydl_options(
    req: DownloadRequest,
    out_dir: Path,
    ffmpeg_location: str | None = None,
    cookies_file: Path | None = None,
    max_bytes: int | None = None,
) -> dict:
    req.validate()
    opts: dict = {
        "outtmpl": str(out_dir / OUTPUT_TEMPLATE),
        "windowsfilenames": True,  # strip characters Windows forbids, on every OS
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
        "fragment_retries": 3,
        "overwrites": False,
        "postprocessors": [],
    }
    if ffmpeg_location:
        opts["ffmpeg_location"] = ffmpeg_location
    if cookies_file:
        opts["cookiefile"] = str(cookies_file)
    if max_bytes:
        # yt-dlp refuses a stream whose *declared* size is over the cap. Streams
        # that declare nothing are caught by the running total in downloader.py.
        opts["max_filesize"] = max_bytes

    if req.mode == "audio":
        opts["format"] = audio_format_selector(req.audio_format)
        quality = str(req.audio_bitrate) if req.audio_format == "mp3" else "0"
        opts["postprocessors"].append(
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": req.audio_format,
                "preferredquality": quality,
            }
        )
        if req.embed_metadata:
            opts["postprocessors"].append({"key": "FFmpegMetadata", "add_metadata": True})
        if req.embed_thumbnail:
            opts["writethumbnail"] = True
            # Convert to JPEG and crop the 16:9 thumbnail to a square so music
            # players show proper cover art instead of a letterboxed frame.
            opts["postprocessors"].append(
                {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"}
            )
            opts["postprocessor_args"] = {
                "thumbnailsconvertor+ffmpeg_o": ["-vf", "crop=min(iw\\,ih):min(iw\\,ih)"]
            }
            opts["postprocessors"].append(
                {"key": "EmbedThumbnail", "already_have_thumbnail": False}
            )
    else:
        opts["format"] = video_format_selector(req.video_height)
        opts["merge_output_format"] = "mp4"
        if req.embed_metadata:
            opts["postprocessors"].append({"key": "FFmpegMetadata", "add_metadata": True})

    return opts
