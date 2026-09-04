"""Where finished files live after a job completes.

LocalStorage  keeps the file on disk and the API streams it (development, or a
              single VPS with enough bandwidth).
R2Storage     uploads to Cloudflare R2 and hands out short-lived signed links, so
              users download from Cloudflare and the API pays no egress.

Both expose the same three operations, so the job store does not care which one
is active. Pick with DM_STORAGE=local|r2.
"""

from __future__ import annotations

import logging
import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredFile:
    key: str
    size_bytes: int


class Storage(Protocol):
    kind: str

    def store(self, job_id: str, path: Path) -> StoredFile:
        """Persist a finished file. May move or delete the original."""

    def download_url(self, key: str, filename: str, ttl_sec: int) -> str | None:
        """A direct link the browser can follow, or None if the API must stream it."""

    def local_path(self, key: str) -> Path | None:
        """Path on disk for streaming, or None if the file is remote."""

    def delete(self, key: str) -> None: ...


def content_disposition(filename: str) -> str:
    """RFC 6266 header value that keeps non-ASCII titles intact."""
    ascii_name = filename.encode("ascii", "replace").decode().replace('"', "'")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


class LocalStorage:
    kind = "local"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def store(self, job_id: str, path: Path) -> StoredFile:
        target_dir = self.root / job_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / path.name
        if path.resolve() != target.resolve():
            shutil.move(str(path), str(target))
        return StoredFile(key=f"{job_id}/{path.name}", size_bytes=target.stat().st_size)

    def download_url(self, key: str, filename: str, ttl_sec: int) -> str | None:
        return None  # the API streams local files itself

    def local_path(self, key: str) -> Path | None:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            return None  # never serve outside the download root
        return path if path.is_file() else None

    def delete(self, key: str) -> None:
        job_dir = self.root / key.split("/", 1)[0]
        shutil.rmtree(job_dir, ignore_errors=True)


class R2Storage:
    kind = "r2"

    def __init__(
        self,
        *,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        account_id: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        import boto3
        from botocore.config import Config

        if not endpoint_url and account_id:
            endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
        self.bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto" if endpoint_url else None,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    def store(self, job_id: str, path: Path) -> StoredFile:
        key = f"{job_id}/{path.name}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        size = path.stat().st_size
        self._client.upload_file(
            str(path), self.bucket, key, ExtraArgs={"ContentType": content_type}
        )
        shutil.rmtree(path.parent, ignore_errors=True)  # local copy no longer needed
        return StoredFile(key=key, size_bytes=size)

    def download_url(self, key: str, filename: str, ttl_sec: int) -> str | None:
        return self._client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentDisposition": content_disposition(filename),
            },
            ExpiresIn=ttl_sec,
        )

    def local_path(self, key: str) -> Path | None:
        return None

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except Exception:  # noqa: BLE001 - a lifecycle rule is the backstop
            log.warning("could not delete %s from R2", key, exc_info=True)


def build_storage(settings) -> Storage:  # noqa: ANN001 - avoids a config import cycle
    if settings.storage == "r2":
        missing = [
            name
            for name in ("r2_bucket", "r2_access_key_id", "r2_secret_access_key")
            if not getattr(settings, name)
        ]
        if missing or not (settings.r2_account_id or settings.r2_endpoint_url):
            raise RuntimeError(
                "DM_STORAGE=r2 needs DM_R2_BUCKET, DM_R2_ACCESS_KEY_ID, DM_R2_SECRET_ACCESS_KEY "
                "and DM_R2_ACCOUNT_ID (or DM_R2_ENDPOINT_URL)"
            )
        return R2Storage(
            bucket=settings.r2_bucket,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            account_id=settings.r2_account_id,
            endpoint_url=settings.r2_endpoint_url,
        )
    return LocalStorage(settings.download_dir)
