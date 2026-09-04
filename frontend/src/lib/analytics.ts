"use client";

/**
 * Product analytics (PostHog), and the rules that keep it harmless.
 *
 * Three properties this module guarantees, because an analytics library is the
 * last thing that should be able to break a download:
 *
 * 1. **Off unless asked for.** With `NEXT_PUBLIC_POSTHOG_KEY` unset - which is
 *    the default, and the whole of development and CI - every function here is a
 *    no-op and `posthog-js` is never even fetched. The import below is dynamic
 *    for exactly that reason: no key, no network request, no bundle weight.
 * 2. **Never throws.** Every call into the library sits inside a try/catch, and
 *    a failed load is remembered so it is not retried on every click. If PostHog
 *    is blocked, down, or eaten by an ad blocker, the app does not notice.
 * 3. **Never leaks.** The one thing this app must not send anywhere is what
 *    somebody downloaded, so `track()` strips URLs from properties before they
 *    leave (see `scrub`). Autocapture and session recording are off: they would
 *    hoover up the pasted link from the input field. People are identified by
 *    their Supabase user id and nothing else - no email address.
 *
 * The event names are the same ones the API writes into the `events` table, so
 * the two sources can be compared instead of argued with. That list is
 * `AnalyticsEvent`, and it is the single place either side is allowed to invent
 * a name.
 */

import type { PostHog } from "posthog-js";
import { usePathname } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";

import { useAuth } from "@/lib/auth";

/**
 * Every event name the backend writes to `events` (see
 * backend/app/services/accounts.py and backend/app/main.py). Client and server
 * must agree, so adding one here means adding it there too.
 */
export type AnalyticsEvent =
  | "signup"
  | "signup_rejected"
  | "signin"
  | "signout"
  | "download_started"
  | "download_completed"
  | "download_failed"
  | "download_cancelled"
  | "playlist_finished"
  | "quota_hit"
  | "account_deleted";

export type AnalyticsProps = Record<string, string | number | boolean | null | undefined>;

const KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY;
const HOST = process.env.NEXT_PUBLIC_POSTHOG_HOST ?? "https://us.i.posthog.com";

/** True only when a key is configured. Everything below checks this first. */
export const analyticsEnabled = Boolean(KEY);

type Task = (ph: PostHog) => void;

let client: PostHog | null = null;
let loading: Promise<void> | null = null;
let broken = false;
/** Calls made before the library finished loading. Bounded: a page that never
 *  loads PostHog must not grow an unbounded array of closures. */
const pending: Task[] = [];
const MAX_PENDING = 50;

async function load(): Promise<void> {
  if (client || broken) return;
  loading ??= (async () => {
    try {
      const mod = await import("posthog-js");
      const ph = mod.default;
      ph.init(KEY as string, {
        api_host: HOST,
        // Pageviews are sent by hand below, on the App Router's navigations,
        // which the library's own listener does not see reliably.
        capture_pageview: false,
        capture_pageleave: true,
        // Both off on purpose: this app's main input is a YouTube link, and
        // autocapture and replay would both record it.
        autocapture: false,
        disable_session_recording: true,
        persistence: "localStorage+cookie",
      });
      client = ph;
      for (const task of pending.splice(0)) {
        try {
          task(ph);
        } catch {
          /* one bad event must not stop the rest */
        }
      }
    } catch {
      // Blocked, offline, or the CDN is down. Give up quietly and for good.
      broken = true;
      pending.length = 0;
    }
  })();
  return loading;
}

function run(task: Task): void {
  if (!analyticsEnabled || broken || typeof window === "undefined") return;
  if (client) {
    try {
      task(client);
    } catch {
      /* analytics never breaks a request */
    }
    return;
  }
  if (pending.length < MAX_PENDING) pending.push(task);
  void load();
}

const URLISH = /^\s*[a-z][a-z0-9+.-]*:\/\//i;
const FORBIDDEN_KEYS = /^(url|link|href|webpage_url|query|q|title|email)$/i;

/**
 * Drop anything that could carry what a person actually watched.
 *
 * A video id is fine (it is what the database stores too); a full URL is not,
 * because it arrives with tracking parameters attached and because "the list of
 * links this person pasted" is the one dataset this project promises not to
 * hand to a third party. Titles and email addresses go the same way.
 */
export function scrub(props: AnalyticsProps | undefined): AnalyticsProps {
  const out: AnalyticsProps = {};
  for (const [key, value] of Object.entries(props ?? {})) {
    if (value === undefined) continue;
    if (FORBIDDEN_KEYS.test(key)) continue;
    if (typeof value === "string" && (URLISH.test(value) || value.includes("@"))) continue;
    out[key] = value;
  }
  return out;
}

/** Record an event. Same name the API writes for the same thing. */
export function track(event: AnalyticsEvent, props?: AnalyticsProps): void {
  const clean = scrub(props);
  run((ph) => ph.capture(event, clean));
}

/** Tie this browser to a Supabase user id. No email, no name. */
export function identify(userId: string, props?: AnalyticsProps): void {
  const clean = scrub(props);
  run((ph) => ph.identify(userId, clean));
}

/** Forget the person on sign-out, so the next user is not merged into them. */
export function resetIdentity(): void {
  run((ph) => ph.reset());
}

export function pageview(path: string): void {
  run((ph) => ph.capture("$pageview", { $current_url: path }));
}

/**
 * Mounted once in the root layout, inside `AuthProvider`.
 *
 * It does the two things that cannot be done from a component that does not
 * exist yet: follows the session so the person is identified after sign-in and
 * forgotten after sign-out, and sends a pageview on every App Router
 * navigation. Product events (`download_started` and friends) are `track()`
 * calls from the screens that cause them.
 *
 * It renders its children untouched and, without a key, does nothing at all.
 */
export function AnalyticsProvider({ children }: { children: ReactNode }): ReactNode {
  const pathname = usePathname();
  const { user } = useAuth();
  const lastIdentity = useRef<string | null>(null);

  useEffect(() => {
    if (!analyticsEnabled) return;
    const id = user?.id ?? null;
    if (id === lastIdentity.current) return;
    lastIdentity.current = id;
    if (id) identify(id, { email_verified: Boolean(user?.email_confirmed_at) });
    else resetIdentity();
  }, [user]);

  useEffect(() => {
    if (!analyticsEnabled || !pathname) return;
    pageview(pathname);
  }, [pathname]);

  return children;
}
