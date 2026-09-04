# Deployment runbook

| Field | Value |
|---|---|
| Status | Phase 4 |
| Date | 2026-09-04 |
| Companion docs | [ROADMAP.md](ROADMAP.md), [PRD.md](PRD.md) |

Follow this top to bottom once. Expect **60 to 90 minutes**, most of it waiting
for DNS. Everything below is free.

| Layer | Service | Ends up at |
|---|---|---|
| Frontend | Vercel Hobby | `https://app.yourdomain.com` |
| Backend | Render free web service (Docker) | `https://api.yourdomain.com` |
| Database + auth | Supabase (`qzngtrpdqtvgrbaxtzar`, ap-northeast-2) | already exists |
| File delivery | Cloudflare R2 | signed links, zero egress to users |
| Monitoring | UptimeRobot | email on an outage |

The repo already contains everything that can be prepared in advance:

| File | What it does |
|---|---|
| [`render.yaml`](../render.yaml) | Render Blueprint: the whole backend service, secrets declared by name |
| [`frontend/vercel.json`](../frontend/vercel.json) | Security headers, function region |
| [`backend/Dockerfile`](../backend/Dockerfile) | The production image (non-root, multi-stage, `$PORT`) |
| [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | Lint, tests, build, and a real start of the image |
| [`.github/workflows/nightly-ytdlp.yml`](../.github/workflows/nightly-ytdlp.yml) | Keeps yt-dlp current |
| [`.github/workflows/backup-database.yml`](../.github/workflows/backup-database.yml) | Weekly `pg_dump` to R2 |

Replace `yourdomain.com` with your GoDaddy domain everywhere below.

---

## 0. Decide the two hostnames first

Everything else references them, so choosing now avoids a second pass:

- **`app.yourdomain.com`** - the UI, on Vercel.
- **`api.yourdomain.com`** - the API, on Render.

Same-site subdomains, so cookies and CORS stay simple. Write them down; you will
paste them five times.

---

## 1. Supabase

The schema is already applied. This step is settings only.

**1.1 Confirm the schema.** From your laptop, with `backend/.env` pointing at the
project:

```powershell
cd backend
uv run python scripts/migrate.py --status
```

Everything should read as applied. The API refuses to start against a Postgres
database with no schema, so this is worth doing before Render tries.

**1.2 Copy the two connection strings.** Dashboard > **Connect**:

| Which | Port | Used by |
|---|---|---|
| **Transaction pooler** | 6543 | `DM_DATABASE_URL` on Render |
| **Session pooler** | 5432 | `SUPABASE_DB_URL` GitHub secret, for `pg_dump` |

They are different on purpose. The transaction pooler cannot run `pg_dump` (no
session state, and it breaks the `COPY` protocol); the session pooler is fine for
both but the app is better off on the transaction pooler.

Use the `postgres` user in both. Account deletion runs
`delete from auth.users`, which needs that role.

**1.3 Copy the anon key.** Project Settings > **API** > `anon` / publishable key.
You will paste it into Render (`DM_SUPABASE_ANON_KEY`) and Vercel
(`NEXT_PUBLIC_SUPABASE_ANON_KEY`). It is the same key, and it is safe in a
browser - but still keep it out of git.

**1.4 URL configuration.** Authentication > **URL Configuration**:

- **Site URL**: `https://app.yourdomain.com`
- **Redirect URLs**, add all four:
  - `https://app.yourdomain.com/auth/callback`
  - `https://app.yourdomain.com/auth/reset`
  - `http://localhost:3000/auth/callback`
  - `http://localhost:3000/auth/reset`

Keep the localhost entries or local development stops working. The two paths
match `frontend/src/app/auth/callback/` and `frontend/src/app/auth/reset/`;
if those routes are ever renamed, this list has to change with them.

**1.5 SMTP.** Supabase's built-in mailer sends only a **few auth emails per
hour** on the free tier, shared across the whole project. That is enough for you
to test with and not enough for real sign-ups: the second person to sign up in an
hour silently never gets a verification mail.

Before you invite anyone, set Authentication > **SMTP Settings** to your own
provider (Resend and Brevo both have free tiers) and set the sender to an address
on `yourdomain.com`. Add the provider's SPF and DKIM records at GoDaddy in the
same sitting as the records in step 6, or the mail lands in spam.

**1.6 Google sign-in (optional).** Authentication > Providers > Google needs a
Google Cloud OAuth client whose redirect URI is
`https://qzngtrpdqtvgrbaxtzar.supabase.co/auth/v1/callback`. The sign-in page
always shows the "Continue with Google" button; until the provider is enabled,
tapping it answers *"Google sign-in is not enabled yet."* So either turn it on
here or expect that dead end.

---

## 2. Cloudflare R2

Two buckets, because they want opposite lifetimes: delivery files are deleted
within the hour, backups are kept for months.

**2.1 Create the delivery bucket.** R2 > Create bucket:

- Name: **`downloader-manager-files`** (`render.yaml` sets `DM_R2_BUCKET` to
  exactly this - change one and change the other)
- Location: **APAC**, to sit near Render Singapore and Supabase Seoul
- Public access: **off**. It stays off. Users get pre-signed links that expire.

**2.2 Lifecycle rule on the delivery bucket.** Bucket > Settings > Object
lifecycle rules > Add rule:

- Applies to: all objects
- Action: **delete objects 1 day after creation**

The app already deletes each file after `DM_JOB_TTL_MINUTES` (60). This rule is
the backstop for the files it misses - a crashed worker, a cancelled job, a
deploy mid-upload. R2's lifecycle UI works in whole days, so one day is the
tightest it goes; the app's own one-hour deletion is what users experience.

**2.3 Create the backup bucket.** Name **`downloader-manager-backups`**, same
region, public access off. Add a lifecycle rule to **delete objects after 180
days**. Weekly dumps at a few MB each will never come near the free 10 GB.

**2.4 Create one API token.** R2 > **Manage R2 API Tokens** > Create token:

- Permissions: **Object Read & Write**
- Scope: **Apply to specific buckets** - select both buckets, nothing else
- TTL: forever, or set a reminder to rotate

Cloudflare shows the values once. Copy three things:

| Shown as | Goes to |
|---|---|
| Access Key ID | `DM_R2_ACCESS_KEY_ID` (Render), `R2_ACCESS_KEY_ID` (GitHub) |
| Secret Access Key | `DM_R2_SECRET_ACCESS_KEY` (Render), `R2_SECRET_ACCESS_KEY` (GitHub) |
| Account ID (in the endpoint `https://<account id>.r2.cloudflarestorage.com`) | `DM_R2_ACCOUNT_ID` (Render), `R2_ACCOUNT_ID` (GitHub) |

Do not use an account-wide token. If it leaks, a bucket-scoped token costs you
two buckets; an account token costs you the account.

---

## 3. Render (backend)

**3.1 Create from the Blueprint.** Render Dashboard > **New** > **Blueprint** >
connect the GitHub repo > it finds `render.yaml` at the root.

Render then prompts once for each variable declared with `sync: false`. Fill in
all six:

| Prompt | Value |
|---|---|
| `DM_CORS_ORIGINS` | `["https://app.yourdomain.com"]` |
| `DM_DATABASE_URL` | the **transaction pooler** URI from step 1.2 (port 6543) |
| `DM_R2_ACCOUNT_ID` | from step 2.4 |
| `DM_R2_ACCESS_KEY_ID` | from step 2.4 |
| `DM_R2_SECRET_ACCESS_KEY` | from step 2.4 |
| `DM_SUPABASE_ANON_KEY` | from step 1.3 |

`DM_CORS_ORIGINS` is **JSON, not a comma list**. It is parsed by pydantic as
`list[str]`, so `https://app.yourdomain.com` on its own fails to start the
service. Scheme included, no trailing slash. If you also want the raw
`*.vercel.app` URL to work while testing:
`["https://app.yourdomain.com","https://downloader-manager.vercel.app"]`.

Never `["*"]`. The API sends credentials, so a wildcard origin would let any
website read a signed-in user's history.

Everything else - `DM_STORAGE=r2`, the quotas, the rate limits, `FORWARDED_ALLOW_IPS`,
a generated `DM_IP_HASH_SALT` - comes from `render.yaml` and needs no input. The
full list is in the reference table at the end of this document.

**3.2 Wait for the first deploy.** Five to ten minutes for the first Docker
build (FFmpeg is a big layer); later ones are faster because the dependency layer
is cached. Then:

```
curl https://<the onrender.com URL Render shows>/health
```

Expect `"status":"ok"`, `"ffmpeg":true`, `"storage":"r2"`,
`"database":"postgresql"`, `"environment":"production"`. Anything else - see
"What breaks first".

**3.3 Add the custom domain.** Service > Settings > **Custom Domains** > add
`api.yourdomain.com`. Render shows the exact CNAME target
(`downloader-manager-api.onrender.com`). Keep the page open for step 6.

**3.4 Know what the free plan does.** 512 MB RAM, ephemeral disk, and a spin-down
after 15 minutes idle that makes the next request take ~40 seconds. The
UptimeRobot monitor in step 8 prevents the spin-down. 750 instance-hours a month
covers one always-on service with a little to spare. Upgrading to Starter ($7)
removes the spin-down and doubles the memory; nothing in the config changes.

---

## 4. Vercel (frontend)

**4.1 Import the project.** Vercel > **Add New** > **Project** > the same repo.

| Setting | Value |
|---|---|
| Framework preset | Next.js (auto-detected) |
| **Root Directory** | **`frontend`** |
| Build / Output / Install command | leave as the defaults |
| Node.js version | 22.x |

The Root Directory is the one setting that is not in a file and the one that
breaks the build if you miss it. Vercel picks up `frontend/vercel.json` for
headers and the function region.

**4.2 Environment variables.** Set all three for **Production, Preview, and
Development**:

| Name | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://api.yourdomain.com` |
| `NEXT_PUBLIC_SUPABASE_URL` | `https://qzngtrpdqtvgrbaxtzar.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | the anon key from step 1.3 |

Optional, only if you turned on Turnstile: `NEXT_PUBLIC_TURNSTILE_SITE_KEY`
(and its partner `DM_TURNSTILE_SECRET` on Render).

`NEXT_PUBLIC_*` values are compiled into the JavaScript bundle at build time, so
**changing one needs a redeploy**, not just a restart. No trailing slash on
`NEXT_PUBLIC_API_URL` (the code strips one, but do not rely on it).

**4.3 Add the custom domain.** Project > Settings > **Domains** > add
`app.yourdomain.com`. Vercel shows the CNAME target to use - usually
`cname.vercel-dns.com`, sometimes a project-specific host. Copy what it shows.

**4.4 What `vercel.json` does, and why it is that short.** Next.js on Vercel
needs no build configuration, so the file only carries what the dashboard cannot:

- **`regions: ["icn1"]`** - Seoul, the same region as the Supabase project
  (ap-northeast-2). Hobby allows exactly one. Static assets are served from every
  edge location regardless; this only pins server rendering.
- **Security headers** on every route: HSTS, `nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy`, `Permissions-Policy`, and
  `Cross-Origin-Opener-Policy: same-origin-allow-popups`. The `-allow-popups`
  variant is deliberate: Supabase's Google sign-in redirects today, but a future
  switch to a popup would break under plain `same-origin`.
- **`Cache-Control: public, max-age=0, must-revalidate` on `/sw.js`** - a
  service worker cached by the CDN keeps serving an old app long after a deploy,
  and it is the hardest kind of stale to explain to a user.
- **No Content-Security-Policy.** A useful CSP for Next.js needs per-request
  nonces from middleware, which is application code and out of scope here. Ship
  it with the Phase 6 hardening pass and test it against the Turnstile and
  Google sign-in flows.

If you would rather this app were not indexed - reasonable, given the Legal note
in the README - add `{"key": "X-Robots-Tag", "value": "noindex, nofollow"}` to
the header list.

---

## 5. GitHub secrets and settings

Settings > Secrets and variables > **Actions** > New repository secret. Names
must match exactly; the workflows reference them by name only.

| Secret | Value | Used by |
|---|---|---|
| `SUPABASE_DB_URL` | **session pooler** URI, port **5432** (step 1.2) | `backup-database.yml` |
| `R2_ACCOUNT_ID` | Cloudflare account id | `backup-database.yml` |
| `R2_ACCESS_KEY_ID` | R2 token id | `backup-database.yml` |
| `R2_SECRET_ACCESS_KEY` | R2 token secret | `backup-database.yml` |
| `R2_BACKUP_BUCKET` | `downloader-manager-backups` | `backup-database.yml` |
| `GH_PAT` *(optional)* | fine-grained PAT, Contents + Pull requests write | `nightly-ytdlp.yml` |

Then Settings > Actions > General > **Workflow permissions**:

- **Read and write permissions**
- **Allow GitHub Actions to create and approve pull requests**

Without those two the nightly job pushes its branch and then fails to open the
PR; it falls back to opening an issue, so you still find out.

`GH_PAT` is optional and only affects one thing: GitHub does not run CI on pull
requests opened with the built-in `GITHUB_TOKEN`. The nightly job runs `ruff` and
the full test suite itself before opening the PR, so the bump is tested either
way - a PAT just makes the checks visible on the PR.

**Verify both workflows by hand before trusting them.** Actions tab > pick the
workflow > **Run workflow**:

- *Weekly database backup* should finish in about a minute and print the object
  key in its summary. Check the object really is in the R2 bucket.
- *Nightly yt-dlp* will most likely say "yt-dlp x.y.z is the latest release" and
  stop. That is a pass.

---

## 6. DNS at GoDaddy

My Products > your domain > **DNS** > Manage Zones. Add two records:

| Type | Name | Value | TTL |
|---|---|---|---|
| CNAME | `app` | the target Vercel showed in 4.3 (usually `cname.vercel-dns.com`) | 600 |
| CNAME | `api` | `downloader-manager-api.onrender.com` (from 3.3) | 600 |

Notes:

- GoDaddy's "Name" field takes the **subdomain only** - `app`, not
  `app.yourdomain.com`.
- Leave off the trailing dot; GoDaddy adds it.
- If GoDaddy already has a parking or forwarding record on `app` or `api`, delete
  it first. Two records on one name is the most common reason a domain never
  verifies.
- Propagation is usually minutes at TTL 600, occasionally an hour. Check with
  `nslookup app.yourdomain.com`.

Both Vercel and Render issue their own TLS certificates once the CNAME resolves.
Neither needs anything else from you. Wait for both dashboards to show the domain
as verified with a valid certificate before the smoke test.

If you also added SMTP in step 1.5, add that provider's SPF, DKIM, and DMARC
records now, in the same visit.

---

## 7. Lock the wiring

Three values must agree, and each lives in a different dashboard. Recheck them
after the domains verify:

| This | must exactly equal | this |
|---|---|---|
| Render `DM_CORS_ORIGINS` | | the Vercel domain the browser uses, as JSON |
| Vercel `NEXT_PUBLIC_API_URL` | | the Render custom domain |
| Supabase Site URL | | the Vercel domain |

Changing `DM_CORS_ORIGINS` on Render restarts the service (about a minute).
Changing `NEXT_PUBLIC_API_URL` on Vercel needs a **redeploy**, not a restart.

Nothing in the repo defaults to a permissive production configuration: the code's
CORS default is `["http://localhost:3000"]`, `render.yaml` declares
`DM_CORS_ORIGINS` with no value at all so Render forces you to choose, and CI
fails if a wildcard or a literal secret ever lands in `render.yaml` or an
`.env.example` file.

---

## 8. UptimeRobot

uptimerobot.com > Add New Monitor:

| Field | Value |
|---|---|
| Monitor Type | HTTP(s) |
| Friendly Name | `downloader-manager api` |
| URL | `https://api.yourdomain.com/health` |
| Monitoring Interval | **5 minutes** |
| Alert contact | your email |

This does three jobs at once:

1. Emails you when the API is down.
2. Keeps the Render free instance from spinning down, so nobody waits 40 seconds.
3. Indirectly, it keeps the **Supabase free project from pausing** after 7 idle
   days. `/health` itself does not touch the database - but keeping the Render
   container awake keeps its janitor thread alive, and that runs a `select`
   against Supabase every 60 seconds. Delete this monitor and, after a week
   with no users, the project pauses and the API cannot start at all.

Optionally add a second monitor on `https://app.yourdomain.com/` for the UI.

---

## 9. Smoke test

In order. Stop at the first failure - the later steps assume the earlier ones.

**9.1 API is healthy.**

```powershell
curl https://api.yourdomain.com/health
```

Every field should be right: `"status":"ok"`, `"ffmpeg":true`,
`"environment":"production"`, `"storage":"r2"`, `"database":"postgresql"`,
`"auth_enabled":true`, `"signup_enabled":true`. Note the `ytdlp_version` -
that number is how you later tell whether a deploy actually took the nightly bump.

**9.2 CORS is right, from the browser.** Open `https://app.yourdomain.com`, open
DevTools > Console, and paste a link. If the preview card appears, CORS is
correct. If the console shows *"blocked by CORS policy"*, `DM_CORS_ORIGINS` on
Render does not match the origin in the address bar - character for character,
including `https://` and no trailing slash.

**9.3 A real download.** Paste a short YouTube link, choose **Audio**, download,
save. Then check:

- The file plays and has the title and cover art.
- In DevTools > Network, `GET /api/v1/jobs/<id>/file` answers **302** to a
  `*.r2.cloudflarestorage.com` URL rather than streaming the bytes itself. That
  redirect is the zero-egress path working.
- Cloudflare > R2 > `downloader-manager-files` has the object.
- Supabase > Table Editor > `downloads` has the row, and `events` has
  `download_started` and `download_completed`.

**9.4 Auth end to end.** Sign up with a real address, get the verification mail,
tap the link, land on `/auth/callback` signed in. Then sign in from a second
browser and confirm the history is there. Then try a disposable address
(`mailinator.com`) and confirm it is refused with a clear message.

**9.5 The file really expires.** Wait an hour, reopen the link from 9.3. It
should answer **410** with "download it again", and the object should be gone
from R2.

**9.6 Deploy from `main` reaches production.** Push a trivial commit. Render and
Vercel should both build and go live in under five minutes with no manual step.
That is the Phase 4 exit criterion.

---

## 10. Rollback

**Frontend.** Vercel > Deployments > pick the last known-good production
deployment > **Instant Rollback** / Promote to Production. Seconds, no rebuild.
Remember that `NEXT_PUBLIC_*` values are baked in at build time, so rolling back
also rolls back those values.

**Backend.** Render > the service > **Deploys** > find the last successful deploy
> **Rollback to this deploy**. It redeploys a cached image, so it is quick.
Environment variable changes are *not* part of a deploy - if the bad change was a
variable, fix the variable and let it restart.

**A bad yt-dlp bump.** Revert the merge commit on `main`. Render redeploys the
previous lockfile automatically. The nightly job will offer the same bump again
tomorrow; close that PR with a comment so you remember why.

**Database.** There is no undo, only the weekly dump. To restore:

```bash
export AWS_ACCESS_KEY_ID=<R2 token id>
export AWS_SECRET_ACCESS_KEY=<R2 token secret>
export AWS_DEFAULT_REGION=auto

aws s3 ls s3://downloader-manager-backups/backups/2026/ \
  --endpoint-url https://<account id>.r2.cloudflarestorage.com
aws s3 cp s3://downloader-manager-backups/backups/2026/dm-<stamp>.sql.gz . \
  --endpoint-url https://<account id>.r2.cloudflarestorage.com
gunzip dm-<stamp>.sql.gz
psql "<session pooler URI, port 5432>" -v ON_ERROR_STOP=1 -f dm-<stamp>.sql
```

Restore into a **fresh Supabase project** unless you are certain the live one is
empty; the dump contains `CREATE TABLE` statements that will collide otherwise.
Then point `DM_DATABASE_URL` at the new project and redeploy. Practise this once
while nothing is on fire - an untested backup is not a backup.

**Everything at once.** The Docker image is the whole backend. `docker compose up`
on any VPS with the same environment variables reproduces production, which is
the escape hatch in the roadmap's hosting table.

---

## 11. What breaks first

Roughly in the order you should expect it.

**1. YouTube starts asking Render to confirm it is not a bot.** *Weeks to months.
Near certain.* Datacenter IP ranges get flagged. Downloads start failing with a
bot-check error while everything else looks perfectly healthy. This is the reason
the roadmap keeps a VM as step two: same image, an IP that is not flagged. Short
term you can attach cookies from a throwaway account; long term move the worker
to Oracle Always Free or a Hetzner box.

**2. yt-dlp goes stale.** *Weeks. Certain, repeatedly.* A YouTube player change
breaks the pinned version. The nightly workflow is the mitigation, but only if
you actually merge its pull requests - the bump does nothing sitting in a branch.
Compare `ytdlp_version` on `/health` against the latest release when downloads
start failing in a batch.

**3. The Supabase project pauses.** *After 7 idle days.* Free projects pause, and
a paused project means the API cannot start at all. The UptimeRobot monitor
prevents it: it keeps the Render container awake, and the container's janitor
thread queries the database every 60 seconds, which Supabase counts as activity.
Delete the monitor and this comes back a week later.

**4. Render memory.** *512 MB.* A long video plus FFmpeg remuxing is the usual
way to hit it; the container is killed and restarts. `DM_WORKER_CONCURRENCY=1`
and `DM_MAX_FILE_MB=300` in `render.yaml` are set low for exactly this. If you
see restarts under load, upgrade to Starter before tuning further.

**5. Render egress.** *100 GB/month.* R2 removes egress **to users**, but Render
still pays to push each finished file **to** R2. So the cap is roughly 100 GB of
downloaded content a month - thousands of songs, or a couple of hundred large
videos. This is the number that decides when the worker moves to a VM.

**6. Free-tier auth email.** *Immediately, once more than one person signs up in
an hour.* Covered in step 1.5. The failure is silent: no error, no mail.

**7. Rate limiting sees the wrong IP.** *Only if `FORWARDED_ALLOW_IPS` is lost.*
Uvicorn trusts `X-Forwarded-For` only from the addresses in that variable, and
its default is `127.0.0.1`. On Render it must be `*`, or every request looks like
it came from the load balancer and `DM_RATE_LIMIT_JOBS` becomes a single global
cap for all users. The trade-off of `*` is that a determined client can spoof
`X-Forwarded-For` to dodge the per-IP limit; the per-browser and per-account
quotas still apply. Putting Cloudflare in front of the API and trusting only
Cloudflare's ranges is the Phase 6 fix.

**8. R2 storage.** *10 GB.* Only reachable if the lifecycle rule in step 2.2 is
missing. Check the bucket size if the free tier ever looks close.

---

## 12. Environment variable reference

Names exactly as the code reads them. Backend variables are the `DM_` prefix plus
the field name in `backend/app/config.py`; the frontend reads `process.env`
directly.

### Render (backend)

Set by `render.yaml` unless the Source column says otherwise.

| Variable | Value | Source |
|---|---|---|
| `DM_ENVIRONMENT` | `production` | blueprint |
| `DM_LOG_LEVEL` | `info` | blueprint |
| `DM_CORS_ORIGINS` | `["https://app.yourdomain.com"]` (JSON array) | **you, at creation** |
| `DM_DATABASE_URL` | Supabase transaction pooler URI, port 6543 | **you, at creation** |
| `DM_STORAGE` | `r2` | blueprint |
| `DM_R2_BUCKET` | `downloader-manager-files` | blueprint |
| `DM_R2_ACCOUNT_ID` | Cloudflare account id | **you, at creation** |
| `DM_R2_ACCESS_KEY_ID` | R2 token id | **you, at creation** |
| `DM_R2_SECRET_ACCESS_KEY` | R2 token secret | **you, at creation** |
| `DM_SUPABASE_URL` | `https://qzngtrpdqtvgrbaxtzar.supabase.co` | blueprint |
| `DM_SUPABASE_ANON_KEY` | anon / publishable key | **you, at creation** |
| `DM_REQUIRE_AUTH` | `false` (`true` = no guest downloads at all) | blueprint |
| `DM_ANON_DAILY_LIMIT` | `3` | blueprint |
| `DM_CHECK_DISPOSABLE_EMAIL` | `true` | blueprint |
| `DM_CHECK_MX` | `true` | blueprint |
| `DM_IP_HASH_SALT` | random 256-bit value | generated by Render |
| `DM_WORKER_CONCURRENCY` | `1` | blueprint |
| `DM_MAX_FILE_MB` | `300` | blueprint |
| `DM_MAX_DURATION_SEC` | `10800` | blueprint |
| `DM_JOB_TTL_MINUTES` | `60` | blueprint |
| `DM_RATE_LIMIT_INFO` | `30/minute` | blueprint |
| `DM_RATE_LIMIT_JOBS` | `10/minute` | blueprint |
| `FORWARDED_ALLOW_IPS` | `*` (read by uvicorn, not by the app) | blueprint |
| `DM_DOWNLOAD_DIR` | `/data/downloads` | Dockerfile |
| `PORT` | injected by Render, read by the container's `CMD` | Render |

Add in the dashboard only if you use them: `DM_TURNSTILE_SECRET`,
`DM_R2_ENDPOINT_URL` (only for a non-default R2 endpoint),
`DM_SUPABASE_JWT_SECRET` (legacy HS256 projects only), `DM_FFMPEG_LOCATION`
(never needed in the image - FFmpeg is on `PATH`).

### Vercel (frontend)

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://api.yourdomain.com` |
| `NEXT_PUBLIC_SUPABASE_URL` | `https://qzngtrpdqtvgrbaxtzar.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | anon / publishable key |
| `NEXT_PUBLIC_TURNSTILE_SITE_KEY` | optional, pairs with `DM_TURNSTILE_SECRET` |

### GitHub Actions

| Secret | Value |
|---|---|
| `SUPABASE_DB_URL` | Supabase **session pooler** URI, port **5432** |
| `R2_ACCOUNT_ID` | Cloudflare account id |
| `R2_ACCESS_KEY_ID` | R2 token id |
| `R2_SECRET_ACCESS_KEY` | R2 token secret |
| `R2_BACKUP_BUCKET` | `downloader-manager-backups` |
| `GH_PAT` | optional; only makes CI run on the nightly bump PR |

---

## 13. Still to do after this runbook

Phase 4 in the roadmap also lists **Sentry in both apps**. That needs an SDK in
`backend/app/` and `frontend/src/`, which is application code, so it is not part
of this deployment work. Add `sentry-sdk[fastapi]` and `@sentry/nextjs` in a
separate pass, with the DSNs as `SENTRY_DSN` on Render and
`NEXT_PUBLIC_SENTRY_DSN` on Vercel.
