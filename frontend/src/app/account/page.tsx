"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { BottomDock } from "@/components/bottom-nav";
import { AppHeader } from "@/components/header";
import { NotConfigured } from "@/components/not-configured";
import { Button, Card, Notice, Page, Skeleton } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { getSupabase } from "@/lib/supabase";

export default function AccountPage() {
  return (
    <Suspense fallback={<AccountSkeleton />}>
      <Account />
    </Suspense>
  );
}

function Account() {
  const router = useRouter();
  const params = useSearchParams();
  const { available, ready, user, me, refreshMe, signOut } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [resent, setResent] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    if (ready && !user) router.replace("/signin");
  }, [ready, user, router]);

  useEffect(() => {
    if (user) void refreshMe();
  }, [user, refreshMe]);

  const resend = async () => {
    const sb = getSupabase();
    if (!sb || !user?.email) return;
    const { error: err } = await sb.auth.resend({
      type: "signup",
      email: user.email,
      options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
    });
    if (err) setError(err.message);
    else setResent(true);
  };

  const remove = async () => {
    if (!window.confirm("Delete your account, history, and files? This cannot be undone.")) return;
    setDeleting(true);
    setError(null);
    try {
      await api.deleteAccount();
      await signOut();
      router.replace("/?deleted=1");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete the account.");
      setDeleting(false);
    }
  };

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
  if (!ready || !user) return <AccountSkeleton />;

  const used = me?.downloads_today ?? 0;
  const quota = me?.daily_quota ?? 20;
  const left = Math.max(0, quota - used);
  const pct = Math.min(100, Math.round((used / Math.max(quota, 1)) * 100));

  return (
    <>
      <Page>
        <AppHeader />
        <h1 className="sr-only">Your account</h1>
        {params.get("reset") && (
          <div className="mb-4">
            <Notice tone="ok">Password updated.</Notice>
          </div>
        )}

        <Card>
          <div className="flex items-center gap-3">
            <span
              aria-hidden
              className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-full font-display text-lg font-bold ${
                me && !me.email_verified
                  ? "bg-amber-soft text-amber"
                  : "bg-accent-soft text-accent"
              }`}
            >
              {(me?.display_name ?? user.email ?? "?").trim().charAt(0).toUpperCase()}
            </span>
            <div className="min-w-0">
              <p className="truncate font-display text-title font-semibold">
                {me?.display_name ?? user.email}
              </p>
              <p className="truncate text-sm text-muted">{user.email}</p>
            </div>
          </div>

          <dl className="mt-5 grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-label uppercase text-muted">Email</dt>
              <dd className={me?.email_verified ? "font-medium text-ok" : "font-medium text-amber"}>
                {me ? (me.email_verified ? "Verified" : "Not verified") : "…"}
              </dd>
            </div>
            <div>
              <dt className="text-label uppercase text-muted">Plan</dt>
              <dd className="font-medium">{me?.role === "admin" ? "Admin" : "Free"}</dd>
            </div>
            <div className="col-span-2">
              <dt className="text-label uppercase text-muted">Downloads today</dt>
              <dd className="mt-1.5">
                <div className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="font-medium tabular-nums">
                    {used} of {quota} used
                  </span>
                  <span className="text-xs text-muted">
                    {left} left · resets at midnight UTC
                  </span>
                </div>
                <div
                  className="mt-1.5 h-2 overflow-hidden rounded-full bg-surface-2"
                  role="progressbar"
                  aria-label="Daily download quota used"
                  aria-valuenow={used}
                  aria-valuemin={0}
                  aria-valuemax={quota}
                  aria-valuetext={`${used} of ${quota} downloads used today`}
                >
                  <div
                    className={`h-full rounded-full transition-[width] duration-300 ease-soft ${
                      pct >= 100 ? "bg-danger" : pct >= 80 ? "bg-amber" : "bg-accent"
                    }`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </dd>
            </div>
          </dl>

          {me && !me.email_verified && (
            <div className="mt-5 space-y-2">
              <Notice tone="warn">
                Verify your email to start downloading. Tap the link we sent to {user.email}.
              </Notice>
              {resent ? (
                <Notice tone="ok">Verification email sent again. Check spam too.</Notice>
              ) : (
                <Button type="button" tone="secondary" onClick={resend}>
                  Resend verification email
                </Button>
              )}
            </div>
          )}
          {error && (
            <div className="mt-3">
              <Notice tone="error">{error}</Notice>
            </div>
          )}

          <div className="mt-6 flex flex-wrap gap-3">
            <Link
              href="/history"
              className="tap inline-flex items-center rounded-control border border-line px-4 text-sm font-semibold text-ink-2 transition-ui hover:bg-surface-2"
            >
              My downloads
            </Link>
            {/* The dashboard is otherwise reachable only by typing the URL. */}
            {me?.role === "admin" && (
              <Link
                href="/admin"
                className="tap inline-flex items-center rounded-control border border-line px-4 text-sm font-semibold text-ink-2 transition-ui hover:bg-surface-2"
              >
                Dashboard
              </Link>
            )}
            <Button
              type="button"
              tone="secondary"
              busy={signingOut}
              busyLabel="Signing out…"
              onClick={() => {
                setSigningOut(true);
                void signOut().then(() => router.replace("/"));
              }}
            >
              Sign out
            </Button>
          </div>
        </Card>

        <Card className="mt-4">
          <h2 className="text-sm font-semibold">Delete account</h2>
          <p className="mt-1 text-sm text-muted">
            Removes your account, download history, and any files still on the server. There is no
            undo.
          </p>
          <Button
            type="button"
            tone="danger"
            className="mt-3"
            busy={deleting}
            busyLabel="Deleting…"
            onClick={remove}
          >
            Delete my account
          </Button>
        </Card>
      </Page>
      <BottomDock />
    </>
  );
}

function AccountSkeleton() {
  return (
    <>
      <Page>
        <AppHeader />
        <p className="sr-only" role="status">
          Loading your account.
        </p>
        <Card>
          <div aria-hidden className="flex items-center gap-3">
            <Skeleton className="h-12 w-12 rounded-full" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          </div>
          <div aria-hidden className="mt-6 space-y-3">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-2 w-full rounded-full" />
            <Skeleton className="h-11 w-40 rounded-control" />
          </div>
        </Card>
      </Page>
      <BottomDock />
    </>
  );
}
