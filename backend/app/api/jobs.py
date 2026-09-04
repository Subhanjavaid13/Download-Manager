"""Jobs: create a download, poll its progress, fetch the file, cancel it, list history."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, RedirectResponse

from app.config import Settings, get_settings
from app.core.downloader import Downloader
from app.core.errors import to_friendly
from app.core.formats import DownloadRequest
from app.core.url import InvalidYouTubeUrl, parse_youtube_url
from app.deps import get_downloader, get_job_store, get_owner, limiter
from app.jobs.store import JobStore, Owner
from app.schemas import JobCreate, JobResponse
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
    owner: Owner = Depends(get_owner),
    store: JobStore = Depends(get_job_store),
    downloader: Downloader = Depends(get_downloader),
    settings: Settings = Depends(get_settings),
) -> JobResponse:
    try:
        parsed = parse_youtube_url(body.url)
    except InvalidYouTubeUrl as exc:
        raise HTTPException(400, str(exc)) from exc
    if parsed.kind == "playlist" or not parsed.video_id:
        raise HTTPException(400, "Playlists are coming in a later phase. Paste a single video.")

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
    return JobResponse(**job)


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
