# Roadmap: Downloader Manager (web)

| Field | Value |
|---|---|
| Status | v1 |
| Date | 2026-09-04 |
| Owner | Subhan javaid |
| Companion doc | [PRD.md](PRD.md) |

## What changed

The first PRD described a local desktop tool. The product is now a **hosted, mobile-first web app** with user accounts, a database, deployment, and activity analytics. This roadmap covers the whole path in six phases plus an optional seventh. Phase 0 is already done in this repo.

---

## 1. Stack decisions

Every choice below is free at the scale of a personal project or a small group of users, and each has a clear paid step when it outgrows the free tier.

### Database and auth: Supabase

**Recommendation: Supabase** (hosted Postgres + built-in Auth + Storage), free tier.

| Why | Detail |
|---|---|
| One service does three jobs | Postgres for data, Auth for sign up / sign in / email verification / password reset / Google login, Storage if needed. Nothing to build yourself. |
| Email verification is built in | Supabase sends the confirmation mail and records `email_confirmed_at`. That is the "authentic email or not" signal you asked for. |
| Row Level Security | Users can only read their own download history, enforced in the database, not just in app code. |
| Free tier is enough to launch | 500 MB database, 50,000 monthly active users, 1 GB file storage, unlimited API requests. |
| Python-friendly | It is plain Postgres. SQLAlchemy connects with a normal connection string. |
| Easy setup | Create a project in the dashboard, copy two keys, run one SQL migration. Under 15 minutes. |

Known limit: free projects **pause after 7 days without activity**. Mitigation: the uptime monitor in Phase 4 pings the API every 5 minutes, and the API touches the database on health checks. Pro is $25/month if you ever need no pausing and daily backups.

Alternatives considered:

| Option | Verdict |
|---|---|
| Neon (serverless Postgres) | Excellent database, but no auth. You would write sign up, verification emails, and password reset yourself. Good second choice if you only want a DB. |
| Firebase (Firestore + Auth) | Great auth, but NoSQL makes "which users did what" queries awkward, and the Python SDK is admin-only. |
| MongoDB Atlas M0 | Free 512 MB, but no auth and NoSQL. Not a fit for relational activity data. |
| PlanetScale | No longer has a free tier. |
| SQLite on the server | Fine for local dev (that is the default in `backend/.env.example`), but a hosted container's disk is wiped on every deploy. |

### Hosting

| Layer | Service | Free tier | Why |
|---|---|---|---|
| Frontend (Next.js) | **Vercel Hobby** | 100 GB bandwidth/month, preview deploys per branch, custom domain, HTTPS | Made by the Next.js team. Zero configuration. |
| Backend (FastAPI + FFmpeg, Docker) | **Render** free web service | 750 hours/month, 512 MB RAM, 100 GB egress | Runs a Dockerfile as-is, so FFmpeg is included. Spins down after 15 minutes idle (first request takes ~40 s). Starter plan is $7/month with no spin-down. |
| Backend, step two | **Oracle Cloud Always Free** ARM VM (4 cores, 24 GB RAM, 10 TB egress/month) or a Hetzner VPS (~€4/month) | Free / ~€4 | A downloader is bandwidth-heavy. When Render's 100 GB egress runs out or YouTube starts blocking Render's IP range, move the worker to a VM you control. Same Docker image. |
| File delivery | **Cloudflare R2** | 10 GB storage, **zero egress fees** | The worker uploads the finished file to R2 and hands the user a short-lived signed link. Users download from Cloudflare, not from your small backend, and a lifecycle rule deletes files after 1 hour. This is the single biggest cost saver. |
| Domain | GoDaddy (already in use) | ~$10/year | Point `app.` at Vercel and `api.` at Render with two CNAME records. |

### Analytics and user activity

| Need | Tool | Free tier |
|---|---|---|
| Product analytics, funnels, session replay | **PostHog Cloud** | 1 M events/month, 5 k session recordings |
| Your own source of truth for the admin dashboard | **`events` table in Supabase** (written by the API) | Included |
| Error tracking | **Sentry** | 5 k errors/month |
| Uptime and the "keep-alive" ping | **UptimeRobot** | 50 monitors, 5-minute interval |

**Email authenticity, layered:**

1. Supabase confirmation email. Unverified users can browse but cannot download. `email_confirmed_at` is the flag.
2. Disposable-domain blocklist at sign up (the `disposable-email-domains` Python package, ~4,000 domains). Block or flag as `risk: disposable`.
3. MX record lookup with `dnspython`: if the domain cannot receive mail, reject.
4. Cloudflare Turnstile (free CAPTCHA) on the sign-up form to stop bots before they create rows.
5. Optional later: a paid verification API (ZeroBounce, Abstract) only for users who hit a quota.

