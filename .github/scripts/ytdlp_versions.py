"""Compare the yt-dlp version pinned in backend/uv.lock against the latest on PyPI.

    python .github/scripts/ytdlp_versions.py

Prints GitHub Actions output lines:

    locked=2025.9.1
    latest=2025.9.26
    outdated=true

YouTube changes break old yt-dlp releases within weeks, and `uv sync --frozen`
means a plain rebuild does not help: the lockfile has to move first. The nightly
workflow uses this to decide whether there is anything to do.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tomllib
import urllib.request

PACKAGE = "yt-dlp"
LOCK = pathlib.Path(__file__).resolve().parents[2] / "backend" / "uv.lock"


def locked_version() -> str:
    data = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    for package in data.get("package", []):
        if package.get("name") == PACKAGE:
            return str(package["version"])
    sys.exit(f"{PACKAGE} is not in {LOCK}")


def latest_version() -> str:
    url = f"https://pypi.org/pypi/{PACKAGE}/json"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed https URL
        return str(json.load(response)["info"]["version"])


def main() -> int:
    locked = locked_version()
    latest = latest_version()
    outdated = locked != latest

    lines = [f"locked={locked}", f"latest={latest}", f"outdated={str(outdated).lower()}"]
    print("\n".join(lines))

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
