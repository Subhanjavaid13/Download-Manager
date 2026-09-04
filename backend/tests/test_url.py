import pytest

from app.core.url import InvalidYouTubeUrl, parse_youtube_url

VIDEO = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "raw",
    [
        f"https://www.youtube.com/watch?v={VIDEO}",
        f"https://youtube.com/watch?v={VIDEO}&t=42s",
        f"https://m.youtube.com/watch?v={VIDEO}",
        f"https://music.youtube.com/watch?v={VIDEO}&list=RDAMVM{VIDEO}",
        f"https://youtu.be/{VIDEO}",
        f"https://youtu.be/{VIDEO}?si=abc123",
        f"https://www.youtube.com/shorts/{VIDEO}",
        f"https://www.youtube.com/embed/{VIDEO}",
        f"https://www.youtube.com/live/{VIDEO}",
        f"youtube.com/watch?v={VIDEO}",
        f"  https://www.youtube.com/watch?v={VIDEO}  ",
    ],
)
def test_video_urls_parse(raw: str) -> None:
    parsed = parse_youtube_url(raw)
    assert parsed.kind == "video"
    assert parsed.video_id == VIDEO
    assert parsed.canonical == f"https://www.youtube.com/watch?v={VIDEO}"


def test_watch_url_keeps_playlist_id() -> None:
    parsed = parse_youtube_url(f"https://www.youtube.com/watch?v={VIDEO}&list=PLabc123")
    assert parsed.kind == "video"
    assert parsed.playlist_id == "PLabc123"


def test_playlist_url() -> None:
    parsed = parse_youtube_url(
        "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
    )
    assert parsed.kind == "playlist"
    assert parsed.video_id is None
    assert parsed.canonical.endswith("list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf")


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "https://vimeo.com/12345",
        "https://example.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/",
        "https://www.youtube.com/watch?v=tooshort",
        "https://www.youtube.com/channel/UC1234567890",
        "javascript:alert(1)",
    ],
)
def test_rejects_bad_input(raw: str) -> None:
    with pytest.raises(InvalidYouTubeUrl):
        parse_youtube_url(raw)
