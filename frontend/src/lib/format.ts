export function formatDuration(sec: number | null): string {
  if (sec == null) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}

export function formatBytes(n: number | null | undefined): string {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
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

/** Pull the first URL out of shared text (the YouTube app shares "Title https://youtu.be/…"). */
export function extractUrl(text: string): string {
  const m = text.match(/https?:\/\/\S+/);
  return (m ? m[0] : text).trim();
}

export function looksLikeYouTube(s: string): boolean {
  return /(youtube\.com|youtu\.be)\//i.test(s);
}
