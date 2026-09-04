"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AppHeader, SubNav } from "@/components/header";
import { NotConfigured } from "@/components/not-configured";
import { Button, Card, Notice, Page } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { getSupabase } from "@/lib/supabase";

export default function AccountPage() {
  return (
    <Suspense fallback={null}>
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
      <Page>
        <AppHeader />
        <NotConfigured />
      </Page>
    );
  }
  if (!ready || !user) return <Page><AppHeader /></Page>;

  const used = me?.downloads_today ?? 0;
  const quota = me?.daily_quota ?? 20;
  const pct = Math.min(100, Math.round((used / Math.max(quota, 1)) * 100));

  return (
    <Page>
      <AppHeader />
      <SubNav />
      {params.get("reset") && (
        <div className="mb-4"><Notice tone="ok">Password updated.</Notice></div>
      )}
      <Card>
        <h1 className="font-display text-xl font-semibold">
          {me?.display_name ?? user.email}
        </h1>
        <p className="mt-0.5 text-sm text-muted">{user.email}</p>

        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt className="text-xs uppercase tracking-wider text-muted">Email</dt>
            <dd className={me?.email_verified ? "font-medium text-ok" : "font-medium text-amber"}>
              {me?.email_verified ? "Verified" : "Not verified"}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wider text-muted">Plan</dt>
            <dd className="font-medium">{me?.role === "admin" ? "Admin" : "Free"}</dd>
          </div>
          <div className="col-span-2">
            <dt className="text-xs uppercase tracking-wider text-muted">Downloads today</dt>
            <dd className="mt-1">
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium tabular-nums">
                  {used} of {quota}
                </span>
                <span className="text-xs text-muted">resets at midnight UTC</span>
              </div>
              <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-line-soft">
                <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
              </div>
            </dd>
          </div>
        </dl>

        {me && !me.email_verified && (
          <div className="mt-4 space-y-2">
            <Notice tone="warn">
              Verify your email to start downloading. Tap the link we sent to {user.email}.
            </Notice>
            {resent ? (
              <Notice tone="ok">Verification email sent again.</Notice>
            ) : (
              <Button type="button" tone="secondary" onClick={resend}>
                Resend verification email
              </Button>
            )}
          </div>
        )}
        {error && <div className="mt-3"><Notice tone="error">{error}</Notice></div>}

        <div className="mt-6 flex flex-wrap gap-3">
          <Link href="/history" className="rounded-lg border border-line px-4 py-2.5 text-sm font-medium text-ink-2 hover:bg-bg">
            My downloads
          </Link>
          <Button type="button" tone="secondary" onClick={() => signOut().then(() => router.replace("/"))}>
            Sign out
          </Button>
        </div>
      </Card>

      <Card className="mt-4">
        <h2 className="text-sm font-semibold">Delete account</h2>
        <p className="mt-1 text-sm text-muted">
          Removes your account, download history, and any files still on the server.
        </p>
        <Button type="button" tone="danger" className="mt-3" busy={deleting} onClick={remove}>
          Delete my account
        </Button>
      </Card>
    </Page>
  );
}
