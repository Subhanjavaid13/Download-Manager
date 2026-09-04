# PRD: Downloader Manager (web)

| Field | Value |
|---|---|
| Status | Draft v2 (supersedes v1, the local desktop tool) |
| Date | 2026-09-04 |
| Owner | Subhan javaid |
| Platform | Mobile-first web app (PWA), works on desktop |
| Backend | Python 3.11+ / FastAPI / yt-dlp / FFmpeg |
| Frontend | Next.js 16 / TypeScript / Tailwind 4 |
| Roadmap | [ROADMAP.md](ROADMAP.md) |

---

## 1. Summary

A hosted, mobile-first web app. A signed-in user pastes a YouTube link, picks **Audio** or **Video**, picks a quality, and gets a clean, tagged file. Audio (music as MP3 or M4A) is the primary use case. Video saves MP4 at a chosen resolution.

Users have accounts with verified email, a personal download history, and a daily quota. The operator has a dashboard showing sign ups, email authenticity, and download activity. Everything runs on free tiers at launch.

## 2. Feasibility

Yes, and every component is free at small scale.

| Need | Solution | Cost at launch |
|---|---|---|
| Fetch streams from YouTube | `yt-dlp` (actively maintained, tracks YouTube changes) | Free |
| MP3 conversion, merge video + audio, cover art | FFmpeg in the backend Docker image | Free |
| API | FastAPI (Python) | Free |
| UI | Next.js + Tailwind, installable PWA | Free |
| Accounts, email verification, database | Supabase (Postgres + Auth) | Free tier |
| File delivery | Cloudflare R2, signed links, 1-hour lifetime | Free tier, zero egress |
| Hosting | Vercel (frontend), Render (backend), later a VM for the worker | Free tiers |
| Analytics | PostHog + own `events` table, Sentry | Free tiers |

**Why not pytube / youtube-dl?** Both break often when YouTube changes its player. `yt-dlp` is the maintained fork the ecosystem relies on and supports playlists, Shorts, YouTube Music, thumbnails, metadata, and browser cookies out of the box.

**Why is FFmpeg mandatory?** YouTube serves high quality as separate video and audio streams (DASH). FFmpeg merges them, and it is the only way to produce MP3.

**What is different about hosting it?** The backend downloads from YouTube and then the user downloads from you, so bandwidth is the real cost, and YouTube sometimes blocks datacenter IPs. Both are handled in the roadmap: R2 for delivery, and a worker that can move to a VM with a clean IP.

## 3. Goals

1. Paste any YouTube URL (watch, youtu.be, Shorts, music.youtube.com) and download it in two taps on a phone.
2. Audio: MP3 (compatible everywhere) or M4A / Opus (no re-encode, best fidelity), with title, artist, and square cover art embedded.
3. Video: MP4 at 360p to 2160p or best available, only offering resolutions the video actually has.
4. Live progress (stage, percent, speed, ETA) and plain-English errors.
5. Sign up and sign in with email + password or Google, with email verification before downloading.
6. Personal download history that follows the user across devices.
7. Operator dashboard: sign ups (verified / unverified / disposable), active users, downloads, failure rates.
8. Run on free tiers, with a known paid step when it outgrows them.

## 4. Non-goals (v2)

- Sites other than YouTube. yt-dlp supports over a thousand; we do not test or expose them yet.
- DRM'd or paid content (YouTube Premium, Movies). Not possible and not attempted.
- Editing or trimming media.
- Bypassing age or region restrictions beyond what yt-dlp does normally.
- Public, marketed "download any song" service. This is a personal-use tool for a small group.
- Native app store apps (optional Phase 7).

## 5. Target users

- **Primary:** the owner and a small circle of people, mostly on Android and iPhone, who want a music file from a link with no ads and no sketchy sites.
- **Operator:** the owner, who wants to see who signed up, whether their email is real, and what they download.

## 6. User stories

| ID | Story | Priority |
|---|---|---|
| US1 | I paste a link on my phone, tap Audio, tap Download, and save an MP3 with cover art. | Must |
| US2 | I choose Video and 1080p and get an MP4 that plays on my phone and in VLC. | Must |
| US3 | I see a progress bar with speed and ETA while it downloads, and I can cancel. | Must |
| US4 | I share a video from the YouTube app straight into Downloader Manager. | Should |
| US5 | I sign up with my email, get a verification mail, and can download only after confirming. | Must |
| US6 | I sign in with Google instead of a password. | Should |
| US7 | I see my past downloads and can re-save a file while it still exists. | Should |
| US8 | I get a plain-English error if the video is private, removed, or YouTube is blocking. | Must |
| US9 | I install it to my home screen and it opens like an app, in dark mode if my phone is dark. | Should |
| US10 | As the operator, I see how many real (verified, non-disposable) users signed up this week and what they downloaded. | Must |
| US11 | As the operator, a broken yt-dlp shows up as a failure spike and an alert, not as silent user complaints. | Should |
| US12 | I paste a playlist and download every item. | Could (Phase 6) |

