"""Jobs: create a download, poll its progress, fetch the file, cancel it."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse

from app.auth import User, get_current_user
from app.config import get_settings
from app.core.formats import DownloadRequest
from app.core.url import InvalidYouTubeUrl, parse_youtube_url
from app.deps import get_job_store, limiter
from app.jobs.store import Job, JobStore
from app.schemas import JobCreate, JobResponse

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _owned(job: Job | None, user: User | None) -> Job:
    if job is None or (job.user_id is not None and (user is None or job.user_id != user.id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    return job


@router.post("", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(lambda: get_settings().rate_limit_jobs)
async def create_job(
    request: Request,
    body: JobCreate,
    user: User | None = Depends(get_current_user),
    store: JobStore = Depends(get_job_store),
) -> JobResponse:
    try:
        parsed = parse_youtube_url(body.url)
    except InvalidYouTubeUrl as exc:
        raise HTTPException(400, str(exc)) from exc
    if parsed.kind == "playlist":
        raise HTTPException(400, "Playlists are coming in a later phase. Paste a single video.")

    req = DownloadRequest(
        mode=body.mode,
        audio_format=body.audio_format,
        audio_bitrate=body.audio_bitrate,
        video_height=body.video_height,
    )
    job = store.submit(parsed.canonical, req, user_id=user.id if user else None)
    return JobResponse(**job.as_dict())


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    user: User | None = Depends(get_current_user),
    store: JobStore = Depends(get_job_store),
) -> list[JobResponse]:
    return [JobResponse(**j.as_dict()) for j in store.list_for_user(user.id if user else None)]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    user: User | None = Depends(get_current_user),
    store: JobStore = Depends(get_job_store),
) -> JobResponse:
    return JobResponse(**_owned(store.get(job_id), user).as_dict())


@router.get("/{job_id}/file")
async def get_file(
    job_id: str,
    user: User | None = Depends(get_current_user),
    store: JobStore = Depends(get_job_store),
) -> FileResponse:
    job = _owned(store.get(job_id), user)
    if job.status != "done" or not job.file_path or not job.file_path.exists():
        raise HTTPException(status.HTTP_409_CONFLICT, "The file is not ready yet.")
    return FileResponse(
        job.file_path,
        filename=job.file_path.name,
        media_type="application/octet-stream",
    )


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_job(
    job_id: str,
    user: User | None = Depends(get_current_user),
    store: JobStore = Depends(get_job_store),
) -> None:
    job = _owned(store.get(job_id), user)
    store.cancel(job.id)
