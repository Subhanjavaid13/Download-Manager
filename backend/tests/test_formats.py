from pathlib import Path

import pytest

from app.core.formats import DownloadRequest, build_ydl_options

OUT = Path("/tmp/out")


def _pp_keys(opts: dict) -> list[str]:
    return [p["key"] for p in opts["postprocessors"]]


def test_mp3_default() -> None:
    opts = build_ydl_options(DownloadRequest(mode="audio"), OUT)
    assert opts["format"] == "bestaudio/best"
    assert _pp_keys(opts) == [
        "FFmpegExtractAudio",
        "FFmpegMetadata",
        "FFmpegThumbnailsConvertor",
        "EmbedThumbnail",
    ]
    extract = opts["postprocessors"][0]
    assert extract["preferredcodec"] == "mp3"
    assert extract["preferredquality"] == "192"
    assert opts["writethumbnail"] is True
    assert opts["windowsfilenames"] is True
    assert opts["noplaylist"] is True


def test_m4a_is_passthrough() -> None:
    opts = build_ydl_options(DownloadRequest(mode="audio", audio_format="m4a"), OUT)
    assert opts["format"].startswith("bestaudio[ext=m4a]")
    assert opts["postprocessors"][0]["preferredquality"] == "0"


def test_opus_is_passthrough() -> None:
    opts = build_ydl_options(DownloadRequest(mode="audio", audio_format="opus"), OUT)
    assert opts["format"].startswith("bestaudio[acodec=opus]")


def test_audio_without_thumbnail() -> None:
    opts = build_ydl_options(DownloadRequest(mode="audio", embed_thumbnail=False), OUT)
    assert "EmbedThumbnail" not in _pp_keys(opts)
    assert "writethumbnail" not in opts


def test_video_1080p() -> None:
    opts = build_ydl_options(DownloadRequest(mode="video", video_height=1080), OUT)
    assert opts["format"].startswith("bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]")
    assert opts["merge_output_format"] == "mp4"
    assert _pp_keys(opts) == ["FFmpegMetadata"]


def test_video_best() -> None:
    opts = build_ydl_options(DownloadRequest(mode="video", video_height=None), OUT)
    assert opts["format"].startswith("bestvideo[ext=mp4]+bestaudio[ext=m4a]")


def test_ffmpeg_location_passed_through() -> None:
    opts = build_ydl_options(DownloadRequest(mode="audio"), OUT, ffmpeg_location="/opt/ffmpeg")
    assert opts["ffmpeg_location"] == "/opt/ffmpeg"


def test_invalid_bitrate_rejected() -> None:
    with pytest.raises(ValueError):
        build_ydl_options(DownloadRequest(mode="audio", audio_bitrate=999), OUT)


def test_invalid_height_rejected() -> None:
    with pytest.raises(ValueError):
        build_ydl_options(DownloadRequest(mode="video", video_height=999), OUT)


def test_labels() -> None:
    assert DownloadRequest(mode="audio").label == "MP3 192 kbps"
    assert DownloadRequest(mode="audio", audio_format="m4a").label == "M4A"
    assert DownloadRequest(mode="video", video_height=720).label == "MP4 720p"
    assert DownloadRequest(mode="video", video_height=None).label == "MP4 best"