## 7. Functional requirements

### 7.1 Input
- **FR1.1** Accept a URL pasted or typed, or received from the Android share sheet (`?url=` / `?text=`).
- **FR1.2** Recognise `youtube.com/watch?v=`, `youtu.be/`, `youtube.com/shorts/`, `music.youtube.com/`, `m.youtube.com/`, `/embed/`, `/live/`. Reject everything else before yt-dlp runs.
- **FR1.3** Show title, channel, duration, thumbnail, and available resolutions before download.
- **FR1.4** A watch URL that also carries `list=` downloads that single video; whole-playlist support arrives in Phase 6.

### 7.2 Audio
- **FR2.1** Formats: MP3 (default), M4A, Opus.
- **FR2.2** MP3 bitrate: 128 / 192 (default) / 320 kbps. Show a note on 320 that the source is ~128 to 160 kbps.
- **FR2.3** M4A and Opus are passthrough when the source matches (highest fidelity).
- **FR2.4** Embed title, artist (uploader), and cover art. Crop the 16:9 thumbnail to a square first.

### 7.3 Video
- **FR3.1** MP4 (H.264 + AAC) container. Merge streams with FFmpeg.
- **FR3.2** Presets 360p to 2160p plus Best. Only show presets at or below the video's maximum.

### 7.4 Jobs and delivery
- **FR4.1** A download is a job: queued, fetching, downloading, processing, done, error, cancelled.
- **FR4.2** Progress: percent, bytes, speed, ETA, current post-processing step.
- **FR4.3** Cancel stops the job and deletes partial files.
- **FR4.4** Finished files are uploaded to R2 and served by a signed link valid for 1 hour, then deleted (Phase 1). Until then, the API streams the file directly.
- **FR4.5** Filenames are `Title [id].ext` with characters Windows forbids removed.
- **FR4.6** Refuse live streams, premieres, and videos longer than 3 hours.

### 7.5 Accounts (Phase 2)
- **FR5.1** Sign up and sign in with email + password, and with Google.
- **FR5.2** Verification email on sign up; downloads are blocked until `email_confirmed_at` is set.
- **FR5.3** Password reset by email.
- **FR5.4** Disposable email domains are refused at sign up. Domains without MX records are refused.
- **FR5.5** CAPTCHA (Cloudflare Turnstile) on sign up.
- **FR5.6** Per-user daily quota, default 20 downloads. Small anonymous allowance (3 per day per IP) so people can try it.
- **FR5.7** Users can delete their account; their history and files are removed.

### 7.6 History (Phase 2)
- **FR6.1** Every job is stored in `downloads` with user id, video id, title, mode, format, quality, status, size, duration, error code, timestamps.
- **FR6.2** History screen lists a user's own downloads, newest first, with re-download while the file exists.

### 7.7 Activity analytics (Phase 5)
- **FR7.1** The API records events: signup, email_verified, signin, info_requested, download_started, download_completed, download_failed (error code), quota_hit. IP is stored as a salted hash.
- **FR7.2** Admin dashboard (role = admin): sign ups by day split verified / unverified / disposable; DAU and WAU; downloads by mode and format; success rate; top error codes; top email domains.
- **FR7.3** PostHog for funnels and session replay, keyed by user id, with consent where required.

### 7.8 Errors
- **FR8.1** Map yt-dlp errors to friendly messages: private, unavailable, age-restricted, geo-blocked, bot check, live, network, FFmpeg missing.
- **FR8.2** Full technical errors go to logs and Sentry, never to the UI.

### 7.9 Operations
- **FR9.1** `/health` reports FFmpeg and yt-dlp versions and whether auth is enabled.
- **FR9.2** Nightly image rebuild keeps yt-dlp current.
- **FR9.3** Uptime monitor pings `/health` every 5 minutes.

## 8. Non-functional requirements

