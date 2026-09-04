"""Test setup: every test run gets its own SQLite database and download folder."""

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="dm-tests-"))
os.environ["DM_DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["DM_DOWNLOAD_DIR"] = str(_tmp / "downloads")
os.environ["DM_STORAGE"] = "local"
os.environ["DM_JOB_TTL_MINUTES"] = "60"
os.environ.pop("DM_SUPABASE_URL", None)
os.environ.pop("DM_SUPABASE_JWT_SECRET", None)
