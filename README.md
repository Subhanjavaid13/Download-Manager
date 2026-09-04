# Downloader Manager

Paste a YouTube link, choose **Audio** or **Video**, choose a quality, save the file. A mobile-first web app with a Python backend.

| Part | Stack | Where it runs |
|---|---|---|
| `backend/` | FastAPI, yt-dlp, FFmpeg, uv | Docker on Render (free), later a VM |
| `frontend/` | Next.js 16, TypeScript, Tailwind 4, PWA | Vercel (free) |
| `supabase/` | Postgres schema, Auth, Row Level Security | Supabase (free) |
| `docs/` | [PRD](docs/PRD.md), [Roadmap](docs/ROADMAP.md) | |

## Run it locally

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 20+, FFmpeg (`winget install Gyan.FFmpeg` on Windows).

```powershell
# Terminal 1: API on http://localhost:8000  (docs at /docs)
cd backend
uv sync
uv run uvicorn app.main:app --reload

# Terminal 2: UI on http://localhost:3000
cd frontend
npm install
npm run dev
```

Nothing else is required. Auth and the database are off until you fill in `backend/.env` (copy from `.env.example`).

## Check it works

```powershell
cd backend
uv run pytest -q                 # 48 tests
curl http://localhost:8000/health
```

`health` reports whether FFmpeg was found and which yt-dlp version is loaded.

## API (v1)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | FFmpeg, yt-dlp version, auth on/off, storage and database in use |
| GET | `/api/v1/info?url=` | Title, channel, duration, thumbnail, available resolutions |
| POST | `/api/v1/jobs` | Start a download `{url, mode, audio_format, audio_bitrate, video_height}` |
| GET | `/api/v1/jobs` | This browser's or user's recent downloads |
| GET | `/api/v1/jobs/{id}` | Progress, status, and whether the file is still available |
| GET | `/api/v1/jobs/{id}/file` | The file (streamed locally, or a redirect to a signed R2 link) |
| DELETE | `/api/v1/jobs/{id}` | Cancel |

Send `X-Client-Id: <8-64 url-safe chars>` on every call so anonymous history works; the frontend does this automatically. Signed-in users send `Authorization: Bearer <supabase token>` instead (Phase 2).

Files are deleted one hour after a job finishes. The history row stays.

## Configuration

All backend settings are `DM_*` environment variables, documented in [backend/.env.example](backend/.env.example). Two matter most: `DM_DATABASE_URL` (SQLite by default, a Supabase Postgres URI in production) and `DM_STORAGE` (`local` by default, `r2` for Cloudflare R2 in production). The frontend needs only `NEXT_PUBLIC_API_URL` (see [frontend/.env.local.example](frontend/.env.local.example)).

## Deploy

See [docs/ROADMAP.md](docs/ROADMAP.md), Phase 4. Short version: Vercel for `frontend/`, Render for `backend/Dockerfile`, Supabase for auth and data, Cloudflare R2 for file delivery. All free tiers.

## Legal

For personal use with content you have the right to download. YouTube's Terms of Service restrict downloading; do not run this as a public service or monetise it. See the Risks section of the PRD.
