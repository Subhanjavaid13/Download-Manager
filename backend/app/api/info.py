"""GET /api/v1/info — metadata preview before the user commits to a download."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool

from app.auth import User, get_current_user
from app.config import Settings, get_settings
from app.core.downloader import Downloader
from app.core.errors import to_friendly
from app.core.url import InvalidYouTubeUrl, parse_youtube_url
from app.deps import get_downloader, limiter
from app.schemas import InfoResponse

router = APIRouter(prefix="/api/v1", tags=["info"])


@router.get("/info", response_model=InfoResponse)
@limiter.limit(lambda: get_settings().rate_limit_info)
async def get_info(
    request: Request,
    url: str = Query(..., max_length=2048),
    _user: User | None = Depends(get_current_user),
    downloader: Downloader = Depends(get_downloader),
    settings: Settings = Depends(get_settings),
) -> InfoResponse:
    try:
        parsed = parse_youtube_url(url)
    except InvalidYouTubeUrl as exc:
        raise HTTPException(400, str(exc)) from exc
    if parsed.kind == "playlist":
        raise HTTPException(400, "Playlists are coming in a later phase. Paste a single video.")

    try:
        info = await run_in_threadpool(downloader.fetch_info, parsed.canonical)
    except Exception as exc:  # noqa: BLE001
        friendly = to_friendly(exc)
        raise HTTPException(friendly.http_status, friendly.message) from exc

    if info.is_live:
        raise HTTPException(400, "Live streams cannot be downloaded until they end.")
    if info.duration_sec and info.duration_sec > settings.max_duration_sec:
        hours = settings.max_duration_sec // 3600
        raise HTTPException(400, f"Videos longer than {hours} hours are not supported.")

    return InfoResponse(**info.as_dict(), kind=parsed.kind, playlist_id=parsed.playlist_id)
