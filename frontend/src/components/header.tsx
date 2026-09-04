"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/lib/auth";

export function AppHeader({ right }: { right?: React.ReactNode }) {
  const { available, ready, user, me } = useAuth();
  const pathname = usePathname();
  const initial = (me?.display_name ?? user?.email ?? "?").trim().charAt(0).toUpperCase();

  return (
    <header className="mb-6 flex items-center justify-between gap-3">
      <Link href="/" className="font-display text-2xl font-bold tracking-tight text-ink">
        Downloader Manager
      </Link>
      <div className="flex items-center gap-3">
        {right}
        {available && ready && (
          user ? (
            <Link
              href="/account"
              aria-label="Account"
              className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-semibold ${
                me && !me.email_verified ? "bg-amber-soft text-amber" : "bg-accent-soft text-accent"
              } ${pathname === "/account" ? "ring-2 ring-accent/40" : ""}`}
            >
              {initial}
            </Link>
          ) : (
            <Link
              href="/signin"
              className="rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink-2 hover:bg-surface"
            >
              Sign in
            </Link>
          )
        )}
      </div>
    </header>
  );
}

export function SubNav() {
  const pathname = usePathname();
  const { user } = useAuth();
  const items = [
    { href: "/", label: "Download" },
    { href: "/history", label: "History" },
    ...(user ? [{ href: "/account", label: "Account" }] : []),
  ];
  return (
    <nav className="mb-5 flex gap-1 rounded-lg border border-line bg-surface p-1 text-sm">
      {items.map((it) => (
        <Link
          key={it.href}
          href={it.href}
          className={`flex-1 rounded-md px-3 py-1.5 text-center font-medium ${
            pathname === it.href ? "bg-accent-soft text-accent" : "text-ink-2 hover:bg-bg"
          }`}
        >
          {it.label}
        </Link>
      ))}
    </nav>
  );
}