Each check writes an event, so the admin dashboard can show verified vs unverified vs suspicious sign ups over time.

---

## 2. Phases

### Phase 0: Foundations (done 2026-09-04)

- Monorepo: `backend/` (FastAPI, uv), `frontend/` (Next.js 16, Tailwind 4), `docs/`, `supabase/`.
- Core engine: URL parsing, format selection, yt-dlp wrapper with progress and cancel, friendly error mapping, FFmpeg detection.
- API: `/health`, `GET /api/v1/info`, `POST /api/v1/jobs`, `GET /api/v1/jobs/{id}`, `GET /api/v1/jobs/{id}/file`, `DELETE /api/v1/jobs/{id}`. Rate limited per IP.
- Supabase JWT verification scaffolded (off by default in dev).
- Mobile-first UI: paste box, preview card, Audio/Video toggle, quality chips, live progress, save button, sticky action bar, dark mode, PWA manifest with Android share target.
- Verified end to end on Windows: a video became a tagged MP3 with square cover art.
- 36 backend tests, frontend lint + type check + production build all green.
- Dockerfile with FFmpeg, `.env.example`, Supabase migration, CI workflow.

### Phase 1: Solid single-user product (done 2026-09-04)

Goal: anyone with the link can use it reliably on a phone, no account yet.

Shipped:
- Jobs persist in a database (SQLite locally, Postgres in production) through SQLAlchemy. History survives restarts; a job that was mid-download when the server died is marked "interrupted" with a friendly message, and queued jobs are re-run.
- Storage layer with two backends: local disk (API streams the file) and Cloudflare R2 (API redirects to a one-hour signed link, zero egress). Selected with `DM_STORAGE`. The R2 path is unit-tested against an S3 emulator.
- Anonymous ownership: the browser generates a client id once, sends it as `X-Client-Id`, and only sees its own jobs. Signed-in users take over in Phase 2 with the same code path.
- Files expire after the TTL; a janitor deletes them and keeps the history row. Expired links answer 410 with "download it again".
- Cancel deletes partial files and frees the worker slot. Progress writes to the database are throttled to twice a second.
- UI: recent downloads on this device with re-save, copy-link button, link-expiry note, playlist notice ("only this video"), and clamped video presets when a video has no HD.
- Verified in a real phone-sized browser (Edge via Playwright): paste, preview, switch modes, download, save, reload, recent list, dark mode. Zero console errors. 48 backend tests.

Deferred: Server-Sent Events for progress (polling every second is fine at this scale); whole-playlist downloads (Phase 6).

Exit criteria for you to run: 20 consecutive downloads (10 audio, 10 video) on a phone over mobile data.

### Phase 2: Accounts and database (built 2026-09-04, one value still needed from you)

Goal: sign up, sign in, verified email, personal history.

Shipped:
- Schema applied to the Supabase project (profiles, downloads, events, Row Level Security, admin views) through `scripts/migrate.py`, which tracks applied files. The API refuses to start on a Postgres database without the schema.
- The API runs against Supabase Postgres through the pooler (psycopg 3, prepared statements off). Downloads, activity events, and the admin view were verified with real rows.
- Token verification with the project's public ES256 keys (JWKS), with HS256 fallback for older projects. Bad or expired tokens get 401.
- Sign-up goes through the API so the checks are enforced server-side: syntax, disposable-domain blocklist (about 4,000 domains), MX lookup, optional Cloudflare Turnstile. The result is stored as `email_risk` on the profile and as a `signup` or `signup_rejected` event. Then the API forwards to Supabase Auth, which sends the verification email.
- Rules: guests get `DM_ANON_DAILY_LIMIT` (3) downloads a day per browser; signed-in users must be email-verified and get `profiles.daily_quota` (20). `DM_REQUIRE_AUTH=true` turns guests off entirely. Rate limits key by token when signed in.
- Sign-in attaches the browser's guest downloads to the account (`POST /api/v1/auth/claim`), so history is not lost by signing up late.
- Events written by the API: signup, signup_rejected, signin, download_started, download_completed, download_failed, download_cancelled, quota_hit, account_deleted. IPs stored as salted hashes.
- Account deletion removes history, files, the profile, and (on Supabase) the auth user.
- Frontend: sign in, sign up (with the verification-sent screen and resend), forgot password, reset password, verification callback, account page (verified state, quota bar, sign out, delete), history page with thumbnails and auto-refresh, Download/History/Account tabs, banners for guests and unverified users, Google sign-in button. Without Supabase keys the UI runs in guest mode and shows a clear "not set up" page.
- Also fixed on the way: M4A and Opus cover art embedding needed `mutagen`.
- 73 backend tests. Frontend lint, types, build, and a browser run of the guest flow on the Postgres-backed API pass.

