"""Locate FFmpeg. yt-dlp needs it for MP3 conversion and for merging video + audio."""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FFmpegStatus:
    available: bool
    path: str | None = None
    version: str | None = None


def find_ffmpeg(explicit: str | None = None) -> FFmpegStatus:
    candidates: list[str] = []
    if explicit:
        p = Path(explicit)
        candidates.append(str(p / "ffmpeg") if p.is_dir() else str(p))
    found = shutil.which("ffmpeg")
    if found:
        candidates.append(found)
    # winget installs Gyan.FFmpeg under the WinGet packages folder, which is only
    # on PATH for shells opened after the install. Look there too.
    local = os.environ.get("LOCALAPPDATA")
    if local:
        base = Path(local) / "Microsoft" / "WinGet" / "Packages"
        if base.exists():
            for exe in base.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"):
                candidates.append(str(exe))

    for cand in candidates:
        try:
            out = subprocess.run(
                [cand, "-version"], capture_output=True, text=True, timeout=10, check=False
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode == 0:
            first = out.stdout.splitlines()[0] if out.stdout else ""
            version = first.replace("ffmpeg version", "").strip().split(" ")[0] or None
            return FFmpegStatus(True, cand, version)
    return FFmpegStatus(False)
