"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { BottomDock } from "@/components/bottom-nav";
import { AppHeader } from "@/components/header";
import { OfflineIcon } from "@/components/icons";
import { Button, Card, Page } from "@/components/ui";

/**
 * What the service worker shows when a page load fails with no connection.
 * It is precached, so it is always available even on the first offline visit.
 */
export default function OfflinePage() {
  const [back, setBack] = useState(false);

  useEffect(() => {
    const sync = () => setBack(navigator.onLine);
    sync();
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    return () => {
      window.removeEventListener("online", sync);
      window.removeEventListener("offline", sync);
    };
  }, []);

  return (
    <>
      <Page>
        <AppHeader />
        <Card>
          <div className="flex items-start gap-3">
            <span className="mt-0.5 shrink-0 text-amber">
              <OfflineIcon className="h-6 w-6" />
            </span>
            <div className="min-w-0">
              <h1 className="text-display font-display">You are offline</h1>
              <p className="mt-2 text-sm text-ink-2">
                Downloader Manager needs a connection to reach YouTube and to fetch your files.
                Nothing was lost: anything that finished earlier is still in your history once you
                are back.
              </p>
            </div>
          </div>

          <ul className="mt-4 space-y-1.5 text-sm text-muted">
            <li>Check Wi-Fi or mobile data, or turn off airplane mode.</li>
            <li>A download that was running keeps going on the server.</li>
            <li>Nothing is deleted while you are away. Your finished files are still there.</li>
          </ul>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <Button type="button" onClick={() => window.location.reload()}>
              Try again
            </Button>
            <Link
              href="/"
              className="text-sm font-semibold text-ink-2 underline-offset-2 hover:underline"
            >
              Back to downloads
            </Link>
          </div>

          <p className="mt-4 text-sm font-medium" role="status">
            {back ? (
              <span className="text-ok">The connection is back. Try again.</span>
            ) : (
              <span className="text-muted">Still no connection.</span>
            )}
          </p>
        </Card>
      </Page>
      <BottomDock />
    </>
  );
}
