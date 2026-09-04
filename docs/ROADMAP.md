# Roadmap: Downloader Manager (web)

| Field | Value |
|---|---|
| Status | v2, all phases delivered |
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

### Phase 3: Mobile-first UI/UX pass (done 2026-09-04)

- Design tokens consolidated for spacing, type, motion and semantic colour, defined light-first with dark overrides so no colour exists only in one theme.
- Bottom navigation. The home page already had a sticky action bar, so both now render inside one fixed stack and overlap is structurally impossible rather than a matter of matched offsets. Verified by measuring positions, not by eye.
- Installable web app: real PNG icons at every size, an install prompt with an iOS fallback, and a service worker that is network-first for pages with a precached offline page and cache-first only for hashed assets. Verified by forcing the browser offline.
- Share target: a link shared from the YouTube app skips the input debounce so the preview appears at once, music links preselect Audio, everything else falls back to remembered preferences.
- Accessibility: skip link, one visible focus style, one heading per screen, a polite live region announcing download stage and progress, roving tabindex on the mode switch, spoken labels on quality chips.
- Fixed a real contrast failure found on the way: white on the dark-theme accent measured 2.7:1 and is now 6.9:1. Muted, amber, ok and danger were darkened in the light theme to clear 4.5:1.

No Lighthouse score: the tool is not available in this environment, so the underlying factors were checked by hand.

### Phase 4: Deployment and operations (built 2026-09-04, deploy still yours to run)

- `render.yaml` blueprint for the backend, `vercel.json` for the frontend, both with secrets declared by name only.
- Backend image rebuilt in two stages, non-root, read-only application directory. Three real defects fixed: the build context previously included the real environment file, the server was not the init process so shutdown never ran, and behind a load balancer every request carried the balancer's address, which silently turned the per-request rate limit into one global cap.
- The health endpoint reported only values cached at startup, so it could not detect a database outage and the uptime ping was not keeping the free database awake. It now runs a real query and reports the result.
- Nightly job bumps the downloader, runs the suite against it and opens a pull request. A plain image rebuild would have changed nothing, because the lockfile pins the version.
- Weekly database dump to object storage, since the free tier has no backups. Uses the session pooler, because the transaction pooler the app uses cannot run the dump.
- `docs/DEPLOYMENT.md` is the step-by-step runbook.

Docker is not installed on this machine, so the image was never built locally. The new continuous integration job builds and runs it, so the first run after pushing is the real test.

### Phase 5: Analytics and user activity (done 2026-09-04)

- Admin service and eight endpoints, all range-scoped, every figure aggregated in SQL rather than counted in application code.
- Access declared once as a router-level dependency so a later route cannot forget it. No token is refused, any role but admin is refused, and with authentication unconfigured the routes are closed rather than open.
- Dashboard leads with the answer in a sentence, then supporting figures, then a strip that appears only when something needs attention. Chart colours were chosen by running a validator, which caught two combinations that fail for colour-blind readers and one that fails for everyone.
- Product analytics are opt-in and inert without a key, with autocapture and session recording off and properties scrubbed of links, titles and addresses.
- Ninety-day event retention is now enforced nightly rather than merely documented, and the dashboard counts overdue rows so a job that quietly stops is visible.

Gap: the dashboard was exercised against a local copy of the real data, because production has no admin account to sign in as and creating one is the user's decision.

### Phase 6: Hardening, quotas, and playlists (done 2026-09-04)

- Whole-playlist downloads: a parent run with one child job per video, taking a single worker slot and running sequentially, with per-item progress, per-item files and per-item failure. A failed video does not stop the run. Cancelling stops the run and keeps what already finished. A restart re-queues only the item that died.
- Quota rule: one video is one download, and the whole playlist must fit in what is left today, refused up front with the numbers. This stops a guest's three-a-day meaning three playlists, and cannot be gamed because the children are real rows the existing count already sees.
- The file size cap was declared in settings and never read. It is now enforced during the download. Doing so surfaced a real bug: an oversized download aborts and still reports success, so the user saw a generic failure instead of being told to pick a lower quality.
- Client address strategy that cannot be forged by the caller, a ban list by user or hashed address that fails open on a database error, an optional cookie file for the bot check, and error reporting behind a key with a scrubber.
- Terms, privacy and copyright pages, honest about what this is, with every operator-specific detail left as a visible placeholder.

Not verified live: the over-cap refusal on a genuinely oversized playlist, video-mode playlists end to end, and playlists against object storage.

### Phase 7: Native mobile (deliberately deferred)

The roadmap always listed this as optional and worth doing only if the installable web app proves insufficient. This machine has neither Java nor an Android SDK, so a wrapper could not be built or verified here, and shipping an unbuildable project would be worse than not shipping one. The share target and install prompt already cover the case it was meant to solve.

## 3. Timeline

| Phase | State |
|---|---|
| 0 Foundations | done |
| 1 Solid single-user product | done |
| 2 Accounts and database | done, browser sign-in still needs the project's public key |
| 3 Mobile-first UI/UX | done |
| 4 Deployment and operations | built and documented, deploy is yours to run |
| 5 Analytics | done |
| 6 Hardening, quotas, playlists | done |
| 7 Native mobile | deferred on purpose, see above |

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
