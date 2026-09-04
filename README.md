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
uv run pytest -q                 # 73 tests
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

## Accounts

Auth is Supabase. Sign in, password reset, and sessions happen in the browser with the Supabase client; sign-up goes through the API so email checks run server-side. To turn it on:

1. Put the project URL and anon key in `frontend/.env.local` (`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`) and in `backend/.env` (`DM_SUPABASE_URL`, `DM_SUPABASE_ANON_KEY`).
2. In the Supabase dashboard set the Site URL and add `/auth/callback` and `/auth/reset` to the redirect allow-list.
3. Restart. Guests keep `DM_ANON_DAILY_LIMIT` downloads a day; verified users get 20. Set `DM_REQUIRE_AUTH=true` to require sign-in for everything.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/auth/config` | Is auth on, is sign-up on, guest allowance |
| POST | `/api/v1/auth/signup` | Checks the email (syntax, disposable, MX, CAPTCHA) then creates the Supabase user |
| GET | `/api/v1/auth/me` | Profile, quota, downloads today, verified flag |
| POST | `/api/v1/auth/claim` | Attach this browser's guest downloads to the signed-in account |
| DELETE | `/api/v1/auth/me` | Delete account, history, and files |

## Database

SQLite is used automatically in development. To use Supabase Postgres, put the pooler URL in `backend/.env` and apply the schema once:

```powershell
cd backend
uv run python scripts/migrate.py --dry-run   # validates the SQL inside a transaction, then rolls back
uv run python scripts/migrate.py             # applies pending files from supabase/migrations
uv run python scripts/migrate.py --status    # what is applied
```

The API refuses to start against a Postgres database that has no schema, so you cannot end up with tables that miss Row Level Security.

## Deploy

See [docs/ROADMAP.md](docs/ROADMAP.md), Phase 4. Short version: Vercel for `frontend/`, Render for `backend/Dockerfile`, Supabase for auth and data, Cloudflare R2 for file delivery. All free tiers.

## Legal

For personal use with content you have the right to download. YouTube's Terms of Service restrict downloading; do not run this as a public service or monetise it. See the Risks section of the PRD.