Not verified yet, because it needs the project's anon key: the browser side of sign-up, the verification email, and sign-in. Steps to finish:
1. Supabase Dashboard > Project Settings > API: copy the anon/publishable key into `frontend/.env.local` as `NEXT_PUBLIC_SUPABASE_ANON_KEY` and into `backend/.env` as `DM_SUPABASE_ANON_KEY`.
2. Dashboard > Authentication > URL Configuration: Site URL `http://localhost:3000`; add `http://localhost:3000/auth/callback` and `http://localhost:3000/auth/reset` to Redirect URLs (later the Vercel domain too).
3. Optional: Authentication > Providers > Google (needs a Google Cloud OAuth client). Optional: Cloudflare Turnstile keys.
4. Restart both servers, sign up with a real address, tap the link, download once, then sign in on a second browser and see the same history.

Note on the free email service: Supabase sends only a few auth emails per hour on the free tier. For real users, add a custom SMTP provider (Resend and Brevo have free tiers) in Authentication > SMTP Settings.

Exit criteria unchanged: sign up, verify, download, sign in elsewhere and see the same history; a disposable email is refused with a clear message.

### Phase 3: Mobile-first UI/UX pass (1 week)

Goal: it feels like an app, not a form.

- Design system in Tailwind tokens (already started in `globals.css`): spacing scale, type scale, semantic colors, motion.
- Bottom navigation: Download, History, Account.
- Install prompt for the PWA, app icon set (192/512 PNG in addition to SVG), splash colors, offline shell that explains "you are offline".
- Share target polish: opening from the YouTube app lands directly on the preview with the right mode preselected.
- Accessibility: focus order, labels, contrast in both themes, reduced motion, screen-reader announcements for progress.
- Performance: Lighthouse mobile score 90+ on Performance and Accessibility. Fonts subset, thumbnails lazy.
- Empty, loading, error, and success states designed for every screen.
- Exit criteria: usability test with 3 people on their own phones, each completes a download without help.

### Phase 4: Deployment and operations (3 to 4 days)

Goal: a public URL, deployed automatically from `main`, monitored.

