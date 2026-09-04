"""Where finished files live after a job completes: a folder on this machine.

Everything downloaded is written under `DM_DOWNLOAD_DIR`, one folder per job,
and the API streams the bytes back from there. There is no remote object store
and no signed link: the file belongs to whoever runs this server, and it stays
on their disk until they delete it (or until `DM_FILE_RETENTION_MINUTES`, if
they set one, sweeps it away).
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredFile:
    key: str
    size_bytes: int


def content_disposition(filename: str) -> str:
    """RFC 6266 header value that keeps non-ASCII titles intact."""
    ascii_name = filename.encode("ascii", "replace").decode().replace('"', "'")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


class LocalStorage:
    """The download folder. Keys are `<job id>/<filename>`, relative to its root."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def store(self, job_id: str, path: Path) -> StoredFile:
        """Move a finished file out of the work folder into the keep folder."""
        target_dir = self.root / job_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / path.name
        if path.resolve() != target.resolve():
            shutil.move(str(path), str(target))
            if path.parent != target_dir and not any(path.parent.iterdir()):
                path.parent.rmdir()  # leave no empty work folder behind
        return StoredFile(key=f"{job_id}/{path.name}", size_bytes=target.stat().st_size)

    def local_path(self, key: str) -> Path | None:
        """The file on disk, or None if it is gone or the key points outside the root."""
        path = (self.root / key).resolve()
        if path == self.root or not path.is_relative_to(self.root):
            return None  # never serve outside the download root
        return path if path.is_file() else None

    def delete(self, key: str) -> None:
        """Remove the whole job folder, so nothing is left behind next to the file."""
        job_id = key.split("/", 1)[0]
        job_dir = (self.root / job_id).resolve()
        if job_dir == self.root or not job_dir.is_relative_to(self.root):
            log.warning("refusing to delete %s: outside the download folder", key)
            return
        shutil.rmtree(job_dir, ignore_errors=True)
