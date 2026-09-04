"""Jobs: create a download, poll its progress, fetch the file, cancel it, list history."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, RedirectResponse

from app.auth import User, auth_enabled, get_current_user
from app.config import Settings, get_settings
from app.core.downloader import Downloader
from app.core.errors import to_friendly
from app.core.formats import DownloadRequest
from app.core.url import InvalidYouTubeUrl, parse_youtube_url
from app.deps import get_accounts, get_downloader, get_job_store, get_owner, limiter
from app.jobs.store import JobStore, Owner
from app.schemas import JobCreate, JobResponse
from app.services.accounts import Accounts
from app.storage import content_disposition

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _get_or_404(store: JobStore, job_id: str, owner: Owner) -> dict:
    job = store.get(job_id, owner)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    return job


@router.post("", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(lambda: get_settings().rate_limit_jobs)
async def create_job(
    request: Request,
    body: JobCreate,
    user: User | None = Depends(get_current_user),
    owner: Owner = Depends(get_owner),
    store: JobStore = Depends(get_job_store),
    downloader: Downloader = Depends(get_downloader),
    accounts: Accounts = Depends(get_accounts),
    settings: Settings = Depends(get_settings),
) -> JobResponse:
    try:
        parsed = parse_youtube_url(body.url)
    except InvalidYouTubeUrl as exc:
        raise HTTPException(400, str(exc)) from exc
    if parsed.kind == "playlist" or not parsed.video_id:
        raise HTTPException(400, "Playlists are coming in a later phase. Paste a single video.")

    _enforce_quota(user, owner, accounts, settings)

    # Resolve metadata first so history has a title and we can refuse bad videos early.
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

    req = DownloadRequest(
        mode=body.mode,
        audio_format=body.audio_format,
        audio_bitrate=body.audio_bitrate,
        video_height=body.video_height,
    )
    job = store.submit(video_id=parsed.video_id, req=req, owner=owner, info=info)
    accounts.record(
        "download_started",
        user_id=user.id if user else None,
        properties={
            "mode": req.mode,
            "format": job["format"],
            "quality": job["quality"],
            "video_id": parsed.video_id,
            "anonymous": user is None,
        },
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return JobResponse(**job)


def _enforce_quota(user: User | None, owner: Owner, accounts: Accounts, settings: Settings) -> None:
    """Who may start a download right now, and how many today.

    Auth off (development): anyone, unlimited.
    Auth on, anonymous:     DM_ANON_DAILY_LIMIT per browser, unless DM_REQUIRE_AUTH.
    Auth on, signed in:     must be email-verified; profiles.daily_quota per day.
    """
    if not auth_enabled(settings):
        return
    if user is None:
        if settings.require_auth:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to download.")
        if owner.client_id is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to download.")
        used = accounts.anonymous_downloads_today(owner.client_id)
        if used >= settings.anon_daily_limit:
            accounts.record("quota_hit", properties={"anonymous": True, "used": used})
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"You have used today's {settings.anon_daily_limit} free downloads. "
                "Sign in for more.",
            )
        return
    if not user.email_verified:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Verify your email address first. Check your inbox."
        )
    quota = accounts.quota_for(user)
    used = accounts.downloads_today(user.id)
    if used >= quota:
        accounts.record("quota_hit", user_id=user.id, properties={"used": used, "quota": quota})
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Daily limit of {quota} downloads reached. Try again tomorrow.",
        )


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    limit: int = Query(20, ge=1, le=100),
    owner: Owner = Depends(get_owner),
    store: JobStore = Depends(get_job_store),
) -> list[JobResponse]:
    return [JobResponse(**j) for j in store.list_for(owner, limit=limit)]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    owner: Owner = Depends(get_owner),
    store: JobStore = Depends(get_job_store),
) -> JobResponse:
    return JobResponse(**_get_or_404(store, job_id, owner))


@router.get("/{job_id}/file")
async def get_file(
    job_id: str,
    owner: Owner = Depends(get_owner),
    store: JobStore = Depends(get_job_store),
):
    job = _get_or_404(store, job_id, owner)
    if not job["file_available"]:
        if job["status"] == "done":
            raise HTTPException(status.HTTP_410_GONE, "This file has expired. Download it again.")
        raise HTTPException(status.HTTP_409_CONFLICT, "The file is not ready yet.")

    if job["direct_url"]:
        # R2: hand the browser a signed link; bytes never pass through this server.
        return RedirectResponse(job["direct_url"], status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    local = store.local_file(job_id, owner)
    if local is None:
        raise HTTPException(status.HTTP_410_GONE, "This file has expired. Download it again.")
    path, filename = local
    return FileResponse(
        path,
        media_type="application/octet-stream",
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_job(
    job_id: str,
    owner: Owner = Depends(get_owner),
    store: JobStore = Depends(get_job_store),
) -> None:
    _get_or_404(store, job_id, owner)
    store.cancel(job_id, owner)
