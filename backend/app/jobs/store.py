"""In-memory job queue for Phase 1.

A job is one download request. Jobs run on a small thread pool, report progress,
can be cancelled, and their files are deleted after a TTL.

Phase 2 replaces this with a Postgres-backed `downloads` table (see
supabase/migrations) so history survives restarts and is per user. Keep the
public methods the same so the API layer does not change.
"""

import logging
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from app.core.downloader import CancelledError, Downloader, Progress
from app.core.errors import FriendlyError, to_friendly
from app.core.formats import DownloadRequest

log = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    url: str
    request: DownloadRequest
    user_id: str | None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    progress: Progress = field(default_factory=Progress)
    file_path: Path | None = None
    error: FriendlyError | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    @property
    def status(self) -> str:
        return self.progress.stage

    @property
    def filename(self) -> str | None:
        return self.file_path.name if self.file_path else None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "mode": self.request.mode,
            "label": self.request.label,
            "status": self.status,
            "progress": self.progress.as_dict(),
            "filename": self.filename,
            "size_bytes": self.file_path.stat().st_size
            if self.file_path and self.file_path.exists()
            else None,
            "error": {"code": self.error.code, "message": self.error.message}
            if self.error
            else None,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class JobStore:
    def __init__(
        self,
        downloader: Downloader,
        download_dir: Path,
        concurrency: int = 2,
        ttl_minutes: int = 60,
    ) -> None:
        self._downloader = downloader
        self._root = download_dir
        self._ttl = ttl_minutes * 60
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="dl")
        self._stop = threading.Event()
        self._janitor = threading.Thread(target=self._sweep_loop, daemon=True, name="janitor")
        self._janitor.start()

    # -- public API -----------------------------------------------------------

    def submit(self, url: str, req: DownloadRequest, user_id: str | None = None) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], url=url, request=req, user_id=user_id)
        with self._lock:
            self._jobs[job.id] = job
        self._pool.submit(self._run, job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_for_user(self, user_id: str | None) -> list[Job]:
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.user_id == user_id]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status in ("done", "error", "cancelled"):
            return False
        job.cancel_event.set()
        return True

    def shutdown(self) -> None:
        self._stop.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    # -- internals ------------------------------------------------------------

    def _run(self, job: Job) -> None:
        job_dir = self._root / job.id
        try:
            job.file_path = self._downloader.download(
                job.url,
                job.request,
                job_dir,
                on_progress=lambda p: setattr(job, "progress", p),
                cancel_event=job.cancel_event,
            )
        except CancelledError:
            job.progress.stage = "cancelled"
            shutil.rmtree(job_dir, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001 - we want every failure mapped
            log.exception("job %s failed", job.id)
            job.error = to_friendly(exc)
            job.progress.stage = "error"
            shutil.rmtree(job_dir, ignore_errors=True)
        finally:
            job.finished_at = time.time()

    def _sweep_loop(self) -> None:
        while not self._stop.wait(60):
            self._sweep()

    def _sweep(self) -> None:
        now = time.time()
        with self._lock:
            expired = [
                j for j in self._jobs.values() if j.finished_at and now - j.finished_at > self._ttl
            ]
            for j in expired:
                self._jobs.pop(j.id, None)
        for j in expired:
            shutil.rmtree(self._root / j.id, ignore_errors=True)
            log.info("expired job %s", j.id)
