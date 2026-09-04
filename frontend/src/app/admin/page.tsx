"use client";

/**
 * `/admin` - the operator's page.
 *
 * **The guard here is a courtesy, not the lock.** The real check is
 * server-side: every `/api/v1/admin` route requires a Supabase token whose
 * profile row says `role = 'admin'` and answers 403 otherwise, so a determined
 * visitor who bypasses this component gets a page with no data in it. What this
 * component does is make that refusal quiet and quick - a non-admin is sent back
 * to the app rather than left staring at an error - and it treats the API's own
 * 403 as the authority, not the locally cached profile, so a role revoked a
 * minute ago still closes the door on the next load.
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { BottomDock } from "@/components/bottom-nav";
import { AppHeader } from "@/components/header";
import { NotConfigured } from "@/components/not-configured";
import { Button, Card, ErrorState, Page, Skeleton } from "@/components/ui";
import { adminApi, RANGES, type Overview, type RangeDays } from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

import { Dashboard } from "./dashboard";

export default function AdminPage() {
  const router = useRouter();
  const { available, ready, user } = useAuth();

  const [days, setDays] = useState<RangeDays>(7);
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  /** Bumped by the Refresh button to re-run the effect below without changing the range. */
  const [reloadKey, setReloadKey] = useState(0);

  const reload = useCallback(() => {
    setLoading(true);
    setReloadKey((k) => k + 1);
  }, []);

  // Not signed in at all: the sign-in screen, not a 403 page.
  useEffect(() => {
    if (ready && available && !user) router.replace("/signin");
  }, [ready, available, user, router]);

  // Signed in but refused by the API: back to the app, no explanation needed.
  useEffect(() => {
    if (forbidden) router.replace("/");
  }, [forbidden, router]);

  useEffect(() => {
    if (!ready || !user) return;
    const controller = new AbortController();
    let stopped = false;
    const run = async () => {
      try {
        const next = await adminApi.overview(days, controller.signal);
        if (stopped) return;
        setData(next);
        setError(null);
      } catch (err) {
        if (stopped) return;
        // 401 and 403 are not failures to retry: they are the answer.
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          setForbidden(true);
          return;
        }
        if (!(err instanceof DOMException && err.name === "AbortError")) {
          setError(err instanceof ApiError ? err.message : "Could not load the dashboard.");
        }
      } finally {
        if (!stopped) setLoading(false);
      }
    };
    void run();
    return () => {
      stopped = true;
      controller.abort();
    };
  }, [ready, user, days, reloadKey]);

  if (!available) {
    return (
      <>
        <Page>
          <AppHeader />
          <NotConfigured />
        </Page>
        <BottomDock />
      </>
    );
  }

  return (
    <>
      <Page>
        <AppHeader />
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="font-display text-display text-ink">Admin</h1>
            <p className="mt-0.5 text-sm text-muted">
              {data
                ? `${data.range.start} to ${data.range.end}, UTC`
                : "Sign-ups, activity and downloads"}
            </p>
          </div>
          {/* One filter row for the whole page: every card below re-renders
              against the same slice, so two cards can never disagree. */}
          <div
            role="group"
            aria-label="Date range"
            className="flex rounded-control border border-line bg-surface p-0.5"
          >
            {RANGES.map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={days === option}
                onClick={() => {
                  if (option === days) return;
                  setLoading(true);
                  setDays(option);
                }}
                className={`rounded-[0.45rem] px-3 py-1.5 text-xs font-semibold transition-ui ${
                  days === option
                    ? "bg-accent text-on-accent"
                    : "text-muted hover:bg-surface-2 hover:text-ink-2"
                }`}
              >
                {option}d
              </button>
            ))}
          </div>
        </div>

        {error && !data ? (
          <ErrorState
            title="Could not load the dashboard"
            body={error}
            onRetry={reload}
          />
        ) : !data ? (
          <DashboardSkeleton />
        ) : (
          <>
            {error && (
              <div className="mb-3">
                <ErrorState title="Refresh failed" body={error} onRetry={reload} />
              </div>
            )}
            {/* On a refetch the previous numbers stay on screen, dimmed. A
                skeleton here would throw the page away and jump the layout. */}
            <div className={loading ? "opacity-60 transition-opacity" : "transition-opacity"}>
              <Dashboard data={data} />
            </div>
            <div className="mt-4 flex items-center justify-between gap-3">
              <p className="text-xs text-muted">
                Read at {new Date(data.generated_at).toLocaleTimeString()} · straight from the
                database, not from PostHog.
              </p>
              <Button type="button" tone="secondary" busy={loading} onClick={reload}>
                Refresh
              </Button>
            </div>
          </>
        )}
      </Page>
      <BottomDock />
    </>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-4">
      <p className="sr-only" role="status">
        Loading the dashboard.
      </p>
      <Card>
        <div aria-hidden className="space-y-3">
          <Skeleton className="h-3 w-28" />
          <Skeleton className="h-12 w-40" />
          <Skeleton className="h-3 w-56" />
          <div className="grid grid-cols-2 gap-2 pt-2 sm:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-20 rounded-control" />
            ))}
          </div>
        </div>
      </Card>
      {[0, 1].map((i) => (
        <Card key={i}>
          <div aria-hidden className="space-y-3">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-32 w-full rounded-control" />
          </div>
        </Card>
      ))}
    </div>
  );
}
