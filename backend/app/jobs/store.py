"""Database-backed job queue (Phase 1).

A job is one download request stored as a `downloads` row. Jobs run on a small
thread pool in this process, write progress to the database (throttled), can be
cancelled, survive an API restart as history, and have their files removed after
a TTL by a janitor thread.

Ownership: a job belongs to a signed-in user (user_id) or to an anonymous
browser (client_id from the X-Client-Id header). Callers pass an Owner and only
see their own rows.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.downloader import CancelledError, Downloader, MediaInfo, Progress
from app.core.errors import to_friendly
from app.core.formats import DownloadRequest
from app.db import session_scope
from app.models import ACTIVE_STATUSES, Download, utcnow
from app.storage import Storage

log = logging.getLogger(__name__)

PROGRESS_WRITE_INTERVAL = 0.5  # seconds between progress rows written to the DB


@dataclass(frozen=True)
class Owner:
    user_id: str | None = None
    client_id: str | None = None

    def owns(self, job: Download) -> bool:
        if job.user_id is not None:
            return self.user_id is not None and str(job.user_id) == self.user_id
        if job.client_id is not None:
            return self.client_id == job.client_id
        return True  # legacy row with no owner: the id is unguessable


def job_to_dict(job: Download, storage: Storage, ttl_sec: int) -> dict:
    available = job.file_available()
    direct = (
        storage.download_url(job.storage_key, job.filename or "download", ttl_sec)
        if available and job.storage_key
        else None
    )
    return {
        "id": str(job.id),
        "video_id": job.video_id,
        "url": job.canonical_url,
        "title": job.title,
        "channel": job.channel,
        "thumbnail": job.thumbnail,
        "duration_sec": job.duration_sec,
        "mode": job.mode,
        "format": job.format,
        "quality": job.quality,
        "label": job.label,
        "status": job.status,
        "progress": {
            "stage": job.status,
            "percent": job.percent,
            "downloaded_bytes": job.downloaded_bytes,
            "total_bytes": job.total_bytes,
            "speed_bps": job.speed_bps,
            "eta_sec": job.eta_sec,
            "detail": job.detail,
        },
        "filename": job.filename,
        "size_bytes": job.size_bytes,
        "file_available": available,
        "file_url": f"/api/v1/jobs/{job.id}/file" if available else None,
        "direct_url": direct,
        "expires_at": _iso(job.expires_at) if available else None,
        "error": (
            {"code": job.error_code, "message": job.error_message} if job.error_code else None
        ),
        "created_at": _iso(job.created_at),
        "finished_at": _iso(job.finished_at),
    }


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat().replace("+00:00", "Z")


class JobStore:
    def __init__(
        self,
        *,
        downloader: Downloader,
        storage: Storage,
        session_factory: sessionmaker[Session],
        work_dir: Path,
        concurrency: int = 2,
        ttl_minutes: int = 60,
        sweep_interval_sec: float = 60.0,
    ) -> None:
        self._downloader = downloader
        self._storage = storage
        self._sessions = session_factory
        self._work_dir = work_dir
        self._ttl = timedelta(minutes=ttl_minutes)
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="dl")
        self._stop = threading.Event()
        self._janitor = threading.Thread(
            target=self._sweep_loop, args=(sweep_interval_sec,), daemon=True, name="janitor"
        )
        self._janitor.start()

    # -- public API -----------------------------------------------------------

    def submit(
        self,
        *,
        video_id: str,
        req: DownloadRequest,
        owner: Owner,
        info: MediaInfo | None = None,
    ) -> dict:
        quality = (
            str(req.audio_bitrate)
            if req.mode == "audio" and req.audio_format == "mp3"
            else None
            if req.mode == "audio"
            else str(req.video_height)
            if req.video_height
            else "best"
        )
        job = Download(
            id=uuid.uuid4(),
            user_id=uuid.UUID(owner.user_id) if owner.user_id else None,
            client_id=owner.client_id,
            video_id=video_id,
            title=info.title if info else None,
            channel=info.channel if info else None,
            duration_sec=info.duration_sec if info else None,
            thumbnail=info.thumbnail if info else None,
            mode=req.mode,
            format=req.audio_format if req.mode == "audio" else "mp4",
            quality=quality,
            status="queued",
        )
        with session_scope(self._sessions) as s:
            s.add(job)
            s.flush()
            snapshot = self._snapshot(job)
        self._enqueue(str(job.id), req)
        return snapshot

    def get(self, job_id: str, owner: Owner) -> dict | None:
        with session_scope(self._sessions) as s:
            job = self._load(s, job_id)
            if job is None or not owner.owns(job):
                return None
            return self._snapshot(job)

    def list_for(self, owner: Owner, limit: int = 20) -> list[dict]:
        if owner.user_id is None and owner.client_id is None:
            return []
        with session_scope(self._sessions) as s:
            stmt = select(Download).order_by(Download.created_at.desc()).limit(limit)
            if owner.user_id:
                stmt = stmt.where(Download.user_id == uuid.UUID(owner.user_id))
            else:
                stmt = stmt.where(Download.user_id.is_(None), Download.client_id == owner.client_id)
            return [self._snapshot(j) for j in s.scalars(stmt)]

    def cancel(self, job_id: str, owner: Owner) -> bool:
        with session_scope(self._sessions) as s:
            job = self._load(s, job_id)
            if job is None or not owner.owns(job) or not job.is_active:
                return False
            job.cancel_requested = True
            if job.status == "queued":
                self._finish(job, "cancelled")
        with self._lock:
            event = self._cancel_events.get(job_id)
        if event:
            event.set()
        return True

    def local_file(self, job_id: str, owner: Owner) -> tuple[Path, str] | None:
        """(path, filename) when the file is on local disk and still available."""
        with session_scope(self._sessions) as s:
            job = self._load(s, job_id)
            if job is None or not owner.owns(job) or not job.file_available():
                return None
            path = self._storage.local_path(job.storage_key or "")
            return (path, job.filename or path.name) if path else None

    def recover(self) -> int:
        """After a restart: mark in-flight jobs as interrupted, re-queue queued ones."""
        requeue: list[str] = []
        with session_scope(self._sessions) as s:
            for job in s.scalars(select(Download).where(Download.status.in_(ACTIVE_STATUSES))):
                if job.status == "queued" and not job.cancel_requested:
                    requeue.append(str(job.id))
                    continue
                self._finish(
                    job,
                    "error",
                    error_code="interrupted",
                    error_message="The server restarted during this download. Please try again.",
                )
                shutil.rmtree(self._work_dir / str(job.id), ignore_errors=True)
        for job_id in requeue:
            self._enqueue(job_id, None)
        return len(requeue)

    def sweep(self) -> int:
        """Delete files whose TTL passed. Rows stay as history. Returns files removed."""
        now = utcnow()
        removed = 0
        with session_scope(self._sessions) as s:
            stmt = select(Download).where(
                Download.storage_key.is_not(None), Download.expires_at < now
            )
            for job in s.scalars(stmt):
                self._storage.delete(job.storage_key or "")
                job.storage_key = None
                removed += 1
        if removed:
            log.info("sweep removed %d expired files", removed)
        return removed

    def shutdown(self) -> None:
        self._stop.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    # -- internals ------------------------------------------------------------

    def _enqueue(self, job_id: str, req: DownloadRequest | None) -> None:
        event = threading.Event()
        with self._lock:
            self._cancel_events[job_id] = event
        self._pool.submit(self._run, job_id, req, event)

    def _run(self, job_id: str, req: DownloadRequest | None, cancel_event: threading.Event) -> None:
        job_dir = self._work_dir / job_id
        try:
            with session_scope(self._sessions) as s:
                job = self._load(s, job_id)
                if job is None or job.status != "queued":
                    return
                if job.cancel_requested:
                    self._finish(job, "cancelled")
                    return
                job.status = "fetching"
                job.started_at = utcnow()
                url = job.canonical_url
                req = req or _request_from_row(job)

            last_write = 0.0

            def on_progress(p: Progress) -> None:
                nonlocal last_write
                now = time.monotonic()
                stage_changed = p.stage not in ("downloading",)
                if not stage_changed and now - last_write < PROGRESS_WRITE_INTERVAL:
                    return
                last_write = now
                with session_scope(self._sessions) as s:
                    row = self._load(s, job_id)
                    if row is None:
                        return
                    if p.stage in ACTIVE_STATUSES:
                        row.status = p.stage
                    row.percent = p.percent
                    row.downloaded_bytes = p.downloaded_bytes
                    row.total_bytes = p.total_bytes
                    row.speed_bps = p.speed_bps
                    row.eta_sec = p.eta_sec
                    row.detail = p.detail

            path = self._downloader.download(
                url, req, job_dir, on_progress=on_progress, cancel_event=cancel_event
            )
            stored = self._storage.store(job_id, path)
            with session_scope(self._sessions) as s:
                job = self._load(s, job_id)
                if job is None:
                    return
                job.filename = path.name
                job.size_bytes = stored.size_bytes
                job.storage_key = stored.key
                job.expires_at = utcnow() + self._ttl
                job.percent = 100.0
                job.detail = None
                self._finish(job, "done")
        except CancelledError:
            self._mark(job_id, "cancelled")
            shutil.rmtree(job_dir, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001 - every failure must be mapped
            log.exception("job %s failed", job_id)
            friendly = to_friendly(exc)
            self._mark(job_id, "error", error_code=friendly.code, error_message=friendly.message)
            shutil.rmtree(job_dir, ignore_errors=True)
        finally:
            with self._lock:
                self._cancel_events.pop(job_id, None)

    def _mark(self, job_id: str, status: str, **fields) -> None:
        with session_scope(self._sessions) as s:
            job = self._load(s, job_id)
            if job is not None:
                self._finish(job, status, **fields)

    @staticmethod
    def _finish(job: Download, status: str, **fields) -> None:
        job.status = status
        job.finished_at = utcnow()
        for k, v in fields.items():
            setattr(job, k, v)

    @staticmethod
    def _load(s: Session, job_id: str) -> Download | None:
        try:
            key = uuid.UUID(job_id)
        except ValueError:
            return None
        return s.get(Download, key)

    def _snapshot(self, job: Download) -> dict:
        return job_to_dict(job, self._storage, int(self._ttl.total_seconds()))

    def _sweep_loop(self, interval: float) -> None:
        while not self._stop.wait(interval):
            try:
                self.sweep()
            except Exception:  # noqa: BLE001
                log.exception("sweep failed")


def _request_from_row(job: Download) -> DownloadRequest:
    """Rebuild the request for a queued job that survived a restart."""
    if job.mode == "audio":
        bitrate = int(job.quality) if job.quality and job.quality.isdigit() else 192
        return DownloadRequest(mode="audio", audio_format=job.format, audio_bitrate=bitrate)  # type: ignore[arg-type]
    height = int(job.quality) if job.quality and job.quality.isdigit() else None
    return DownloadRequest(mode="video", video_height=height)
