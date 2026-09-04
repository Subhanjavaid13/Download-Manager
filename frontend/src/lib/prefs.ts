import type { Mode } from "@/lib/format";

/**
 * What the user picked last time, kept on this device only.
 * Coming back to the app should feel like picking the phone back up, not
 * like filling in the same form again.
 */

const KEY = "dm.prefs";

export type Prefs = {
  mode: Mode;
  /** id of an entry in AUDIO_OPTIONS */
  audio: string;
  /** video height, or null for "best available" */
  height: number | null;
};

export const DEFAULT_PREFS: Prefs = { mode: "audio", audio: "mp3-192", height: 1080 };

export function loadPrefs(): Prefs {
  if (typeof window === "undefined") return DEFAULT_PREFS;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return DEFAULT_PREFS;
    const parsed = JSON.parse(raw) as Partial<Prefs>;
    return {
      mode: parsed.mode === "video" ? "video" : "audio",
      audio: typeof parsed.audio === "string" ? parsed.audio : DEFAULT_PREFS.audio,
      height:
        parsed.height === null || typeof parsed.height === "number"
          ? parsed.height
          : DEFAULT_PREFS.height,
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

export function savePrefs(prefs: Prefs): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(prefs));
  } catch {
    // Private mode or storage blocked. Preferences just do not stick.
  }
}

/** Remembers that a dismissible thing was dismissed (the install card). */
export function isDismissed(key: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(`dm.dismissed.${key}`) === "1";
  } catch {
    return false;
  }
}

export function dismiss(key: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(`dm.dismissed.${key}`, "1");
  } catch {
    // Nothing to do; the card comes back next time.
  }
}
