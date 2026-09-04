import Link from "next/link";

import { Card } from "@/components/ui";

export function NotConfigured() {
  return (
    <Card>
      <h1 className="font-display text-display">Accounts are not set up yet</h1>
      <p className="mt-2 text-sm text-ink-2">
        This copy of the app has no Supabase keys, so there is nothing to sign in to. Downloads work
        without an account, and this device keeps its own history.
      </p>
      <p className="mt-3 text-sm text-muted">
        To turn accounts on, add{" "}
        <code className="rounded bg-surface-2 px-1 font-mono text-data">
          NEXT_PUBLIC_SUPABASE_URL
        </code>{" "}
        and{" "}
        <code className="rounded bg-surface-2 px-1 font-mono text-data">
          NEXT_PUBLIC_SUPABASE_ANON_KEY
        </code>{" "}
        to the frontend environment and restart.
      </p>
      <Link
        href="/"
        className="tap mt-4 inline-flex items-center rounded-control bg-accent px-4 text-sm font-semibold text-on-accent"
      >
        Back to downloads
      </Link>
    </Card>
  );
}
