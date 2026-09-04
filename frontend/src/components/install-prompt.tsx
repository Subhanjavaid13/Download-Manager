"use client";

import { useCallback, useEffect, useState } from "react";

import { CloseIcon, InstallIcon } from "@/components/icons";
import { dismiss, isDismissed } from "@/lib/prefs";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

const DISMISS_KEY = "install";

function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    // iOS Safari, added to the home screen
    (window.navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

/**
 * Offer to install the app.
 *
 * Chrome and Edge fire `beforeinstallprompt`; we keep the event and show a
 * card with a real Install button. iOS never fires it, so there we explain
 * the Share > Add to Home Screen route instead. Dismissing sticks, and an
 * app that is already installed never sees this at all.
 */
export function InstallPrompt() {
  const [kind, setKind] = useState<"none" | "prompt" | "ios">("none");
  const [event, setEvent] = useState<BeforeInstallPromptEvent | null>(null);

  useEffect(() => {
    if (isStandalone() || isDismissed(DISMISS_KEY)) return;

    const onPrompt = (e: Event) => {
      e.preventDefault();
      setEvent(e as BeforeInstallPromptEvent);
      setKind("prompt");
    };
    const onInstalled = () => {
      setKind("none");
      setEvent(null);
      dismiss(DISMISS_KEY);
    };

    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);

    // iOS has no install event, so it gets the manual instructions instead.
    if (/iphone|ipad|ipod/i.test(navigator.userAgent)) {
      queueMicrotask(() => setKind((current) => (current === "none" ? "ios" : current)));
    }

    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  const close = useCallback(() => {
    setKind("none");
    dismiss(DISMISS_KEY);
  }, []);

  const install = useCallback(async () => {
    if (!event) return;
    await event.prompt();
    const { outcome } = await event.userChoice;
    setEvent(null);
    setKind("none");
    if (outcome === "accepted") dismiss(DISMISS_KEY);
  }, [event]);

  if (kind === "none") return null;

  return (
    <div className="mb-4 flex animate-rise items-start gap-3 rounded-card border border-accent/25 bg-accent-soft px-3 py-3">
      <span className="mt-0.5 shrink-0 text-accent">
        <InstallIcon />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-ink">Add Downloader to your home screen</p>
        {kind === "prompt" ? (
          <>
            <p className="mt-0.5 text-sm text-ink-2">
              It opens full screen, and YouTube&apos;s Share menu can send links straight here.
            </p>
            <button
              type="button"
              onClick={install}
              className="tap mt-2 inline-flex items-center rounded-control bg-accent px-3.5 py-2 text-sm font-semibold text-on-accent transition-ui hover:opacity-90"
            >
              Install
            </button>
          </>
        ) : (
          <p className="mt-0.5 text-sm text-ink-2">
            Tap the Share button in Safari, then <strong>Add to Home Screen</strong>. It opens full
            screen after that.
          </p>
        )}
      </div>
      <button
        type="button"
        onClick={close}
        aria-label="Dismiss the install suggestion"
        className="tap -mr-1 -mt-1 flex w-9 shrink-0 items-center justify-center rounded-control text-muted transition-ui hover:text-ink-2"
      >
        <CloseIcon className="h-4 w-4" />
      </button>
    </div>
  );
}