| Area | Requirement |
|---|---|
| Mobile-first | Designed at 360 px wide first. Sticky action bar, thumb-reachable controls, works as an installed PWA. |
| Performance | Lighthouse mobile 90+ (Performance, Accessibility). Preview appears within 2 s of paste on a normal connection. |
| Responsiveness | The API never blocks: downloads run on worker threads, the UI polls or streams progress. |
| Reliability | Retry transient network errors 3 times. Jobs persist across restarts (Phase 1). Files expire after 1 hour. |
| Security | No shell execution with user input. JWT verified per request. Row Level Security in Postgres. Rate limits. CORS locked to the app origin. Secrets only in env vars. |
| Privacy | Hash IPs. Store video ids, not full URLs. 90-day retention on raw events. Delete on account deletion. |
| Cost | $0/month at launch. Known steps: Render Starter $7, Supabase Pro $25, Hetzner VPS ~€4. |
| Portability | Backend is one Docker image that runs on Render, Fly, Railway, Oracle, or any VPS. |

## 9. Tech stack

| Layer | Choice | Reason |
|---|---|---|
| Backend runtime | Python 3.11+ (3.14 locally), FastAPI, uvicorn | Async API, automatic docs, pairs naturally with yt-dlp. |
| Download engine | `yt-dlp` via its Python API | Maintained, progress hooks, no shell. |
| Media | FFmpeg (apt in Docker; winget locally) | Required for MP3 and merging. |
| Package manager | `uv` | Fast, lockfile, same in Docker and CI. |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind 4 | Mobile-first PWA, free on Vercel, share target support. |
| Auth + DB | Supabase (Postgres, Auth, RLS) | Sign up, verification, reset, Google login without writing any of it. |
| DB access | SQLAlchemy 2 | SQLite locally, Postgres in production, same code. |
| File delivery | Cloudflare R2 | Zero egress fees. |
| Analytics | PostHog, own `events` table, Sentry | Funnels and replay; source of truth; errors. |
| CI | GitHub Actions | Lint, tests, build on every PR. |
| Deploy | Vercel + Render (Docker), later a VM for the worker | Free, automatic from `main`. |

Alternatives considered: **Neon** (Postgres only, no auth), **Firebase** (NoSQL, admin-only Python SDK), **MongoDB Atlas** (no auth, NoSQL), **HTMX + Jinja** instead of Next.js (one language, but weaker mobile app feel and no share target ergonomics), **Fly.io / Railway** (no longer free for new accounts).

## 10. Architecture

```
downloader-manager/
├── docs/                      PRD.md, ROADMAP.md
├── supabase/migrations/       0001_init.sql  (profiles, downloads, events, RLS)
├── backend/                   FastAPI + yt-dlp + FFmpeg  (Docker on Render / VM)
│   ├── app/
│   │   ├── core/              url.py, formats.py, downloader.py, errors.py, ffmpeg.py
│   │   ├── api/               info.py, jobs.py
│   │   ├── jobs/store.py      job queue (in-memory now, Postgres in Phase 1)
│   │   ├── auth.py            Supabase JWT verification (JWKS or HS256)
│   │   ├── config.py          settings from DM_* env vars
│   │   ├── deps.py            rate limiter, DI
│   │   ├── schemas.py         request/response models
│   │   └── main.py            app factory, /health
│   ├── tests/                 url, formats, api
│   ├── Dockerfile             python:3.12-slim + ffmpeg + uv
│   └── .env.example
├── frontend/                  Next.js 16  (Vercel)
│   ├── src/app/               layout.tsx, page.tsx, manifest.ts (share_target), globals.css
│   ├── src/components/        downloader.tsx (paste, preview, mode, quality, progress)
│   └── src/lib/               api.ts (typed client, token provider), format.ts
└── .github/workflows/ci.yml   backend tests + frontend build
```

Request flow: phone → Vercel (Next.js) → `api.` (FastAPI) → worker thread runs yt-dlp + FFmpeg → file to R2 → signed link back to the phone → R2 serves the bytes → lifecycle deletes after 1 hour. Auth: the browser talks to Supabase for sign up / sign in and sends the access token to the API, which verifies it against Supabase's public keys.

Rule: **`core/` has no HTTP or UI code.** The API, a future CLI, and tests all call the same `Downloader` class.

### Key yt-dlp settings (the heart of the product)

| Goal | Format selector | Post-processor |
|---|---|---|
| MP3 192 kbps | `bestaudio/best` | `FFmpegExtractAudio` codec=mp3, quality=192 |
| M4A passthrough | `bestaudio[ext=m4a]/bestaudio/best` | `FFmpegExtractAudio` codec=m4a, quality=0 (copies if already AAC) |
| Opus passthrough | `bestaudio[acodec=opus]/bestaudio/best` | `FFmpegExtractAudio` codec=opus, quality=0 |
| MP4 1080p | `bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best` | `merge_output_format="mp4"` |
| MP4 best | `bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best` | `merge_output_format="mp4"` |
| Cover art + tags | any audio | `FFmpegMetadata`, `FFmpegThumbnailsConvertor` (jpg, square crop), `EmbedThumbnail` |

