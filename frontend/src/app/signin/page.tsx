"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { AppHeader } from "@/components/header";
import { NotConfigured } from "@/components/not-configured";
import { Button, Card, Divider, Field, Notice, Page } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { getSupabase } from "@/lib/supabase";

export default function SignInPage() {
  const router = useRouter();
  const { available, ready, user } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (ready && user) router.replace("/");
  }, [ready, user, router]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const sb = getSupabase();
    if (!sb) return;
    setBusy(true);
    setError(null);
    const { error: err } = await sb.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (err) {
      setError(
        err.message === "Invalid login credentials"
          ? "Wrong email or password."
          : err.message === "Email not confirmed"
            ? "Verify your email first. Check your inbox for the link."
            : err.message,
      );
      return;
    }
    router.replace("/");
  };

  const google = async () => {
    const sb = getSupabase();
    if (!sb) return;
    setError(null);
    const { error: err } = await sb.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/auth/callback` },
    });
    if (err) setError(err.message.includes("not enabled") ? "Google sign-in is not enabled yet." : err.message);
  };

  return (
    <Page>
      <AppHeader />
      {!available ? (
        <NotConfigured />
      ) : (
        <Card>
          <h1 className="font-display text-xl font-semibold">Sign in</h1>
          <p className="mt-1 text-sm text-muted">Your history follows you to every device.</p>
          <form onSubmit={submit} className="mt-5 space-y-4">
            <Field
              label="Email"
              name="email"
              type="email"
              autoComplete="email"
              inputMode="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <Field
              label="Password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {error && <Notice tone="error">{error}</Notice>}
            <Button type="submit" busy={busy} className="w-full">
              Sign in
            </Button>
          </form>
          <div className="mt-3 flex justify-between text-sm">
            <Link href="/forgot" className="text-ink-2 hover:underline">
              Forgot password?
            </Link>
            <Link href="/signup" className="font-medium text-accent hover:underline">
              Create an account
            </Link>
          </div>
          <Divider label="or" />
          <Button type="button" tone="secondary" className="w-full" onClick={google}>
            Continue with Google
          </Button>
        </Card>
      )}
    </Page>
  );
}
