-- Downloader Manager: initial schema (Phase 2).
-- Run in the Supabase SQL editor, or with `supabase db push`.
--
-- Tables
--   profiles   one row per auth user: role, quota, risk flags
--   downloads  one row per download job, owned by a user
--   events     activity log written by the API (analytics source of truth)
--
-- Security
--   Row Level Security is ON for every table. Users see only their own rows.
--   The API uses the service_role key for writes, which bypasses RLS.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- profiles
-- ---------------------------------------------------------------------------
create table if not exists public.profiles (
  id              uuid primary key references auth.users (id) on delete cascade,
  email           text not null,
  display_name    text,
  role            text not null default 'user' check (role in ('user', 'admin')),
  daily_quota     integer not null default 20,
  email_risk      text not null default 'unknown'
                  check (email_risk in ('unknown', 'ok', 'disposable', 'no_mx', 'bounced')),
  signup_ip_hash  text,
  signup_ua       text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

comment on table public.profiles is 'Per-user settings and risk flags. Mirrors auth.users.';
comment on column public.profiles.email_risk is 'Result of sign-up checks: disposable domain, missing MX, bounce.';

-- Create a profile automatically when a user signs up.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, email, display_name)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data ->> 'full_name', new.raw_user_meta_data ->> 'name')
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Keep updated_at fresh.
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists profiles_touch on public.profiles;
create trigger profiles_touch before update on public.profiles
  for each row execute function public.touch_updated_at();

-- ---------------------------------------------------------------------------
-- downloads
-- ---------------------------------------------------------------------------
create table if not exists public.downloads (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid references public.profiles (id) on delete cascade,
  client_id        text,                     -- anonymous browser id (X-Client-Id) before sign-in
  video_id         text not null,            -- never the full URL
  title            text,
  channel          text,
  duration_sec     integer,
  thumbnail        text,
  mode             text not null check (mode in ('audio', 'video')),
  format           text not null,            -- mp3 | m4a | opus | mp4
  quality          text,                     -- '192' for kbps, '1080' for height, 'best'
  status           text not null default 'queued'
                   check (status in ('queued', 'fetching', 'downloading', 'processing',
                                     'done', 'error', 'cancelled')),
  -- live progress, written by the worker
  percent          double precision not null default 0,
  downloaded_bytes bigint not null default 0,
  total_bytes      bigint,
  speed_bps        double precision,
  eta_sec          integer,
  detail           text,
  cancel_requested boolean not null default false,
  -- result
  filename         text,
  size_bytes       bigint,
  storage_key      text,                     -- storage object key while the file exists
  expires_at       timestamptz,              -- when the file is deleted (row stays as history)
  error_code       text,
  error_message    text,
  created_at       timestamptz not null default now(),
  started_at       timestamptz,
  finished_at      timestamptz
);

create index if not exists downloads_user_created_idx
  on public.downloads (user_id, created_at desc);
create index if not exists downloads_client_created_idx
  on public.downloads (client_id, created_at desc);
create index if not exists downloads_status_idx on public.downloads (status);
create index if not exists downloads_created_idx on public.downloads (created_at desc);

comment on table public.downloads is 'One row per download job. video_id only, never the full URL.';

-- ---------------------------------------------------------------------------
-- events (activity log)
-- ---------------------------------------------------------------------------
create table if not exists public.events (
  id          bigint generated always as identity primary key,
  user_id     uuid references public.profiles (id) on delete set null,
  name        text not null,               -- signup, email_verified, signin, info_requested,
                                           -- download_started, download_completed,
                                           -- download_failed, quota_hit
  properties  jsonb not null default '{}'::jsonb,
  ip_hash     text,                        -- salted hash, never the raw IP
  user_agent  text,
  created_at  timestamptz not null default now()
);

create index if not exists events_name_created_idx on public.events (name, created_at desc);
create index if not exists events_user_created_idx on public.events (user_id, created_at desc);
create index if not exists events_created_idx on public.events (created_at desc);

comment on table public.events is 'Activity log. Raw rows are pruned after 90 days (see prune_old_events).';

-- Retention: call from a scheduled job (pg_cron on Pro, or a GitHub Action on free).
create or replace function public.prune_old_events(keep_days integer default 90)
returns integer language plpgsql security definer as $$
declare removed integer;
begin
  delete from public.events where created_at < now() - make_interval(days => keep_days);
  get diagnostics removed = row_count;
  return removed;
end;
$$;

-- ---------------------------------------------------------------------------
-- Quota helper: downloads started today by a user (UTC).
-- ---------------------------------------------------------------------------
create or replace function public.downloads_today(uid uuid)
returns integer language sql stable as $$
  select count(*)::integer
  from public.downloads
  where user_id = uid
    and created_at >= date_trunc('day', now() at time zone 'utc')
    and status <> 'cancelled';
$$;

-- ---------------------------------------------------------------------------
-- Admin views for the dashboard (Phase 5)
-- ---------------------------------------------------------------------------
create or replace view public.admin_signups_daily as
select
  date_trunc('day', u.created_at)::date            as day,
  count(*)                                          as signups,
  count(*) filter (where u.email_confirmed_at is not null) as verified,
  count(*) filter (where p.email_risk = 'disposable')      as disposable,
  count(*) filter (where p.email_risk = 'no_mx')           as no_mx
from auth.users u
left join public.profiles p on p.id = u.id
group by 1
order by 1 desc;

create or replace view public.admin_downloads_daily as
select
  date_trunc('day', created_at)::date as day,
  mode,
  format,
  count(*)                                    as total,
  count(*) filter (where status = 'done')     as done,
  count(*) filter (where status = 'error')    as failed,
  sum(size_bytes) filter (where status = 'done') as bytes_done
from public.downloads
group by 1, 2, 3
order by 1 desc, 2, 3;

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
alter table public.profiles  enable row level security;
alter table public.downloads enable row level security;
alter table public.events    enable row level security;

create or replace function public.is_admin()
returns boolean language sql stable security definer as $$
  select exists (
    select 1 from public.profiles where id = auth.uid() and role = 'admin'
  );
$$;

-- profiles: read/update own row; admins read all.
drop policy if exists "profiles: own read"   on public.profiles;
drop policy if exists "profiles: own update" on public.profiles;
drop policy if exists "profiles: admin read" on public.profiles;
create policy "profiles: own read"   on public.profiles for select using (id = auth.uid());
create policy "profiles: own update" on public.profiles for update using (id = auth.uid())
  with check (id = auth.uid() and role = (select role from public.profiles where id = auth.uid()));
create policy "profiles: admin read" on public.profiles for select using (public.is_admin());

-- downloads: users read their own; only the API (service role) writes.
drop policy if exists "downloads: own read"   on public.downloads;
drop policy if exists "downloads: admin read" on public.downloads;
create policy "downloads: own read"   on public.downloads for select using (user_id = auth.uid());
create policy "downloads: admin read" on public.downloads for select using (public.is_admin());

-- events: only admins read; only the API writes.
drop policy if exists "events: admin read" on public.events;
create policy "events: admin read" on public.events for select using (public.is_admin());

-- Views inherit the caller's rights on the underlying tables; restrict to admins explicitly.
revoke all on public.admin_signups_daily   from anon, authenticated;
revoke all on public.admin_downloads_daily from anon, authenticated;

-- ---------------------------------------------------------------------------
-- Make yourself admin after your first sign up:
--   update public.profiles set role = 'admin' where email = 'you@example.com';
-- ---------------------------------------------------------------------------
