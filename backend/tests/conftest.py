"""Test setup: every test run gets its own SQLite database and download folder."""

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="dm-tests-"))
os.environ["DM_DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["DM_DOWNLOAD_DIR"] = str(_tmp / "downloads")
# The shipping default: finished files are kept, so the API tests see the same
# behaviour a user gets. The tests that need an expiry set one themselves.
os.environ["DM_FILE_RETENTION_MINUTES"] = "0"
# The rate limiter counts per IP for the whole process, and every TestClient looks
# like the same caller ("testclient"), so the shipping 10/minute would fail
# whichever test happened to run eleventh. Limits are proven by their own tests.
os.environ["DM_RATE_LIMIT_JOBS"] = "10000/minute"
os.environ["DM_RATE_LIMIT_INFO"] = "10000/minute"
# Environment variables beat backend/.env, so pin everything the tests assume.
os.environ["DM_SUPABASE_URL"] = ""
os.environ["DM_SUPABASE_JWT_SECRET"] = ""
os.environ["DM_REQUIRE_AUTH"] = "false"
os.environ["DM_ENVIRONMENT"] = "development"