Note on audio quality: YouTube's source audio is roughly 128 kbps AAC or 130 to 160 kbps Opus. A 320 kbps MP3 does **not** sound better than the source; it only makes a bigger file. Default to 192 kbps MP3 and recommend M4A or Opus for best fidelity.

## 11. Milestones

See [ROADMAP.md](ROADMAP.md) for the full phase plan. Summary:

| Phase | Outcome | Duration |
|---|---|---|
| 0 | Foundations: engine, API, mobile UI, Docker, CI, migration. Verified end to end. | done |
| 1 | Solid single-user product: R2 delivery, persistent jobs, cancel, UX states. | 1 week |
| 2 | Accounts: Supabase Auth, verification, disposable-email checks, history, quotas. | 1 week |
| 3 | Mobile-first UI/UX pass: navigation, install prompt, accessibility, Lighthouse 90+. | 1 week |
| 4 | Deployment and operations: Vercel, Render, R2, DNS, CI/CD, uptime, backups, nightly rebuild. | 3 to 4 days |
| 5 | Analytics: events, PostHog, admin dashboard, email authenticity reporting. | 4 to 5 days |
| 6 | Hardening and growth: quotas, bot-check strategy, playlists, legal pages. | ongoing |
| 7 | Optional native mobile wrapper. | later |

## 12. Risks and legal

| Risk | Impact | Mitigation |
|---|---|---|
| YouTube blocks datacenter IPs | Downloads fail with a bot-check error | Friendly error now; worker on a clean-IP VM, throwaway-account cookies, or residential proxy later. |
| YouTube changes break `yt-dlp` | Downloads fail until updated | Nightly rebuild; `/health` shows the version; Sentry alert on failure spikes. |
| Bandwidth cost | Free tiers exhausted | R2 for delivery (no egress fees), size caps, 1-hour TTL, per-user quotas. |
| Hosting provider objects | Service taken down | Personal use, quotas, no marketing; Docker image moves to a VPS in an hour. |
| Terms of Service and copyright | YouTube's ToS forbids downloading without permission except via YouTube's own features. Copyrighted music you do not own may infringe in your jurisdiction. As the **operator** of a hosted service, this exposure is now yours, not only the end user's. | Personal use with content you have rights to. Disclaimer at sign up. No monetisation. DMCA contact page. Small, private user base. |
| Supabase free project pauses after 7 idle days | Sign in fails | Uptime ping every 5 minutes. |
| Fake or throwaway sign ups | Polluted analytics, quota abuse | Verification required, disposable-domain and MX checks, Turnstile, per-user quotas. |

## 13. Success criteria

- On a phone, paste to saved MP3 with cover art in under 30 seconds for a typical song.
- A 1080p MP4 downloads and plays on the phone and in VLC with no manual steps.
- Every one of the top error cases (bad link, private, removed, bot check, network, FFmpeg) shows a friendly message; zero unhandled exceptions in Sentry for those.
- A new user can sign up, verify, download, and see history on a second device.
- A disposable or MX-less email is refused with a clear message.
- The admin dashboard answers "how many real users this week and what did they download" on one page.
- Monthly cost at launch: $0 plus the domain.

## 14. Open questions (defaults chosen)

1. Require sign in for every download, or allow a small anonymous allowance? Default: 3 per day per IP anonymous, then sign in.
2. Google login in Phase 2 or later? Default: Phase 2, it is one toggle in Supabase.
3. Deliver files through the API or through R2? Default: R2 from Phase 1.
4. Whole-playlist downloads: Phase 6 or earlier? Default: Phase 6, after quotas exist.
5. Where does the worker live long term? Default: Oracle Always Free ARM VM; Hetzner if Oracle sign-up fails.

## 15. Local setup

```powershell
# Backend (FFmpeg is already installed via winget on this machine)
cd backend
uv sync
uv run pytest -q
uv run uvicorn app.main:app --reload        # http://localhost:8000/docs

# Frontend (in a second terminal)
cd frontend
npm install
npm run dev                                 # http://localhost:3000
```

`backend/.env.example` and `frontend/.env.local.example` list every setting. Nothing is required for local development.