- Vercel project for `frontend/`, env `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
- Render web service from `backend/Dockerfile`, env from `.env.example`, health check `/health`, persistent disk not needed (files go to R2).
- R2 bucket with lifecycle rule and an API token scoped to that bucket.
- DNS at GoDaddy: `app.yourdomain` to Vercel, `api.yourdomain` to Render. Lock CORS to the app origin.
- GitHub Actions (already in `.github/workflows/ci.yml`): lint, tests, build on every PR. Deploys are automatic from `main` on Vercel and Render.
- UptimeRobot on `/health` every 5 minutes (also keeps Render and Supabase awake).
- Nightly job that rebuilds the backend image so `yt-dlp` stays current. YouTube changes break old versions within weeks.
- Weekly `pg_dump` from a GitHub Action to R2 (free backups; Supabase free tier has none).
- Sentry in both apps.
- Exit criteria: push to `main` reaches production in under 5 minutes with zero manual steps; an outage pages you by email.

### Phase 5: Analytics and user activity (4 to 5 days)

Goal: know who signs up, whether their email is real, and what they do.

- API writes to `events` for: `signup`, `email_verified`, `signin`, `info_requested`, `download_started`, `download_completed`, `download_failed` (with error code), `quota_hit`. Properties as JSONB. IP stored as a salted hash, never raw.
- PostHog snippet in the frontend with the same event names, identified by the Supabase user id. Funnels: sign up to verified, verified to first download, first download to 7-day return.
- Admin dashboard (route guarded by `profiles.role = 'admin'`):
  - Sign ups per day, split verified / unverified / disposable / bounced.
  - Daily and weekly active users.
  - Downloads per day by mode and format, success rate, top error codes.
  - Median time from paste to file ready.
  - Top email domains, flagged accounts.
- Data hygiene: 90-day retention on raw events, a privacy policy page, cookie consent for PostHog if you have EU visitors.
- Exit criteria: you can answer "how many real users did I get this week and what did they download" from one page.

### Phase 6: Hardening, quotas, and growth (ongoing)

- Abuse controls: per-user and per-IP quotas, file size caps, refuse videos over 3 hours, ban list.
- YouTube bot-check strategy: cookies from a dedicated throwaway account, or route the worker through a residential proxy, or run the worker on a home machine or VM whose IP is not flagged. Decide when it first happens, not before.
- Whole-playlist downloads with a job queue and per-item progress.
- Sentry alerts to email or Telegram, cost alerts on R2 and Render.
- Legal pages: Terms of Service, Privacy Policy, DMCA contact. Personal-use disclaimer at sign up.
- Second language for the UI if your users need it.
- Cost review: at roughly 200 daily downloads you will outgrow Render free; move the worker to the Oracle VM or Hetzner and keep everything else free.

### Phase 7 (optional): Native mobile

- Wrap the PWA with Capacitor for an installable Android app, or build an Expo app that talks to the same API.
- Push notification when a long download finishes.
- Only worth it if the PWA share target is not enough for your users.

---

## 3. Timeline

| Phase | Duration | Cumulative |
|---|---|---|
| 0 Foundations | done | week 0 |
| 1 Solid single-user product | done | week 0 |
| 2 Accounts and database | built, needs anon key | week 0 |
| 3 Mobile-first UI/UX | 1 week | week 3 |
| 4 Deployment and operations | 3 to 4 days | week 4 |
| 5 Analytics | 4 to 5 days | week 5 |
| 6 Hardening and growth | ongoing | week 6+ |

Phases 2 and 3 can swap if you want the public URL sooner. Phase 4 can move earlier so every phase deploys to a real URL, which is the better habit.

---

## 4. Best practices baked in

**Security**
- User input never reaches a shell. yt-dlp is called through its Python API.
- Only YouTube hosts are accepted, checked before yt-dlp runs.
- JWT verified on every request; Row Level Security in Postgres as the second wall.
- Secrets only in environment variables. `.env` files are git-ignored; `.env.example` documents the keys.
- CORS locked to the frontend origin. HTTPS everywhere (free on Vercel and Render).
- Rate limits per IP now, per user in Phase 2.

**Reliability**
- Retries on transient network errors. Files deleted after a TTL. Cancel cleans up partial files.
- Health endpoint reports FFmpeg and yt-dlp versions so a broken deploy is visible immediately.
- Nightly rebuild keeps yt-dlp current.

**Privacy**
- Store the video id, not the whole URL with tracking parameters.
- Hash IPs. Keep raw events 90 days. No third-party trackers beyond PostHog, and only with consent where required.
- Delete a user's files and history on account deletion.

**Engineering**
- `core/` has no HTTP or UI code, so it is testable and reusable.
- Same Docker image in CI, locally, and in production.
- Migrations in `supabase/migrations`, applied in order, never edited after they ship.

---

## 5. Risks specific to hosting

| Risk | Likelihood | Mitigation |
|---|---|---|
| YouTube blocks datacenter IPs ("confirm you're not a bot") | High over time | Worker on a VM with a clean IP, cookies from a throwaway account, or a residential proxy. Detect the error code and show a friendly message meanwhile. |
| Hosting provider objects to a downloader | Medium | Keep it personal-use, no public marketing of "download any song", quotas, personal-use disclaimer. Have the Docker image ready to move to a VPS in an hour. |
| Bandwidth cost | Medium | R2 for delivery (no egress fees), file size caps, 1-hour TTL, quotas. |
| Operator ToS and copyright exposure | Medium | This is the operator's risk now, not the end user's. Personal use only, no redistribution, DMCA contact page, do not monetize. |
| Supabase free project pauses | Low with the uptime ping | UptimeRobot every 5 minutes. |
| yt-dlp breaks after a YouTube change | Certain, periodically | Nightly rebuild, health endpoint shows the version, Sentry alert on a spike of `download_failed`. |

---

## 6. Decisions to make (defaults chosen)

| Question | Default | Change if |
|---|---|---|
| Deliver files through the API or through R2? | R2 from Phase 1 | You want zero third-party services and accept the bandwidth cap. |
| Require sign in to download? | Yes from Phase 2, with a small anonymous allowance (3 per day per IP) | You want a fully private app: require sign in for everything. |
| Google login? | Yes, alongside email + password | You prefer email only for simplicity. |
| PostHog or self-hosted analytics? | PostHog Cloud | You have EU users and want data in your own Postgres only: use the `events` table plus a simple dashboard. |
| Where does the worker run long term? | Oracle Always Free ARM VM | Sign-up for Oracle fails (it is flaky); use Hetzner at ~€4/month. |
