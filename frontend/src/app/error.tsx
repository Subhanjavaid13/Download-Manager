"use client";

import Link from "next/link";
import { useEffect } from "react";

import { BottomDock } from "@/components/bottom-nav";
import { AppHeader } from "@/components/header";
import { AlertIcon } from "@/components/icons";
import { Button, Card, Page } from "@/components/ui";

/** Last resort when a screen throws. Keeps the app frame and offers a way out. */
export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <>
      <Page>
        <AppHeader />
        <Card>
          <div className="flex items-start gap-3">
            <span className="mt-0.5 shrink-0 text-danger">
              <AlertIcon className="h-6 w-6" />
            </span>
            <div className="min-w-0">
              <h1 className="font-display text-display">Something went wrong</h1>
              <p className="mt-2 text-sm text-ink-2">
                This screen stopped before it finished loading. Reloading usually fixes it, and
                nothing you downloaded is affected.
              </p>
              {error.digest && (
                <p className="mt-2 font-mono text-data text-muted">Reference: {error.digest}</p>
              )}
            </div>
          </div>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <Button type="button" onClick={reset}>
              Reload this screen
            </Button>
            <Link
              href="/"
              className="text-sm font-semibold text-ink-2 underline-offset-2 hover:underline"
            >
              Back to downloads
            </Link>
          </div>
        </Card>
      </Page>
      <BottomDock />
    </>
  );
}
