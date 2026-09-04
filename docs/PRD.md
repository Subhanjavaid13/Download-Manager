# PRD: YouTube Audio/Video Downloader ("downloader-manager")

| Field | Value |
|---|---|
| Status | Draft v1 |
| Date | 2026-09-04 |
| Owner | Subhan javaid |
| Platform | Windows 11 first, cross-platform by design |
| Language | Python 3.11+ (3.14 installed locally) |

---

## 1. Summary

A free, local desktop tool where the user pastes a YouTube link, picks **Audio** or **Video**, picks a quality, and gets a clean file on disk. Audio mode is the primary use case (saving music as MP3/M4A). Video mode saves MP4 at a chosen resolution.

Everything runs on the user's machine. No accounts, no server, no cost.

## 2. Feasibility (short answer: yes)

| Need | Solution | Cost |
|---|---|---|
| Fetch streams from YouTube | `yt-dlp` (open-source, actively maintained, handles YouTube's frequent changes) | Free |
| Convert to MP3, merge video+audio, embed cover art | FFmpeg (open-source) | Free |
| CLI | `typer` + `rich` | Free |
| Desktop GUI | `customtkinter` (pure Python, modern look) | Free |
| Single .exe for Windows | PyInstaller | Free |

**Why not pytube / youtube-dl?** Both break often when YouTube changes its player. `yt-dlp` is the maintained fork that the whole ecosystem relies on; it also supports playlists, Shorts, YouTube Music, thumbnails, metadata, and browser cookies out of the box.

**Why is FFmpeg mandatory?** YouTube serves high quality as *separate* video and audio streams (DASH). FFmpeg merges them, and it is the only way to produce MP3 (YouTube never serves MP3 directly).

## 3. Goals

1. Paste any YouTube URL (watch, youtu.be, Shorts, playlist, music.youtube.com) and download it in one click.
2. Audio mode: MP3 (compatible everywhere) or M4A/Opus (no re-encode, best fidelity).
3. Video mode: MP4 at 360p / 480p / 720p / 1080p / best available.
4. Show live progress (percent, speed, ETA) and clear error messages.
5. Embed title, artist, album, and cover art into audio files so music players show them correctly.
6. Work fully offline apart from the download itself; no login required by default.

## 4. Non-goals (v1)

- Downloading from sites other than YouTube (yt-dlp supports 1000+ sites; we may expose this later but will not test it).
- DRM'd or paid content (YouTube Premium, Movies). Not possible and not attempted.
- Cloud sync, accounts, or a hosted web service.
- Editing or trimming media.
- Bypassing YouTube age or region restrictions beyond what yt-dlp does normally.

## 5. Target user

A single person on Windows who wants a simple "paste link, get file" tool for personal use. Comfortable installing Python once. Not a power user of the command line.

## 6. User stories

| ID | Story | Priority |
|---|---|---|
| US1 | As a user I paste a video link, choose Audio > MP3, and get `Artist - Title.mp3` in my Music folder. | Must |
| US2 | As a user I choose Video > 1080p and get an MP4 that plays in Windows Media Player and VLC. | Must |
| US3 | As a user I see a progress bar with speed and ETA while it downloads. | Must |
| US4 | As a user I paste a playlist link and every item downloads with the same settings. | Should |
| US5 | As a user I pick the output folder once and the app remembers it. | Should |
| US6 | As a user my MP3s show the cover art and artist in my music player. | Should |
| US7 | As a user I get a plain-English error if the video is private, removed, or my internet is down. | Must |
| US8 | As a user I can queue several links and they download one after another. | Could |
| US9 | As a user I can update the downloader engine from inside the app when YouTube changes. | Should |

## 7. Functional requirements

### 7.1 Input
- **FR1.1** Accept a single URL pasted into a text field or passed on the command line.
- **FR1.2** Recognise: `youtube.com/watch?v=`, `youtu.be/`, `youtube.com/shorts/`, `youtube.com/playlist?list=`, `music.youtube.com/`.
- **FR1.3** Validate the URL before starting; reject non-YouTube links with a clear message.
- **FR1.4** Fetch and display title, channel, duration, and thumbnail before download (metadata preview).

### 7.2 Mode: Audio
- **FR2.1** Formats: `MP3` (default), `M4A`, `Opus`.
- **FR2.2** MP3 bitrate options: 128 / 192 (default) / 320 kbps.
- **FR2.3** M4A and Opus are passthrough (no re-encode) when the source stream matches, which is the highest fidelity option.
- **FR2.4** Embed metadata (title, artist/uploader, album/playlist, year) and the video thumbnail as cover art.
- **FR2.5** Crop the 16:9 thumbnail to a square before embedding (so it looks right in music players).

### 7.3 Mode: Video
- **FR3.1** Container: MP4 (H.264 + AAC) by default for maximum compatibility.
- **FR3.2** Resolution options: 360p, 480p, 720p, 1080p, 1440p, 2160p, Best. Only show resolutions the video actually has.
- **FR3.3** Merge video and audio streams automatically via FFmpeg.
- **FR3.4** Optional: embed subtitles if available (Could).

### 7.4 Output
- **FR4.1** Default folders: `~/Music/YouTube` for audio, `~/Videos/YouTube` for video. User can change and the choice persists.
- **FR4.2** Filename template default: `%(title)s [%(id)s].%(ext)s`. Sanitize characters that Windows forbids in filenames (backslash, slash, colon, asterisk, question mark, quotes, angle brackets, pipe).
- **FR4.3** Never overwrite silently: skip if the file already exists, or add a numeric suffix.
- **FR4.4** Open the output folder from the UI after completion.

### 7.5 Progress and feedback
- **FR5.1** Live progress: percent, downloaded/total size, speed, ETA.
- **FR5.2** Post-processing stage shown separately ("Converting to MP3...").
- **FR5.3** Cancel button that stops the download and deletes partial files.

### 7.6 Playlists
- **FR6.1** Detect playlist URLs and ask: "Download whole playlist (N items) or only this video?"
- **FR6.2** Sequential download with per-item and overall progress.
- **FR6.3** Continue past failed items and report them at the end.

### 7.7 Error handling
- **FR7.1** Map common yt-dlp errors to friendly messages: private video, removed video, age-restricted, geo-blocked, network failure, FFmpeg missing.
- **FR7.2** Log full technical errors to `~/.downloader-manager/app.log` for debugging.
- **FR7.3** If YouTube demands sign-in ("confirm you're not a bot"), offer the option to use cookies from the user's browser (`cookiesfrombrowser`).

### 7.8 Maintenance
- **FR8.1** "Update engine" action runs `pip install -U yt-dlp` (or replaces the bundled binary) because YouTube changes break old versions within weeks.
- **FR8.2** On startup, detect FFmpeg. If missing, show install instructions (`winget install Gyan.FFmpeg`) or offer to download a static build.

## 8. Non-functional requirements

| Area | Requirement |
|---|---|
| Performance | Download speed limited only by network; UI stays responsive (downloads run in a worker thread). |
| Reliability | Retry transient network errors up to 3 times. Resume partial downloads. |
| Portability | Runs on Windows 11 first; no Windows-only APIs so macOS/Linux work too. |
| Privacy | No telemetry. No data leaves the machine except requests to YouTube. |
| Footprint | Installed size under 150 MB including FFmpeg. |
| Configuration | Settings stored in `~/.downloader-manager/config.json`. |

## 9. Tech stack

| Layer | Choice | Reason |
|---|---|---|
| Runtime | Python 3.11+ | Requested; best library support for this problem. |
| Download engine | `yt-dlp` | De facto standard, actively maintained, Python API with progress hooks. |
| Media processing | FFmpeg (static build) | Required for MP3 conversion and stream merging. |
| CLI | `typer` + `rich` | Type-safe commands, beautiful progress bars for free. |
| GUI | `customtkinter` | Modern look, pure Python, small, no Qt licensing questions. |
| Config | `pydantic-settings` or plain `json` | Simple typed settings file. |
| Packaging | PyInstaller (`--onefile`) | Single .exe, no Python install required for end users. |
| Tests | `pytest` | Unit tests for URL parsing, format selection, filename sanitizing. |

Alternatives considered: **PySide6/Qt** (heavier, more polished; use if the GUI grows), **Flet** (Flutter UI, modern but bigger binary), **local web UI with FastAPI** (good for cross-platform, but a browser tab feels less like a tool).

## 10. Architecture

```
downloader-manager/
├── docs/PRD.md
├── pyproject.toml
├── src/downloader_manager/
│   ├── __init__.py
│   ├── core/
│   │   ├── url.py          # parse/validate YouTube URLs, detect playlist vs video
│   │   ├── formats.py      # build yt-dlp format selectors + postprocessors
│   │   ├── downloader.py   # thin wrapper around yt_dlp.YoutubeDL, progress hooks, cancel
│   │   ├── ffmpeg.py       # locate/verify FFmpeg, install guidance
│   │   └── errors.py       # map yt-dlp exceptions to user-facing messages
│   ├── config.py           # load/save settings (output dirs, defaults)
│   ├── cli.py              # typer app: `ytdm audio <url>`, `ytdm video <url> --res 1080`
│   └── gui/
│       ├── app.py          # customtkinter main window
│       └── widgets.py      # URL entry, mode toggle, quality dropdown, progress bar
└── tests/
    ├── test_url.py
    ├── test_formats.py
    └── test_filenames.py
```

Rule: **`core/` has no UI code.** Both the CLI and the GUI call the same `Downloader` class, so behaviour is identical and testable.

### Key yt-dlp settings (the heart of the product)

| Goal | Format selector | Post-processor |
|---|---|---|
| MP3 192 kbps | `bestaudio/best` | `FFmpegExtractAudio` codec=mp3, quality=192 |
| M4A passthrough | `bestaudio[ext=m4a]/bestaudio` | `FFmpegExtractAudio` codec=m4a (copies if already AAC) |
| Opus passthrough | `bestaudio[acodec=opus]/bestaudio` | none |
| MP4 1080p | `bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]` | `merge_output_format="mp4"` |
| MP4 best | `bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best` | `merge_output_format="mp4"` |
| Cover art + tags | any audio | `EmbedThumbnail` + `FFmpegMetadata`, with `writethumbnail=True` |

Note on audio quality: YouTube's source audio is roughly 128 kbps AAC or 130-160 kbps Opus. A 320 kbps MP3 does **not** sound better than the source; it just makes a bigger file. Default to 192 kbps MP3, and recommend M4A/Opus to users who want the best fidelity.

## 11. Milestones

| # | Milestone | Deliverable | Effort |
|---|---|---|---|
| M0 | Environment | `pip install yt-dlp typer rich customtkinter`, install FFmpeg, verify one manual download. | 1 hour |
| M1 | Core + CLI (MVP) | `ytdm audio <url>` and `ytdm video <url> --res 1080` work with progress bar, metadata, cover art. Tests for URL and format logic. | 1-2 days |
| M2 | GUI | CustomTkinter window: paste box, Audio/Video toggle, quality dropdown, folder picker, progress bar, cancel. | 2-3 days |
| M3 | Playlists + queue | Playlist detection and prompt, sequential queue, per-item status. | 1-2 days |
| M4 | Polish + packaging | Friendly errors, FFmpeg detection, "update engine" button, PyInstaller .exe. | 1-2 days |

Ship M1 first. It is useful on its own and proves the whole pipeline.

## 12. Risks and legal

| Risk | Impact | Mitigation |
|---|---|---|
| YouTube changes break `yt-dlp` | Downloads fail until updated | "Update engine" button; pin nothing, always allow upgrade. |
| YouTube bot-check / sign-in wall | Downloads fail on some networks | Support `cookiesfrombrowser`; document it. |
| FFmpeg not installed | MP3 and high-res video impossible | Detect at startup; give one-line install command; optionally bundle a static build. |
| Terms of Service | YouTube's ToS forbids downloading content without permission except via YouTube's own download features. Downloading copyrighted music you do not own may also infringe copyright in your jurisdiction. | Tool is for personal use with content you have rights to (your own uploads, Creative Commons, public domain, or where the owner permits). Show a one-time disclaimer. Do not distribute the app commercially. |
| FFmpeg licensing when bundling | GPL/LGPL obligations | Bundle an LGPL build and include its license text, or have the user install it. |

Building and using this tool for yourself is the same thing thousands of yt-dlp users do daily. The legal exposure comes from what you download and whether you redistribute it, not from writing the software.

## 13. Success criteria

- A pasted music video becomes a tagged MP3 with cover art in under 30 seconds on a normal connection.
- A 1080p video downloads and plays in VLC and Windows Media Player with no manual steps.
- Zero crashes on the top 5 error cases (bad URL, private, removed, offline, no FFmpeg): each shows a friendly message.
- The GUI never freezes during a download.

## 14. Open questions

1. GUI now, or CLI only until it proves useful? (Recommendation: CLI first, GUI in week 2.)
2. Bundle FFmpeg inside the .exe (bigger download, zero setup) or ask the user to install it (smaller, one extra step)?
3. Default audio format: MP3 for compatibility, or M4A for fidelity?
4. Should the queue persist across restarts?

## 15. Setup commands (M0)

```powershell
# in d:\workspace\projects\downloader-manager
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install yt-dlp typer rich customtkinter pytest
winget install Gyan.FFmpeg      # then reopen the terminal so ffmpeg is on PATH

# smoke test: best audio as MP3 with cover art
yt-dlp -x --audio-format mp3 --audio-quality 192K --embed-thumbnail --embed-metadata "<youtube url>"
```
