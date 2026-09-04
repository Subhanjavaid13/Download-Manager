"""Database-backed job queue (Phase 1, playlists in Phase 6).

A job is one download request stored as a `downloads` row. Jobs run on a small
thread pool in this process, write progress to the database (throttled), can be
cancelled, survive an API restart as history, and have their files removed after
a TTL by a janitor thread.

A playlist is a `playlists` row plus one `downloads` row per video. It takes a
single worker slot and runs its items one after another, so a playlist never
starves the queue and YouTube sees a steady, human-ish rate. One item failing
does not stop the others: the failure is recorded on that item and summarised on
the parent when the run ends.

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
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.downloader import CancelledError, Downloader, MediaInfo, PlaylistEntry, Progress
from app.core.errors import to_friendly
from app.core.formats import DownloadRequest
from app.db import session_scope
from app.models import (
    ACTIVE_STATUSES,
    PLAYLIST_ACTIVE_STATUSES,
    Download,
    Playlist,
    utcnow,
)
from app.storage import Storage

log = logging.getLogger(__name__)

PROGRESS_WRITE_INTERVAL = 0.5  # seconds between progress rows written to the DB


@dataclass(frozen=True)
class Owner:
    user_id: str | None = None
    client_id: str | None = None

    def owns(self, job: Download | Playlist) -> bool:
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
        "user_id": str(job.user_id) if job.user_id else None,
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
        "playlist_job_id": str(job.playlist_job_id) if job.playlist_job_id else None,
        "playlist_index": job.playlist_index,
    }


def playlist_to_dict(pl: Playlist, items: list[dict] | None) -> dict:
    """`items` is None in list views, where loading every child would be wasteful."""
    return {
        "id": str(pl.id),
        "user_id": str(pl.user_id) if pl.user_id else None,
        "playlist_id": pl.playlist_id,
        "url": pl.canonical_url,
        "title": pl.title,
        "channel": pl.channel,
        "thumbnail": pl.thumbnail,
        "mode": pl.mode,
        "format": pl.format,
        "quality": pl.quality,
        "label": pl.label,
        "status": pl.status,
        "total_items": pl.total_items,
        "completed_items": pl.completed_items,
        "failed_items": pl.failed_items,
        "cancelled_items": pl.cancelled_items,
        "percent": pl.percent,
        "error": ({"code": pl.error_code, "message": pl.error_message} if pl.error_code else None),
        "created_at": _iso(pl.created_at),
        "finished_at": _iso(pl.finished_at),
        "items": items,
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
        on_finish: Callable[[dict], None] | None = None,
        on_playlist_finish: Callable[[dict], None] | None = None,
    ) -> None:
        self._downloader = downloader
        self._on_finish = on_finish
        self._on_playlist_finish = on_playlist_finish
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
        quality = _quality_of(req)
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

    def submit_playlist(
        self,
        *,
        playlist_id: str,
        entries: list[PlaylistEntry],
        req: DownloadRequest,
        owner: Owner,
        title: str | None = None,
        channel: str | None = None,
    ) -> dict:
        """Create the parent row plus one queued child per video, then run them in order."""
        if not entries:
            raise ValueError("a playlist download needs at least one video")
        quality = _quality_of(req)
        fmt = req.audio_format if req.mode == "audio" else "mp4"
        user_uuid = uuid.UUID(owner.user_id) if owner.user_id else None
        pl = Playlist(
            id=uuid.uuid4(),
            user_id=user_uuid,
            client_id=owner.client_id,
            playlist_id=playlist_id,
            title=title,
            channel=channel,
            thumbnail=entries[0].thumbnail,
            mode=req.mode,
            format=fmt,
            quality=quality,
            status="queued",
            total_items=len(entries),
        )
        with session_scope(self._sessions) as s:
            s.add(pl)
            s.flush()
            for index, entry in enumerate(entries):
                s.add(
                    Download(
                        id=uuid.uuid4(),
                        user_id=user_uuid,
                        client_id=owner.client_id,
                        video_id=entry.id,
                        title=entry.title,
                        duration_sec=entry.duration_sec,
                        thumbnail=entry.thumbnail,
                        mode=req.mode,
                        format=fmt,
                        quality=quality,
                        status="queued",
                        playlist_job_id=pl.id,
                        playlist_index=index,
                    )
                )
            s.flush()
            snapshot = self._playlist_snapshot(s, pl, with_items=True)
        self._enqueue_playlist(str(pl.id), req)
        return snapshot

    def get(self, job_id: str, owner: Owner) -> dict | None:
        with session_scope(self._sessions) as s:
            job = self._load(s, job_id)
            if job is None or not owner.owns(job):
                return None
            return self._snapshot(job)

    def get_playlist(self, playlist_id: str, owner: Owner) -> dict | None:
        with session_scope(self._sessions) as s:
            pl = self._load_playlist(s, playlist_id)
            if pl is None or not owner.owns(pl):
                return None
            return self._playlist_snapshot(s, pl, with_items=True)

    def list_for(
        self, owner: Owner, limit: int = 20, include_playlist_items: bool = False
    ) -> list[dict]:
        """History. Playlist items are hidden by default so 50 songs do not bury
        the single downloads around them; they are listed under their playlist."""
        if owner.user_id is None and owner.client_id is None:
            return []
        with session_scope(self._sessions) as s:
            stmt = select(Download).order_by(Download.created_at.desc()).limit(limit)
            if owner.user_id:
                stmt = stmt.where(Download.user_id == uuid.UUID(owner.user_id))
            else:
                stmt = stmt.where(Download.user_id.is_(None), Download.client_id == owner.client_id)
            if not include_playlist_items:
                stmt = stmt.where(Download.playlist_job_id.is_(None))
            return [self._snapshot(j) for j in s.scalars(stmt)]

    def list_playlists(self, owner: Owner, limit: int = 20) -> list[dict]:
        if owner.user_id is None and owner.client_id is None:
            return []
        with session_scope(self._sessions) as s:
            stmt = select(Playlist).order_by(Playlist.created_at.desc()).limit(limit)
            if owner.user_id:
                stmt = stmt.where(Playlist.user_id == uuid.UUID(owner.user_id))
            else:
                stmt = stmt.where(Playlist.user_id.is_(None), Playlist.client_id == owner.client_id)
            return [playlist_to_dict(pl, None) for pl in s.scalars(stmt)]

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

    def cancel_playlist(self, playlist_id: str, owner: Owner) -> bool:
        """Stop the whole run: the item downloading now, and everything still queued."""
        with session_scope(self._sessions) as s:
            pl = self._load_playlist(s, playlist_id)
            if pl is None or not owner.owns(pl) or not pl.is_active:
                return False
            pl.cancel_requested = True
            item_ids = [str(i) for i in self._item_ids(s, pl.id)]
            for item in s.scalars(
                select(Download).where(
                    Download.playlist_job_id == pl.id, Download.status == "queued"
                )
            ):
                item.cancel_requested = True
                self._finish(item, "cancelled")
            if pl.status == "queued":
                # Never started, so no worker will finalise it.
                self._finish(pl, "cancelled")
        with self._lock:
            events = [self._cancel_events.get(i) for i in [playlist_id, *item_ids]]
        for event in events:
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
        """After a restart: mark in-flight jobs as interrupted, re-queue queued ones.

        Playlist items are treated more kindly than single jobs: the run is
        re-queued and the item that died goes back to 'queued' to be retried,
        because losing item 34 of 50 to a deploy is worth one retry.
        """
        requeue: list[str] = []
        requeue_playlists: list[str] = []
        with session_scope(self._sessions) as s:
            for job in s.scalars(
                select(Download).where(
                    Download.status.in_(ACTIVE_STATUSES), Download.playlist_job_id.is_(None)
                )
            ):
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

            for pl in s.scalars(
                select(Playlist).where(Playlist.status.in_(PLAYLIST_ACTIVE_STATUSES))
            ):
                if pl.cancel_requested:
                    self._finish(pl, "cancelled")
                    continue
                for item in s.scalars(
                    select(Download).where(
                        Download.playlist_job_id == pl.id,
                        Download.status.in_(ACTIVE_STATUSES),
                        Download.status != "queued",
                    )
                ):
                    item.status = "queued"
                    item.percent = 0.0
                    item.downloaded_bytes = 0
                    item.detail = None
                    shutil.rmtree(self._work_dir / str(item.id), ignore_errors=True)
                requeue_playlists.append(str(pl.id))
        for job_id in requeue:
            self._enqueue(job_id, None)
        for playlist_id in requeue_playlists:
            self._enqueue_playlist(playlist_id, None)
        return len(requeue) + len(requeue_playlists)

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

    def delete_stored(self, key: str) -> None:
        """Remove one stored file (used when an account is deleted)."""
        try:
            self._storage.delete(key)
        except Exception:  # noqa: BLE001
            log.warning("could not delete %s", key, exc_info=True)

    def shutdown(self) -> None:
        self._stop.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    # -- internals ------------------------------------------------------------

    def _enqueue(self, job_id: str, req: DownloadRequest | None) -> None:
        event = threading.Event()
        with self._lock:
            self._cancel_events[job_id] = event
        self._pool.submit(self._run, job_id, req, event)

    def _enqueue_playlist(self, playlist_id: str, req: DownloadRequest | None) -> None:
        event = threading.Event()
        with self._lock:
            self._cancel_events[playlist_id] = event
        self._pool.submit(self._run_playlist, playlist_id, req, event)

    def _run(self, job_id: str, req: DownloadRequest | None, cancel_event: threading.Event) -> None:
        try:
            self._download_one(job_id, req, cancel_event)
        finally:
            with self._lock:
                self._cancel_events.pop(job_id, None)
            self._notify(job_id)

    def _run_playlist(
        self, playlist_id: str, req: DownloadRequest | None, cancel_event: threading.Event
    ) -> None:
        """One worker slot, items one at a time, failures recorded and stepped over."""
        try:
            with session_scope(self._sessions) as s:
                pl = self._load_playlist(s, playlist_id)
                if pl is None or not pl.is_active:
                    return
                if pl.cancel_requested:
                    self._finish(pl, "cancelled")
                    return
                pl.status = "running"
                pl.started_at = pl.started_at or utcnow()
                req = req or _request_from_playlist(pl)
                item_ids = [str(i) for i in self._item_ids(s, pl.id)]

            for item_id in item_ids:
                if cancel_event.is_set():
                    break
                with session_scope(self._sessions) as s:
                    row = self._load(s, item_id)
                    if row is None or row.status != "queued":
                        continue  # cancelled by the user, or already done before a restart
                item_event = threading.Event()
                with self._lock:
                    self._cancel_events[item_id] = item_event
                try:
                    self._download_one(item_id, req, item_event)
                finally:
                    with self._lock:
                        self._cancel_events.pop(item_id, None)
                    self._notify(item_id)
                self._refresh_counts(playlist_id)

            self._finalize_playlist(playlist_id, cancelled=cancel_event.is_set())
        except Exception:  # noqa: BLE001 - a broken run must still leave a readable row
            log.exception("playlist %s failed", playlist_id)
            self._finalize_playlist(playlist_id, cancelled=False)
        finally:
            with self._lock:
                self._cancel_events.pop(playlist_id, None)
            if self._on_playlist_finish is not None:
                try:
                    with session_scope(self._sessions) as s:
                        pl = self._load_playlist(s, playlist_id)
                        snapshot = playlist_to_dict(pl, None) if pl is not None else None
                    if snapshot is not None:
                        self._on_playlist_finish(snapshot)
                except Exception:  # noqa: BLE001
                    log.exception("on_playlist_finish hook failed for %s", playlist_id)

    def _download_one(
        self, job_id: str, req: DownloadRequest | None, cancel_event: threading.Event
    ) -> None:
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

    def _notify(self, job_id: str) -> None:
        if self._on_finish is None:
            return
        try:
            with session_scope(self._sessions) as s:
                row = self._load(s, job_id)
                snapshot = self._snapshot(row) if row is not None else None
            if snapshot is not None:
                self._on_finish(snapshot)
        except Exception:  # noqa: BLE001
            log.exception("on_finish hook failed for %s", job_id)

    def _refresh_counts(self, playlist_id: str) -> None:
        """Keep the parent's counters live so the UI can show '4 of 12 done'."""
        with session_scope(self._sessions) as s:
            pl = self._load_playlist(s, playlist_id)
            if pl is None:
                return
            counts = self._count_items(s, pl.id)
            pl.completed_items = counts["done"]
            pl.failed_items = counts["error"]
            pl.cancelled_items = counts["cancelled"]

    def _finalize_playlist(self, playlist_id: str, *, cancelled: bool) -> None:
        with session_scope(self._sessions) as s:
            pl = self._load_playlist(s, playlist_id)
            if pl is None or not pl.is_active:
                return
            # Nothing may stay 'queued' once the run is over: close the leftovers
            # (a cancel, or a crash in the loop) and bin their partial files.
            stopped = cancelled or pl.cancel_requested
            for item in s.scalars(
                select(Download).where(
                    Download.playlist_job_id == pl.id, Download.status.in_(ACTIVE_STATUSES)
                )
            ):
                if stopped:
                    self._finish(item, "cancelled")
                else:
                    self._finish(
                        item,
                        "error",
                        error_code="interrupted",
                        error_message=(
                            "This video was skipped because the playlist run stopped. "
                            "Start the playlist again to get it."
                        ),
                    )
                shutil.rmtree(self._work_dir / str(item.id), ignore_errors=True)
            s.flush()
            counts = self._count_items(s, pl.id)
            pl.completed_items = counts["done"]
            pl.failed_items = counts["error"]
            pl.cancelled_items = counts["cancelled"]

            if stopped:
                status, code, message = "cancelled", None, None
            elif counts["error"] == 0 and counts["cancelled"] == 0:
                status, code, message = "done", None, None
            elif counts["error"] == 0:
                # Items the user cancelled one by one: not a failure, not a clean run.
                status = "partial" if counts["done"] else "cancelled"
                code, message = None, None
            else:
                status = "partial" if counts["done"] else "error"
                code = self._top_error_code(s, pl.id) or "download_failed"
                kept = (
                    "The videos that worked are ready to save."
                    if counts["done"]
                    else "Check the link is public, then try again."
                )
                message = (
                    f"{counts['error']} of {pl.total_items} videos could not be downloaded. "
                    f"{kept} Open the list to see what went wrong with each one."
                )
            self._finish(pl, status, error_code=code, error_message=message)

    @staticmethod
    def _count_items(s: Session, playlist_id: uuid.UUID) -> dict[str, int]:
        rows = s.execute(
            select(Download.status, func.count())
            .where(Download.playlist_job_id == playlist_id)
            .group_by(Download.status)
        ).all()
        counts = {status: int(n) for status, n in rows}
        return {k: counts.get(k, 0) for k in ("done", "error", "cancelled", "queued")}

    @staticmethod
    def _top_error_code(s: Session, playlist_id: uuid.UUID) -> str | None:
        row = s.execute(
            select(Download.error_code, func.count().label("n"))
            .where(
                Download.playlist_job_id == playlist_id,
                Download.status == "error",
                Download.error_code.is_not(None),
            )
            .group_by(Download.error_code)
            .order_by(func.count().desc())
            .limit(1)
        ).first()
        return row[0] if row else None

    @staticmethod
    def _item_ids(s: Session, playlist_id: uuid.UUID) -> list[uuid.UUID]:
        return list(
            s.scalars(
                select(Download.id)
                .where(Download.playlist_job_id == playlist_id)
                .order_by(Download.playlist_index)
            )
        )

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

    @staticmethod
    def _load_playlist(s: Session, playlist_id: str) -> Playlist | None:
        try:
            key = uuid.UUID(playlist_id)
        except ValueError:
            return None
        return s.get(Playlist, key)

    def _snapshot(self, job: Download) -> dict:
        return job_to_dict(job, self._storage, int(self._ttl.total_seconds()))

    def _playlist_snapshot(self, s: Session, pl: Playlist, *, with_items: bool) -> dict:
        items = None
        if with_items:
            rows = s.scalars(
                select(Download)
                .where(Download.playlist_job_id == pl.id)
                .order_by(Download.playlist_index)
            )
            items = [self._snapshot(row) for row in rows]
        return playlist_to_dict(pl, items)

    def _sweep_loop(self, interval: float) -> None:
        while not self._stop.wait(interval):
            try:
                self.sweep()
            except Exception:  # noqa: BLE001
                log.exception("sweep failed")


