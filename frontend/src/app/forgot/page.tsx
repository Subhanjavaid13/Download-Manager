"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { AppHeader } from "@/components/header";
import { NotConfigured } from "@/components/not-configured";
import { Button, Card, Field, Notice, Page } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { getSupabase } from "@/lib/supabase";

export default function ForgotPage() {
  const { available } = useAuth();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const sb = getSupabase();
    if (!sb) return;
    setBusy(true);
    setError(null);
    const { error: err } = await sb.auth.resetPasswordForEmail(email.trim(), {
      redirectTo: `${window.location.origin}/auth/reset`,
    });
    setBusy(false);
    if (err) setError(err.message);
    else setSent(true);
  };

  return (
    <Page>
      <AppHeader />
      {!available ? (
        <NotConfigured />
      ) : (
        <Card>
          <h1 className="font-display text-xl font-semibold">Reset your password</h1>
          {sent ? (
            <>
              <p className="mt-2 text-sm text-ink-2">
                If an account exists for <strong>{email}</strong>, a reset link is on its way.
              </p>
              <Link href="/signin" className="mt-4 inline-block text-sm font-medium text-accent hover:underline">
                Back to sign in
              </Link>
            </>
          ) : (
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
              {error && <Notice tone="error">{error}</Notice>}
              <Button type="submit" busy={busy} className="w-full">
                Send reset link
              </Button>
              <p className="text-center text-sm">
                <Link href="/signin" className="text-ink-2 hover:underline">
                  Back to sign in
                </Link>
              </p>
            </form>
          )}
        </Card>
      )}
    </Page>
  );
}
