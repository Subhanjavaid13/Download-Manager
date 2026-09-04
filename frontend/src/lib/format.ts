export function formatDuration(sec: number | null): string {
  if (sec == null) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}

/** The same duration, said out loud for a screen reader. */
export function spokenDuration(sec: number | null): string {
  if (sec == null) return "";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  const parts = [];
  if (m) parts.push(`${m} minute${m === 1 ? "" : "s"}`);
  if (s) parts.push(`${s} second${s === 1 ? "" : "s"}`);
  return parts.join(" ") || "0 seconds";
}

export function formatBytes(n: number | null | undefined): string {
  if (n == null) return "";
  if (n < 1024) return `${Math.round(n)} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function formatSpeed(bps: number | null | undefined): string {
  if (!bps) return "";
  return `${formatBytes(bps)}/s`;
}

export function formatEta(sec: number | null | undefined): string {
  if (sec == null) return "";
  if (sec < 60) return `${Math.round(sec)}s left`;
  return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s left`;
}

export function formatClock(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

/** "Today", "Yesterday", then a short date. Used to group the history list. */
export function formatDay(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((startOf(new Date()) - startOf(d)) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return d.toLocaleDateString(undefined, { weekday: "long" });
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(d.getFullYear() === new Date().getFullYear() ? {} : { year: "numeric" }),
  });
}

/** Pull the first URL out of shared text (the YouTube app shares "Title https://youtu.be/…"). */
export function extractUrl(text: string): string {
  const m = text.match(/https?:\/\/\S+/);
  return (m ? m[0] : text).trim();
}

export function looksLikeYouTube(s: string): boolean {
  return /(youtube\.com|youtu\.be)\//i.test(s);
}

export type Mode = "audio" | "video";

/**
 * What the link itself tells us about the mode. A YouTube Music link is a
 * song, so Audio is preselected; anything else is left to the user's last
 * choice. Returns null when the link says nothing either way.
 */
export function inferMode(url: string): Mode | null {
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (host === "music.youtube.com") return "audio";
  } catch {
    if (/(^|\/\/|\.)music\.youtube\.com\//i.test(url)) return "audio";
  }
  return null;
}

export type SharedLink = {
  /** The link to download, already trimmed out of any shared text. */
  url: string;
  /** Mode the link implies, or null when it implies nothing. */
  mode: Mode | null;
  /** True when the app was opened from another app's share sheet. */
  shared: boolean;
};

/**
 * Read the Android share target (and our own ?url= deep links).
 * The share sheet sends the link in `url`, or inside `text` with the title.
 */
export function parseSharedLink(params: {
  url?: string | null;
  text?: string | null;
  title?: string | null;
}): SharedLink | null {
  const raw = params.url ?? params.text ?? "";
  if (!raw.trim()) return null;
  const url = extractUrl(raw);
  if (!url) return null;
  return { url, mode: inferMode(url), shared: !!(params.text || params.title) };
}
