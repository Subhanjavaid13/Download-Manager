import Link from "next/link";

import { BottomDock } from "@/components/bottom-nav";
import { AppHeader } from "@/components/header";
import { Card, Page } from "@/components/ui";

export default function NotFound() {
  return (
    <>
      <Page>
        <AppHeader />
        <Card>
          <p className="font-mono text-label uppercase text-muted">Error 404</p>
          <h1 className="mt-1 font-display text-display">This page does not exist</h1>
          <p className="mt-2 text-sm text-ink-2">
            The link may be old, or it may have a typo. The download screen is one tap away.
          </p>
          <div className="mt-5 flex flex-wrap gap-4">
            <Link
              href="/"
              className="tap inline-flex items-center rounded-control bg-accent px-4 text-sm font-semibold text-on-accent"
            >
              Go to downloads
            </Link>
            <Link
              href="/history"
              className="tap inline-flex items-center text-sm font-semibold text-ink-2 underline-offset-2 hover:underline"
            >
              See my downloads
            </Link>
          </div>
        </Card>
      </Page>
      <BottomDock />
    </>
  );
}
