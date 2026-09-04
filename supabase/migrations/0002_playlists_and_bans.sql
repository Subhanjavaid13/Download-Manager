-- Downloader Manager: whole-playlist downloads and the ban list (Phase 6).
-- Run with `uv run python scripts/migrate.py` from backend/ (add --dry-run first).
--
-- Tables
--   playlists  one row per whole-playlist download; the parent of N downloads rows
--   bans       user ids and hashed IPs that may not start downloads
--
-- Changes to existing tables
--   downloads gains playlist_job_id + playlist_index, NULL for ordinary single jobs.
--
-- Security
--   Row Level Security as in 0001: users read their own rows, admins read all,
--   only the API (service_role) writes. Nobody but an admin ever reads `bans`.

-- ---------------------------------------------------------------------------
-- playlists
-- ---------------------------------------------------------------------------
create table if not exists public.playlists (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid references public.profiles (id) on delete cascade,
  client_id        text,                     -- anonymous browser id (X-Client-Id)
  playlist_id      text not null,            -- YouTube's list id, never the full URL
  title            text,
  channel          text,
  thumbnail        text,
  mode             text not null check (mode in ('audio', 'video')),
  format           text not null,            -- mp3 | m4a | opus | mp4
  quality          text,                     -- '192' for kbps, '1080' for height, 'best'
  status           text not null default 'queued'
                   check (status in ('queued', 'running', 'done', 'partial',
                                     'error', 'cancelled')),
  -- counts, updated by the worker as each item ends
  total_items      integer not null default 0,
  completed_items  integer not null default 0,
  failed_items     integer not null default 0,
  cancelled_items  integer not null default 0,
  cancel_requested boolean not null default false,
  error_code       text,
  error_message    text,                     -- the end-of-run summary of failures
  created_at       timestamptz not null default now(),
  started_at       timestamptz,
  finished_at      timestamptz
);

create index if not exists playlists_user_created_idx
  on public.playlists (user_id, created_at desc);
create index if not exists playlists_client_created_idx
  on public.playlists (client_id, created_at desc);
create index if not exists playlists_status_idx on public.playlists (status);

comment on table public.playlists is
  'One whole-playlist download. Its items are downloads rows with playlist_job_id set.';
comment on column public.playlists.status is
  'partial = the run finished with some items failed; error = every item failed.';

-- ---------------------------------------------------------------------------
-- downloads: playlist membership
-- ---------------------------------------------------------------------------
alter table public.downloads
  add column if not exists playlist_job_id uuid
    references public.playlists (id) on delete cascade;
alter table public.downloads
  add column if not exists playlist_index integer;

-- Items of one playlist, in order. Also serves "is this row part of a playlist".
create index if not exists downloads_playlist_idx
  on public.downloads (playlist_job_id, playlist_index);

comment on column public.downloads.playlist_job_id is
  'Parent playlist, or NULL for an ordinary single-video download.';

-- ---------------------------------------------------------------------------
-- bans
-- ---------------------------------------------------------------------------
create table if not exists public.bans (
  id           uuid primary key default gen_random_uuid(),
  subject_type text not null check (subject_type in ('user', 'ip_hash')),
  subject      text not null,          -- a profiles.id, or the salted IP hash from events.ip_hash
  reason       text,
  created_by   text,                   -- who added it: an email, or 'script'
  created_at   timestamptz not null default now(),
  expires_at   timestamptz             -- NULL means forever
);

-- The lookup the API runs before every job: one index covers both subject kinds.
create unique index if not exists bans_subject_idx on public.bans (subject_type, subject);
create index if not exists bans_expires_idx on public.bans (expires_at);

comment on table public.bans is
  'Block list checked before a download starts. Raw IPs are never stored, only salted hashes.';

-- Is this caller blocked right now? Used by the API and handy in the SQL editor.
create or replace function public.is_banned(uid uuid, iphash text)
returns boolean language sql stable as $$
  select exists (
    select 1 from public.bans
    where (expires_at is null or expires_at > now())
      and ((subject_type = 'user'    and uid is not null    and subject = uid::text)
        or (subject_type = 'ip_hash' and iphash is not null and subject = iphash))
  );
$$;

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
alter table public.playlists enable row level security;
alter table public.bans      enable row level security;

drop policy if exists "playlists: own read"   on public.playlists;
drop policy if exists "playlists: admin read" on public.playlists;
create policy "playlists: own read"   on public.playlists for select using (user_id = auth.uid());
create policy "playlists: admin read" on public.playlists for select using (public.is_admin());

-- bans: admins read; nobody but the service role writes. A banned user must not
-- be able to see, or edit, the row that blocks them.
drop policy if exists "bans: admin read" on public.bans;
create policy "bans: admin read" on public.bans for select using (public.is_admin());

-- ---------------------------------------------------------------------------
-- Admin cheat sheet (no redeploy needed for any of these)
--
--   -- block a user, forever
--   insert into public.bans (subject_type, subject, reason, created_by)
--   select 'user', id::text, 'abuse', 'you@example.com'
--   from public.profiles where email = 'them@example.com';
--
--   -- block an IP for a week. Copy the hash from events.ip_hash; the raw IP is
--   -- never stored, so hash it with backend/scripts/ban.py instead of by hand:
--   --   uv run python scripts/ban.py add --ip 1.2.3.4 --days 7 --reason "scraping"
--
--   -- who is blocked
--   select subject_type, subject, reason, expires_at from public.bans order by created_at desc;
--
--   -- lift a ban
--   delete from public.bans where subject = '<id or hash>';
-- ---------------------------------------------------------------------------
