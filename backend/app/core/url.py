"""Parse and validate YouTube URLs.

Accepts the forms people actually paste:
    https://www.youtube.com/watch?v=ID
    https://youtu.be/ID
    https://www.youtube.com/shorts/ID
    https://m.youtube.com/watch?v=ID
    https://music.youtube.com/watch?v=ID
    https://www.youtube.com/playlist?list=LIST
    https://www.youtube.com/embed/ID, /live/ID
Anything else is rejected before yt-dlp ever sees it.
"""

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlparse

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_PLAYLIST_ID = re.compile(r"^[A-Za-z0-9_-]{2,}$")
_PATH_PREFIXES = ("/shorts/", "/embed/", "/live/", "/v/")


class InvalidYouTubeUrl(ValueError):
    """Raised when the input is not a usable YouTube video or playlist link."""


def is_video_id(value: str | None) -> bool:
    """True for the 11-character ids YouTube gives videos."""
    return bool(value and _VIDEO_ID.match(value))


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def playlist_url(playlist_id: str) -> str:
    return f"https://www.youtube.com/playlist?list={playlist_id}"


@dataclass(frozen=True)
class ParsedUrl:
    kind: Literal["video", "playlist"]
    video_id: str | None
    playlist_id: str | None
    canonical: str


def parse_youtube_url(raw: str) -> ParsedUrl:
    raw = (raw or "").strip()
    if not raw:
        raise InvalidYouTubeUrl("Paste a YouTube link first.")
    if "://" not in raw:
        raw = "https://" + raw

    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host not in YOUTUBE_HOSTS:
        raise InvalidYouTubeUrl("Only YouTube links are supported.")

    query = parse_qs(parsed.query)
    path = parsed.path.rstrip("/") or "/"
    segments = path.split("/")

    video_id: str | None = None
    playlist_id: str | None = query.get("list", [None])[0]

    if host.endswith("youtu.be"):
        video_id = segments[1] if len(segments) > 1 else None
    elif path == "/watch":
        video_id = query.get("v", [None])[0]
    elif path.startswith(_PATH_PREFIXES) and len(segments) > 2:
        video_id = segments[2]

    if video_id and not _VIDEO_ID.match(video_id):
        video_id = None
    if playlist_id and not _PLAYLIST_ID.match(playlist_id):
        playlist_id = None

    if video_id:
        return ParsedUrl(
            kind="video",
            video_id=video_id,
            playlist_id=playlist_id,
            canonical=f"https://www.youtube.com/watch?v={video_id}",
        )
    if playlist_id:
        return ParsedUrl(
            kind="playlist",
            video_id=None,
            playlist_id=playlist_id,
            canonical=f"https://www.youtube.com/playlist?list={playlist_id}",
        )
    raise InvalidYouTubeUrl("That link has no video or playlist id.")
