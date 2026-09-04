"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { BottomDock } from "@/components/bottom-nav";
import { AppHeader } from "@/components/header";
import { NotConfigured } from "@/components/not-configured";
import { Button, Card, Field, Notice, Page } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { getSupabase } from "@/lib/supabase";

/** Landing page of the password-reset email. Supabase signs the user in from the link. */
export default function ResetPage() {
  const router = useRouter();
  const { available, ready, user } = useAuth();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [mismatch, setMismatch] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (password !== confirm) {
      setMismatch("The two passwords do not match.");
      return;
    }
    setMismatch(undefined);
    const sb = getSupabase();
    if (!sb) return;
    setBusy(true);
    setError(null);
    const { error: err } = await sb.auth.updateUser({ password });
    setBusy(false);
    if (err) setError(err.message);
    else router.replace("/account?reset=1");
  };

  return (
    <>
      <Page>
        <AppHeader />
        {!available ? (
          <NotConfigured />
        ) : (
          <Card>
            <h1 className="font-display text-display">Choose a new password</h1>
            {ready && !user ? (
              <>
                <div className="mt-3">
                  <Notice tone="warn">
                    This link has expired or was already used. Request a new one from the sign-in
                    page.
                  </Notice>
                </div>
                <Link
                  href="/forgot"
                  className="mt-4 inline-block text-sm font-semibold text-accent hover:underline"
                >
                  Send me a new link
                </Link>
              </>
            ) : (
              <form onSubmit={submit} className="mt-5 space-y-4">
                <Field
                  label="New password"
                  name="password"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  hint="At least 8 characters."
                />
                <Field
                  label="Repeat password"
                  name="confirm"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={8}
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  error={mismatch}
                />
                {error && <Notice tone="error">{error}</Notice>}
                <Button
                  type="submit"
                  busy={busy}
                  busyLabel="Saving…"
                  disabled={!ready}
                  className="w-full"
                >
                  Save password
                </Button>
              </form>
            )}
          </Card>
        )}
      </Page>
      <BottomDock />
    </>
  );
}
