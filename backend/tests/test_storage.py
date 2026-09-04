from pathlib import Path
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from moto import mock_aws

from app.storage import LocalStorage, R2Storage, content_disposition


def _make_file(tmp_path: Path, name: str = "Song [abc].mp3") -> Path:
    job_dir = tmp_path / "work" / "job1"
    job_dir.mkdir(parents=True)
    path = job_dir / name
    path.write_bytes(b"abc")
    return path


def test_content_disposition_handles_unicode() -> None:
    header = content_disposition('Naïve "quote" 🎵.mp3')
    assert header.startswith("attachment; filename=\"Na?ve 'quote' ")
    assert "filename*=UTF-8''Na%C3%AFve%20%22quote%22%20%F0%9F%8E%B5.mp3" in header


def test_local_storage_moves_file_and_serves_it(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "files")
    src = _make_file(tmp_path)
    stored = storage.store("job1", src)
    assert stored.key == "job1/Song [abc].mp3"
    assert stored.size_bytes == 3
    assert not src.exists()
    assert storage.download_url(stored.key, "x.mp3", 60) is None
    served = storage.local_path(stored.key)
    assert served and served.read_bytes() == b"abc"
    storage.delete(stored.key)
    assert storage.local_path(stored.key) is None


def test_local_storage_refuses_path_traversal(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "files")
    (tmp_path / "secret.txt").write_text("nope")
    assert storage.local_path("../secret.txt") is None


@mock_aws
def test_r2_storage_uploads_signs_and_deletes(tmp_path: Path) -> None:
    # moto emulates S3; R2 speaks the same API, so this covers the code path.
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="dm-test")
    storage = R2Storage(
        bucket="dm-test", access_key_id="testing", secret_access_key="testing", endpoint_url=None
    )
    src = _make_file(tmp_path, "Clip [xyz].mp4")
    stored = storage.store("job9", src)
    assert stored.key == "job9/Clip [xyz].mp4"
    assert stored.size_bytes == 3
    assert not src.exists()  # local copy removed after upload

    url = storage.download_url(stored.key, "Clip [xyz].mp4", 3600)
    assert url and "job9/Clip" in url
    qs = parse_qs(urlparse(url).query)
    assert qs["response-content-disposition"][0].startswith("attachment;")
    assert qs["X-Amz-Expires"] == ["3600"]
    assert storage.local_path(stored.key) is None

    s3 = boto3.client("s3", region_name="us-east-1")
    assert s3.get_object(Bucket="dm-test", Key=stored.key)["Body"].read() == b"abc"
    storage.delete(stored.key)
    with pytest.raises(s3.exceptions.NoSuchKey):
        s3.get_object(Bucket="dm-test", Key=stored.key)
