"use client";

import Link from "next/link";
import type { ReactNode } from "react";

/** The app mark, same drawing as the installed icon. */
function Mark() {
  return (
    <span
      aria-hidden
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[0.55rem] bg-accent text-on-accent"
    >
      <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5">
        <path
          d="M12 4.5v9.5M8 11l4 4 4-4"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path d="M7 18.5h10" stroke="var(--amber)" strokeWidth="2.2" strokeLinecap="round" />
      </svg>
    </span>
  );
}

/**
 * The bar at the top of every screen: the app mark and name, plus an optional
 * status slot. Navigation lives in the bottom bar, within thumb reach.
 *
 * `asHeading` makes the app name the page's <h1>; screens with their own
 * title leave it off and render their own heading instead.
 */
export function AppHeader({ right, asHeading }: { right?: ReactNode; asHeading?: boolean }) {
  const name = (
    <Link href="/" className="flex items-center gap-2.5 rounded-control">
      <Mark />
      <span className="font-display text-lg font-bold tracking-tight text-ink">
        Downloader Manager
      </span>
    </Link>
  );

  return (
    <header className="mb-5 flex items-center justify-between gap-3">
      {asHeading ? <h1 className="min-w-0">{name}</h1> : name}
      {right}
    </header>
  );
}
