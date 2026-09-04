"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { BottomDock } from "@/components/bottom-nav";
import { AppHeader } from "@/components/header";
import { InboxIcon } from "@/components/icons";
import { NotConfigured } from "@/components/not-configured";
import { Turnstile, TURNSTILE_SITE_KEY } from "@/components/turnstile";
import { Button, Card, Field, Notice, Page } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { getSupabase } from "@/lib/supabase";

export default function SignUpPage() {
  const router = useRouter();
  const { available, ready, user, config } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [resent, setResent] = useState(false);

  useEffect(() => {
    if (ready && user) router.replace("/");
  }, [ready, user, router]);

  const onToken = useCallback((t: string | null) => setToken(t), []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.signup({
        email: email.trim(),
        password,
        display_name: name.trim() || undefined,
        turnstile_token: token ?? undefined,
        redirect_to: `${window.location.origin}/auth/callback`,
      });
      if (res.session) {
        const sb = getSupabase();
        if (sb) await sb.auth.setSession(res.session);
        router.replace("/");
        return;
      }
      setSentTo(res.email);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the account.");
    } finally {
      setBusy(false);
    }
  };

  const resend = async () => {
    const sb = getSupabase();
    if (!sb || !sentTo) return;
    const { error: err } = await sb.auth.resend({
      type: "signup",
      email: sentTo,
      options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
    });
    if (err) setError(err.message);
    else setResent(true);
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

  if (sentTo) {
    return (
      <>
        <Page>
          <AppHeader />
          <Card>
            <div className="flex items-start gap-3">
              <span className="mt-0.5 shrink-0 text-accent">
                <InboxIcon className="h-6 w-6" />
              </span>
              <div className="min-w-0">
                <h1 className="font-display text-display">Check your inbox</h1>
                <p className="mt-2 text-sm text-ink-2">
                  We sent a verification link to <strong>{sentTo}</strong>. Tap it on this device to
                  finish signing up. Downloads unlock as soon as your email is verified.
                </p>
              </div>
            </div>
            <p className="mt-3 text-xs text-muted">
              Nothing there after a minute? Check spam, or resend below. The free email service
              allows only a few messages per hour.
            </p>
            {error && (
              <div className="mt-3">
                <Notice tone="error">{error}</Notice>
              </div>
            )}
            {resent && (
              <div className="mt-3">
                <Notice tone="ok">Sent again.</Notice>
              </div>
            )}
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <Button type="button" tone="secondary" onClick={resend} disabled={resent}>
                Resend email
              </Button>
              <Link href="/signin" className="text-sm font-semibold text-accent hover:underline">
                Go to sign in
              </Link>
            </div>
          </Card>
        </Page>
        <BottomDock />
      </>
    );
  }

  const signupOff = config && !config.signup_enabled;

  return (
    <>
      <Page>
        <AppHeader />
        <Card>
          <h1 className="font-display text-display">Create an account</h1>
          <p className="mt-1 text-sm text-muted">
            {config
              ? `${config.anon_daily_limit} downloads a day as a guest, 20 with an account.`
              : "Twenty downloads a day, and history on every device."}
          </p>
          {signupOff && (
            <div className="mt-3">
              <Notice tone="warn">Sign-up is not enabled on the server yet.</Notice>
            </div>
          )}
          <form onSubmit={submit} className="mt-5 space-y-4">
            <Field
              label="Name (optional)"
              name="name"
              autoComplete="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={80}
            />
            <Field
              label="Email"
              name="email"
              type="email"
              autoComplete="email"
              inputMode="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              hint="Temporary or throwaway addresses are not accepted."
            />
            <Field
              label="Password"
              name="password"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              hint="At least 8 characters."
            />
            <Turnstile onToken={onToken} />
            {error && <Notice tone="error">{error}</Notice>}
            <Button
              type="submit"
              busy={busy}
              busyLabel="Creating…"
              disabled={!!signupOff || (!!TURNSTILE_SITE_KEY && !token)}
              className="w-full"
            >
              Create account
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-ink-2">
            Already have one?{" "}
            <Link href="/signin" className="font-medium text-accent hover:underline">
              Sign in
            </Link>
          </p>
          <p className="mt-4 text-xs leading-relaxed text-muted">
            For personal use with content you have the right to download. Your files are kept
            until you delete them.
          </p>
        </Card>
      </Page>
      <BottomDock />
    </>
  );
}
