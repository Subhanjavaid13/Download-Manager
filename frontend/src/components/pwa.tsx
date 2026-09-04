"use client";

import { useEffect, useState } from "react";

import { OfflineIcon } from "@/components/icons";

/**
 * Registers the service worker that keeps the offline page available.
 * Development is left alone: a cached shell there only hides your changes.
 */
export function ServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    if (!("serviceWorker" in navigator)) return;
    const register = () => {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {
        // No service worker means no offline page. Everything else still works.
      });
    };
    if (document.readyState === "complete") register();
    else {
      window.addEventListener("load", register, { once: true });
      return () => window.removeEventListener("load", register);
    }
  }, []);

  return null;
}

/**
 * A strip at the top of the app while the browser reports no connection.
 * It sits in the page flow rather than over it, so it can never cover a
 * control, and it announces itself politely.
 */
export function ConnectionBanner() {
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    const sync = () => setOffline(!navigator.onLine);
    sync();
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    return () => {
      window.removeEventListener("online", sync);
      window.removeEventListener("offline", sync);
    };
  }, []);

  if (!offline) return null;
  return (
    <p
      role="status"
      className="flex items-center justify-center gap-2 bg-amber-soft px-gutter py-2 text-sm font-medium text-amber"
    >
      <OfflineIcon className="h-4 w-4" />
      No connection. Downloads resume when you are back online.
    </p>
  );
}
