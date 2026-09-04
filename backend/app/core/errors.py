"""Map yt-dlp / FFmpeg failures to short, user-facing messages.

The full technical error is still logged; only the friendly version reaches the UI.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FriendlyError:
    code: str
    message: str
    http_status: int = 400


_RULES: list[tuple[tuple[str, ...], FriendlyError]] = [
    (
        ("private video",),
        FriendlyError("private", "This video is private, so it cannot be downloaded."),
    ),
    (
        ("video unavailable", "has been removed", "no longer available", "does not exist"),
        FriendlyError("unavailable", "This video is unavailable or has been removed."),
    ),
    (
        ("confirm your age", "age-restricted", "age restricted"),
        FriendlyError("age_restricted", "This video is age-restricted and needs a signed-in account."),
    ),
    (
        ("not available in your country", "geo", "blocked it in your country"),
        FriendlyError("geo_blocked", "This video is not available in the server's region."),
    ),
    (
        ("confirm you're not a bot", "sign in to confirm", "cookies"),
        FriendlyError(
            "bot_check",
            "YouTube asked for a sign-in check. Try again in a few minutes.",
            503,
        ),
    ),
    (
        ("ffmpeg not found", "ffprobe and ffmpeg not found", "ffmpeg is not installed"),
        FriendlyError("ffmpeg_missing", "The server is missing FFmpeg. Contact the admin.", 500),
    ),
    (
        ("is a live", "live stream", "premieres in"),
        FriendlyError("live", "Live streams and premieres cannot be downloaded until they end."),
    ),
    (
        ("unable to download webpage", "getaddrinfo", "connection", "timed out", "network"),
        FriendlyError("network", "Could not reach YouTube. Check the connection and retry.", 502),
    ),
    (
        ("unsupported url", "is not a valid url"),
        FriendlyError("invalid_url", "That does not look like a supported YouTube link."),
    ),
]

_DEFAULT = FriendlyError("download_failed", "The download failed. Please try again.", 500)


def to_friendly(exc: BaseException) -> FriendlyError:
    text = str(exc).lower()
    for needles, friendly in _RULES:
        if any(n in text for n in needles):
            return friendly
    return _DEFAULT
