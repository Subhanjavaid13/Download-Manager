"""Playlists: download every video in one, watch it progress, cancel the run.

The items themselves are ordinary jobs, so their files come from the existing
`GET /api/v1/jobs/{item_id}/file` and a single item can be cancelled with
`POST /api/v1/jobs/{item_id}/cancel` without stopping the rest of the playlist.
Deleting, though, is all-or-nothing here: `DELETE /api/v1/playlists/{id}` takes
the whole run away, so the counts on the parent row never describe rows that
have gone.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool

from app.api.guards import enforce_not_banned, enforce_quota
from app.auth import User, get_current_user
from app.config import Settings, get_settings
from app.core.downloader import Downloader, PlaylistInfo
from app.core.errors import to_friendly
from app.core.formats import DownloadRequest
from app.core.url import InvalidYouTubeUrl, parse_youtube_url
from app.deps import (
    client_ip,
    get_accounts,
    get_bans,
    get_downloader,
    get_job_store,
    get_owner,
    limiter,
)
from app.jobs.store import JobStore, Owner
from app.models import PLAYLIST_ACTIVE_STATUSES
from app.schemas import PlaylistCreate, PlaylistResponse
from app.services.accounts import Accounts
from app.services.bans import Bans

router = APIRouter(prefix="/api/v1/playlists", tags=["playlists"])


@router.post("", response_model=PlaylistResponse, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(lambda: get_settings().rate_limit_jobs)
async def create_playlist(
    request: Request,
    body: PlaylistCreate,
    user: User | None = Depends(get_current_user),
    owner: Owner = Depends(get_owner),
    store: JobStore = Depends(get_job_store),
    downloader: Downloader = Depends(get_downloader),
    accounts: Accounts = Depends(get_accounts),
    bans: Bans = Depends(get_bans),
    settings: Settings = Depends(get_settings),
) -> PlaylistResponse:
    try:
        parsed = parse_youtube_url(body.url)
    except InvalidYouTubeUrl as exc:
        raise HTTPException(400, str(exc)) from exc
    if not parsed.playlist_id:
        raise HTTPException(
            400,
            "That link has no playlist in it. Open the playlist on YouTube and copy "
            "the address from there, or download the single video instead.",
        )

    ip = client_ip(request, settings)
    enforce_not_banned(bans, user, ip)

    info = await _fetch_playlist(downloader, parsed.playlist_id, settings)
    # The whole playlist has to fit in what is left today, so nobody gets half of one.
    enforce_quota(user, owner, accounts, settings, cost=len(info.entries))

    req = DownloadRequest(
        mode=body.mode,
        audio_format=body.audio_format,
        audio_bitrate=body.audio_bitrate,
        video_height=body.video_height,
    )
    playlist = store.submit_playlist(
        playlist_id=parsed.playlist_id,
        entries=info.entries,
        req=req,
        owner=owner,
        title=info.title,
        channel=info.channel,
    )
    accounts.record(
        "playlist_started",
        user_id=user.id if user else None,
        properties={
            "mode": req.mode,
            "format": playlist["format"],
            "quality": playlist["quality"],
            "playlist_id": parsed.playlist_id,
            "items": playlist["total_items"],
            "anonymous": user is None,
        },
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    return PlaylistResponse(**playlist)


async def _fetch_playlist(
    downloader: Downloader, playlist_id: str, settings: Settings
) -> PlaylistInfo:
    """List the playlist, refusing the ones that are empty or too big to be fair."""
    limit = settings.max_playlist_items
    try:
        info = await run_in_threadpool(
            downloader.fetch_playlist, f"https://www.youtube.com/playlist?list={playlist_id}", limit
        )
    except Exception as exc:  # noqa: BLE001
        friendly = to_friendly(exc)
        raise HTTPException(friendly.http_status, friendly.message) from exc

    if not info.entries:
        raise HTTPException(
            400,
            "This playlist has no videos we can download. It may be private, or empty. "
            "Check the link opens for you in a private browser window.",
        )
    if info.truncated:
        raise HTTPException(
            400,
            f"This playlist has more than {limit} videos, which is the most this server "
            f"takes at once. Download it in batches of {limit} or fewer.",
        )
    return info


@router.get("", response_model=list[PlaylistResponse])
async def list_playlists(
    limit: int = Query(20, ge=1, le=100),
    owner: Owner = Depends(get_owner),
    store: JobStore = Depends(get_job_store),
) -> list[PlaylistResponse]:
    """Recent playlists. `items` is null here: fetch one by id to see its videos."""
    return [PlaylistResponse(**p) for p in store.list_playlists(owner, limit=limit)]


@router.get("/{playlist_id}", response_model=PlaylistResponse)
async def get_playlist(
    playlist_id: str,
    owner: Owner = Depends(get_owner),
    store: JobStore = Depends(get_job_store),
) -> PlaylistResponse:
    return PlaylistResponse(**_get_or_404(store, playlist_id, owner))


@router.post("/{playlist_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_playlist(
    playlist_id: str,
    owner: Owner = Depends(get_owner),
    store: JobStore = Depends(get_job_store),
) -> None:
    """Stop the run: the video downloading now and everything still waiting.

    The videos that already finished are kept, and stay in history.
    """
    _get_or_404(store, playlist_id, owner)
    store.cancel_playlist(playlist_id, owner)


@router.delete("/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_playlist(
    playlist_id: str,
    owner: Owner = Depends(get_owner),
    store: JobStore = Depends(get_job_store),
) -> None:
    """Delete a finished playlist: every video's file, and every row including this one."""
    playlist = _get_or_404(store, playlist_id, owner)
    if playlist["status"] in PLAYLIST_ACTIVE_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This playlist is still running. Stop it first, then delete it.",
        )
    store.delete_playlist(playlist_id, owner)


def _get_or_404(store: JobStore, playlist_id: str, owner: Owner) -> dict:
    playlist = store.get_playlist(playlist_id, owner)
    if playlist is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist not found.")
    return playlist