def _quality_of(req: DownloadRequest) -> str | None:
    """The `quality` column: kbps for MP3, height for video, None for M4A/Opus."""
    if req.mode == "audio":
        return str(req.audio_bitrate) if req.audio_format == "mp3" else None
    return str(req.video_height) if req.video_height else "best"


def _request_from_row(job: Download) -> DownloadRequest:
    """Rebuild the request for a queued job that survived a restart."""
    if job.mode == "audio":
        bitrate = int(job.quality) if job.quality and job.quality.isdigit() else 192
        return DownloadRequest(mode="audio", audio_format=job.format, audio_bitrate=bitrate)  # type: ignore[arg-type]
    height = int(job.quality) if job.quality and job.quality.isdigit() else None
    return DownloadRequest(mode="video", video_height=height)


def _request_from_playlist(pl: Playlist) -> DownloadRequest:
    """Same, for a playlist run that survived a restart."""
    if pl.mode == "audio":
        bitrate = int(pl.quality) if pl.quality and pl.quality.isdigit() else 192
        return DownloadRequest(mode="audio", audio_format=pl.format, audio_bitrate=bitrate)  # type: ignore[arg-type]
    height = int(pl.quality) if pl.quality and pl.quality.isdigit() else None
    return DownloadRequest(mode="video", video_height=height)
