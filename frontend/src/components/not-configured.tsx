import Link from "next/link";

import { Card } from "@/components/ui";

export function NotConfigured() {
  return (
    <Card>
      <h1 className="font-display text-xl font-semibold">Accounts are not set up yet</h1>
      <p className="mt-2 text-sm text-ink-2">
        Add <code className="rounded bg-line-soft px-1">NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
        <code className="rounded bg-line-soft px-1">NEXT_PUBLIC_SUPABASE_ANON_KEY</code> to the
        frontend environment and restart. Downloads work without an account in the meantime.
      </p>
      <Link href="/" className="mt-4 inline-block text-sm font-medium text-accent hover:underline">
        Back to downloads
      </Link>
    </Card>
  );
}
