"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/header";
import { Card, Notice, Page } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { getSupabase } from "@/lib/supabase";

/**
 * Landing page for email verification and Google sign-in.
 * Supabase puts the session in the URL; the client picks it up and we go home.
 */
export default function AuthCallbackPage() {
  const router = useRouter();
  const { ready, user } = useAuth();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const search = new URLSearchParams(window.location.search);
    const description = hash.get("error_description") ?? search.get("error_description");
    if (description) {
      const message = description.replace(/\+/g, " ");
      queueMicrotask(() => setError(message));
      return;
    }
    // PKCE fallback (only if a code arrives; the implicit flow needs nothing here).
    const code = search.get("code");
    const sb = getSupabase();
    if (code && sb) {
      sb.auth.exchangeCodeForSession(code).then(({ error: err }) => {
        if (err) setError(err.message);
      });
    }
  }, []);

  useEffect(() => {
    if (ready && user) {
      const t = setTimeout(() => router.replace("/?verified=1"), 400);
      return () => clearTimeout(t);
    }
  }, [ready, user, router]);

  useEffect(() => {
    // Nothing arrived within a few seconds: the link was probably used already.
    if (!ready || user || error) return;
    const t = setTimeout(
      () => setError("This link is no longer valid. Sign in, or request a new one."),
      6000,
    );
    return () => clearTimeout(t);
  }, [ready, user, error]);

  return (
    <Page>
      <AppHeader />
      <Card>
        {error ? (
          <>
            <Notice tone="error">{error}</Notice>
            <Link href="/signin" className="mt-4 inline-block text-sm font-medium text-accent hover:underline">
              Go to sign in
            </Link>
          </>
        ) : (
          <>
            <h1 className="font-display text-xl font-semibold">Signing you in…</h1>
            <p className="mt-2 text-sm text-muted">One moment.</p>
          </>
        )}
      </Card>
    </Page>
  );
}
