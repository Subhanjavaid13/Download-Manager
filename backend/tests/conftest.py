"""Test setup: every test run gets its own SQLite database and download folder."""

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="dm-tests-"))
os.environ["DM_DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["DM_DOWNLOAD_DIR"] = str(_tmp / "downloads")
os.environ["DM_STORAGE"] = "local"
os.environ["DM_JOB_TTL_MINUTES"] = "60"
# Environment variables beat backend/.env, so pin everything the tests assume.
os.environ["DM_SUPABASE_URL"] = ""
os.environ["DM_SUPABASE_JWT_SECRET"] = ""
os.environ["DM_REQUIRE_AUTH"] = "false"
os.environ["DM_ENVIRONMENT"] = "development"
