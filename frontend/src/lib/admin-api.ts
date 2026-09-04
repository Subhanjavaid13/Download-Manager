/**
 * Typed client for `/api/v1/admin`.
 *
 * Separate from `lib/api.ts` on purpose: those endpoints are for everybody and
 * fail soft, these are for one person and must fail loudly. A 403 here is not an
 * error to retry, it is the answer - "you are not an admin" - and the dashboard
 * reads it as such.
 *
 * The token comes straight from Supabase rather than through the shared client's
 * provider, so this module works on a page loaded directly (a bookmarked
 * `/admin`) before anything else has had a chance to register one.
 */

import { API_URL, ApiError } from "@/lib/api";
import { getSupabase } from "@/lib/supabase";

// ---------------------------------------------------------------------------
// Wire format - mirrors backend/app/api/admin.py
// ---------------------------------------------------------------------------

export type AdminRange = { start: string; end: string; days: number };

export type SignupDay = {
  day: string;
  total: number;
  verified: number;
  unverified: number;
  flagged: number;
  disposable: number;
  no_mx: number;
  refused: number;
};

export type Signups = { daily: SignupDay[]; totals: Record<string, number> };

export type ActiveDay = { day: string; total: number; signed_in: number; guests: number };

export type ActiveUsers = {
  daily: ActiveDay[];
  dau: number;
  avg_dau: number;
  wau: number;
  wau_signed_in: number;
  mau: number;
  in_range: number;
  in_range_signed_in: number;
  stickiness: number;
};

export type DownloadDay = {
  day: string;
  total: number;
  done: number;
  failed: number;
  cancelled: number;
  audio: number;
  video: number;
};

export type FormatRow = {
  mode: "audio" | "video" | string;
  format: string;
  quality: string | null;
  total: number;
  done: number;
  bytes: number;
};

export type ErrorRow = { code: string; count: number };

export type Downloads = {
  daily: DownloadDay[];
  by_format: FormatRow[];
  errors: ErrorRow[];
  totals: {
    total: number;
    done: number;
    failed: number;
    cancelled: number;
    audio: number;
    video: number;
    from_playlists: number;
    bytes: number;
    success_rate: number | null;
  };
};

export type Timing = {
  samples: number;
  median_sec: number | null;
  p90_sec: number | null;
  fastest_sec: number | null;
  slowest_sec: number | null;
  mean_sec: number | null;
};

export type DomainRow = { domain: string; accounts: number; verified: number; flagged: number };

export type FlaggedAccount = {
  id: string;
  /** Already masked by the API: `j***@example.com`. */
  email: string;
  risk: string;
  verified: boolean;
  downloads: number;
  created_at: string | null;
};

export type Accounts = {
  domains: DomainRow[];
  flagged: FlaggedAccount[];
  totals: { accounts: number; verified: number; admins: number; flagged: number };
};

export type FunnelStep = {
  key: string;
  label: string;
  count: number;
  of_previous: number | null;
  of_start: number | null;
  note: string | null;
  eligible: number | null;
};

export type Funnels = { cohort: AdminRange; steps: FunnelStep[] };

export type Retention = {
  keep_days: number;
  events: number;
  oldest_event: string | null;
  /** Rows past the retention promise. Anything but 0 means the prune job stopped. */
  overdue: number;
};

export type Summary = {
  signups: number;
  verified_signups: number;
  refused_signups: number;
  active_users: number;
  active_signed_in: number;
  wau: number;
  downloads: number;
  downloads_done: number;
  downloads_failed: number;
  success_rate: number | null;
  bytes: number;
  median_sec: number | null;
  flagged_accounts: number;
};

export type Overview = {
  range: AdminRange;
  generated_at: string;
  summary: Summary;
  signups: Signups;
  active_users: ActiveUsers;
  downloads: Downloads;
  timing: Timing;
  accounts: Accounts;
  funnels: Funnels;
  retention: Retention;
};

// ---------------------------------------------------------------------------

async function adminRequest<T>(path: string, signal?: AbortSignal): Promise<T> {
  const headers = new Headers();
  try {
    const sb = getSupabase();
    const token = sb ? (await sb.auth.getSession()).data.session?.access_token : null;
    if (token) headers.set("Authorization", `Bearer ${token}`);
  } catch {
    // No session to read. The request goes out unauthenticated and the API
    // answers 401, which is the honest outcome.
  }

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { headers, signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "The server did not answer. Check your connection and try again.");
  }
  if (!res.ok) {
    let message = res.statusText || "Request failed";
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message);
  }
  return (await res.json()) as T;
}

/** The date windows the dashboard offers. Anything else is a hand-typed URL. */
export const RANGES = [7, 30, 90] as const;
export type RangeDays = (typeof RANGES)[number];

export const adminApi = {
  /**
   * One request for the whole page. The API also serves each section on its own
   * (`/signups`, `/downloads`, `/funnels`, ... - see the README), which is what a
   * drill-down or a script would use; the dashboard wants a single consistent
   * snapshot, so it asks for all of it at once.
   */
  overview: (days: RangeDays | number, signal?: AbortSignal) =>
    adminRequest<Overview>(`/api/v1/admin/overview?days=${days}`, signal),
};

// ---------------------------------------------------------------------------
// Formatting shared by the dashboard's cards
// ---------------------------------------------------------------------------

/** 1,284 · 12.9K · 3.4M - short enough to sit in a stat tile on a phone. */
export function compact(n: number): string {
  if (!Number.isFinite(n)) return "-";
  if (Math.abs(n) < 10_000) return n.toLocaleString("en-US");
  if (Math.abs(n) < 1_000_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")}K`;
  return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}

export function bytes(n: number): string {
  if (!n) return "0 MB";
  const mb = n / 1_048_576;
  if (mb < 1) return `${Math.round(n / 1024)} KB`;
  if (mb < 1024) return `${mb.toFixed(mb < 10 ? 1 : 0)} MB`;
  return `${(mb / 1024).toFixed(1)} GB`;
}

export function duration(sec: number | null): string {
  if (sec === null || !Number.isFinite(sec)) return "-";
  if (sec < 60) return `${sec.toFixed(sec < 10 ? 1 : 0)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return s ? `${m}m ${s}s` : `${m}m`;
}

export function percent(value: number | null, fallback = "-"): string {
  return value === null || !Number.isFinite(value) ? fallback : `${value}%`;
}

/** "Thu 4" for an axis; the full date stays in the tooltip and the table. */
export function shortDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", timeZone: "UTC" });
}

/** "8 Aug" - short enough to be a stat-tile value without overflowing it. */
export function shortDate(iso: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso.length > 10 ? iso : `${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}

export function longDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}
