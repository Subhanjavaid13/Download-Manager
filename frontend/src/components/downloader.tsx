"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  api,
  ApiError,
  type AudioBitrate,
  type AudioFormat,
  type Health,
  type Info,
  type Job,
  type JobCreate,
  type VideoHeight,
} from "@/lib/api";
import {
  extractUrl,
  formatBytes,
  formatDuration,
  formatEta,
  formatSpeed,
  looksLikeYouTube,
} from "@/lib/format";

type Mode = "audio" | "video";

type AudioOption = {
  id: string;
  label: string;
  sub: string;
  audio_format: AudioFormat;
  audio_bitrate: AudioBitrate;
};

const AUDIO_OPTIONS: AudioOption[] = [
  { id: "mp3-128", label: "MP3", sub: "128 kbps", audio_format: "mp3", audio_bitrate: 128 },
  { id: "mp3-192", label: "MP3", sub: "192 kbps", audio_format: "mp3", audio_bitrate: 192 },
  { id: "mp3-320", label: "MP3", sub: "320 kbps", audio_format: "mp3", audio_bitrate: 320 },
  { id: "m4a", label: "M4A", sub: "original AAC", audio_format: "m4a", audio_bitrate: 192 },
  { id: "opus", label: "Opus", sub: "original", audio_format: "opus", audio_bitrate: 192 },
];

const VIDEO_HEIGHTS: VideoHeight[] = [360, 480, 720, 1080, 1440, 2160];
const TERMINAL = new Set(["done", "error", "cancelled"]);

const STAGE_LABEL: Record<string, string> = {
  queued: "Waiting in queue",
  fetching: "Contacting YouTube",
  downloading: "Downloading",
  processing: "Converting",
  done: "Ready",
  error: "Failed",
  cancelled: "Cancelled",
};

export default function Downloader() {
  const params = useSearchParams();
  const shared = params.get("url") ?? params.get("text") ?? "";

  const [url, setUrl] = useState(() => extractUrl(shared));
  const [mode, setMode] = useState<Mode>("audio");
  const [audioChoice, setAudioChoice] = useState("mp3-192");
  const [height, setHeight] = useState<VideoHeight | null>(1080);

  const [health, setHealth] = useState<Health | null | "offline">(null);
  const [info, setInfo] = useState<Info | null>(null);
  const [infoError, setInfoError] = useState<string | null>(null);
  const [loadingInfo, setLoadingInfo] = useState(false);

  const [job, setJob] = useState<Job | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [recent, setRecent] = useState<Job[]>([]);

  const refreshRecent = useCallback(() => {
    api
      .listJobs(8)
      .then(setRecent)
      .catch(() => {
        // history is a convenience; the page works without it
      });
  }, []);

  // Backend status for the header dot, and this browser's recent downloads.
  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch(() => setHealth("offline"));
    refreshRecent();
  }, [refreshRecent]);

  // Changing the link invalidates the preview immediately.
  const updateUrl = useCallback((next: string) => {
    setUrl(next);
    setInfo(null);
    setInfoError(null);
  }, []);

  // Debounced metadata preview whenever the URL changes.
  useEffect(() => {
    const candidate = url.trim();
    if (!looksLikeYouTube(candidate)) return;

    const ctrl = new AbortController();
    const timer = setTimeout(async () => {
      setLoadingInfo(true);
      try {
        setInfo(await api.info(candidate, ctrl.signal));
      } catch (e) {
        if (ctrl.signal.aborted) return;
        setInfoError(e instanceof ApiError ? e.message : "Could not load video details.");
      } finally {
        if (!ctrl.signal.aborted) setLoadingInfo(false);
      }
    }, 450);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [url]);

  // Poll the running job once a second until it reaches a final state.
  const jobId = job?.id ?? null;
  const jobActive = !!job && !TERMINAL.has(job.status);
  useEffect(() => {
    if (!jobId || !jobActive) return;
    const timer = setInterval(async () => {
      try {
        const next = await api.getJob(jobId);
        setJob(next);
        if (TERMINAL.has(next.status)) refreshRecent();
      } catch {
        // keep the last known state; the next tick retries
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [jobId, jobActive, refreshRecent]);

  // Video presets that make sense for this video (never above what YouTube has).
  const maxAvailable = info?.available_heights.length
    ? Math.max(...info.available_heights)
    : null;
  const videoPresets = useMemo(
    () => (maxAvailable ? VIDEO_HEIGHTS.filter((h) => h <= maxAvailable) : VIDEO_HEIGHTS),
    [maxAvailable],
  );
  // If the user picked 1080p but this video tops out at 480p, use the best preset that exists.
  const effectiveHeight: VideoHeight | null =
    height !== null && maxAvailable && height > maxAvailable
      ? (videoPresets[videoPresets.length - 1] ?? null)
      : height;

  const pasteFromClipboard = useCallback(async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) updateUrl(extractUrl(text));
    } catch {
      // Clipboard permission denied; the user can paste manually.
    }
  }, [updateUrl]);

  const canSubmit = !!info && !loadingInfo && !submitting && !jobActive;

  const submit = useCallback(async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setJobError(null);
    const base = { url: url.trim(), mode };
    const body: JobCreate =
      mode === "audio"
        ? (() => {
            const opt = AUDIO_OPTIONS.find((o) => o.id === audioChoice) ?? AUDIO_OPTIONS[1];
            return { ...base, audio_format: opt.audio_format, audio_bitrate: opt.audio_bitrate };
          })()
        : { ...base, video_height: effectiveHeight };
    try {
      setJob(await api.createJob(body));
    } catch (e) {
      setJobError(e instanceof ApiError ? e.message : "Could not start the download.");
    } finally {
      setSubmitting(false);
    }
  }, [canSubmit, url, mode, audioChoice, effectiveHeight]);

  const cancel = useCallback(async () => {
    if (!jobId) return;
    try {
      await api.cancelJob(jobId);
    } catch {
      // The job may already have finished.
    }
  }, [jobId]);

  const reset = () => {
    setJob(null);
    setJobError(null);
  };

  const selectedLabel =
    mode === "audio"
      ? (() => {
          const o = AUDIO_OPTIONS.find((x) => x.id === audioChoice);
          return o ? `${o.label} · ${o.sub}` : "";
        })()
      : effectiveHeight
        ? `MP4 · ${effectiveHeight}p`
        : "MP4 · best";

  return (
    <>
      <main className="mx-auto w-full max-w-md flex-1 px-4 pb-32 pt-6 sm:max-w-lg sm:pt-10">
        <header className="mb-6 flex items-center justify-between">
          <h1 className="font-display text-2xl font-bold tracking-tight">Downloader Manager</h1>
          <HealthDot health={health} />
        </header>

        {/* URL input */}
        <section className="rounded-xl border border-line bg-surface p-3 shadow-sm">
          <label htmlFor="url" className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-muted">
            YouTube link
          </label>
          <div className="flex gap-2">
            <input
              id="url"
              type="url"
              inputMode="url"
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
              enterKeyHint="go"
              placeholder="https://youtu.be/…"
              value={url}
              onChange={(e) => updateUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              className="min-w-0 flex-1 rounded-lg border border-line bg-bg px-3 py-2.5 text-base text-ink placeholder:text-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30"
            />
            <button
              type="button"
              onClick={pasteFromClipboard}
              className="shrink-0 rounded-lg border border-line px-3 py-2.5 text-sm font-medium text-ink-2 hover:bg-bg focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
            >
              Paste
            </button>
          </div>

          <div className="mt-3 min-h-[4.5rem]">
            {loadingInfo && <PreviewSkeleton />}
            {!loadingInfo && info && <Preview info={info} />}
            {!loadingInfo && infoError && (
              <p className="rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">{infoError}</p>
            )}
            {!loadingInfo && !info && !infoError && (
              <p className="px-1 text-sm text-muted">
                Paste a video link. Details show up here before you download.
              </p>
            )}
          </div>
        </section>

        {/* Mode */}
        <section className="mt-6">
          <div
            role="radiogroup"
            aria-label="Download as"
            className="grid grid-cols-2 gap-1 rounded-xl border border-line bg-surface p-1"
          >
            <ModeButton active={mode === "audio"} onClick={() => setMode("audio")} tone="amber">
              Audio
            </ModeButton>
            <ModeButton active={mode === "video"} onClick={() => setMode("video")} tone="blue">
              Video
            </ModeButton>
          </div>
        </section>

        {/* Quality */}
        <section className="mt-4">
          <h2 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">Quality</h2>
          {mode === "audio" ? (
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
              {AUDIO_OPTIONS.map((o) => (
                <Chip
                  key={o.id}
                  active={audioChoice === o.id}
                  tone="amber"
                  onClick={() => setAudioChoice(o.id)}
                  label={o.label}
                  sub={o.sub}
                />
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-4 gap-2 sm:grid-cols-7">
              {videoPresets.map((h) => (
                <Chip
                  key={h}
                  active={effectiveHeight === h}
                  tone="blue"
                  onClick={() => setHeight(h)}
                  label={`${h}p`}
                  sub={h >= 1080 ? "HD" : h >= 720 ? "HD" : "SD"}
                />
              ))}
              <Chip
                active={effectiveHeight === null}
                tone="blue"
                onClick={() => setHeight(null)}
                label="Best"
                sub="available"
              />
            </div>
          )}
          {mode === "audio" && audioChoice === "mp3-320" && (
            <p className="mt-2 text-xs text-muted">
              YouTube&apos;s source audio is about 128 to 160 kbps. 320 kbps makes a bigger file, not a better one.
            </p>
          )}
        </section>

        {/* Job status */}
        {(job || jobError) && (
          <section className="mt-6">
            {jobError && (
              <p className="rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">{jobError}</p>
            )}
            {job && <JobCard job={job} onCancel={cancel} onReset={reset} />}
          </section>
        )}

        {recent.filter((r) => r.id !== job?.id).length > 0 && (
          <section className="mt-8">
            <h2 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">
              Recent on this device
            </h2>
            <ul className="divide-y divide-line-soft rounded-xl border border-line bg-surface">
              {recent
                .filter((r) => r.id !== job?.id)
                .slice(0, 6)
                .map((r) => (
                  <RecentRow key={r.id} job={r} />
                ))}
            </ul>
          </section>
        )}

        <footer className="mt-10 text-xs leading-relaxed text-muted">
          For personal use with content you have the right to download. Files are deleted from the
          server one hour after they finish.
        </footer>
      </main>

      {/* Sticky action bar (mobile) */}
      <div className="fixed inset-x-0 bottom-0 border-t border-line bg-surface/95 backdrop-blur supports-[backdrop-filter]:bg-surface/80">
        <div className="mx-auto flex w-full max-w-md items-center gap-3 px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:max-w-lg">
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">{selectedLabel}</div>
            <div className="truncate text-xs text-muted">
              {info ? info.title : "No video selected"}
            </div>
          </div>
          <button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            className={`shrink-0 rounded-lg px-5 py-3 text-sm font-semibold text-white transition focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-40 ${
              mode === "audio" ? "bg-amber focus-visible:ring-amber" : "bg-accent focus-visible:ring-accent"
            }`}
          >
            {submitting ? "Starting…" : jobActive ? "Working…" : "Download"}
          </button>
        </div>
      </div>
    </>
  );
}

/* ---------- pieces ---------- */

function HealthDot({ health }: { health: Health | null | "offline" }) {
  const state =
    health === null
      ? { color: "bg-muted", text: "Checking API" }
      : health === "offline"
        ? { color: "bg-danger", text: "API offline" }
        : !health.ffmpeg
          ? { color: "bg-amber", text: "FFmpeg missing" }
          : { color: "bg-ok", text: "Ready" };
  return (
    <span className="flex items-center gap-2 text-xs text-muted" title={state.text}>
      <span className={`h-2 w-2 rounded-full ${state.color}`} aria-hidden />
      <span className="sr-only sm:not-sr-only">{state.text}</span>
    </span>
  );
}

function Preview({ info }: { info: Info }) {
  return (
    <div className="flex gap-3">
      {info.thumbnail ? (
        // eslint-disable-next-line @next/next/no-img-element -- remote thumbnail, unoptimized on purpose
        <img
          src={info.thumbnail}
          alt=""
          className="h-16 w-28 shrink-0 rounded-md bg-line-soft object-cover"
        />
      ) : (
        <div className="h-16 w-28 shrink-0 rounded-md bg-line-soft" />
      )}
      <div className="min-w-0">
        <p className="line-clamp-2 text-sm font-medium leading-snug">{info.title}</p>
        <p className="mt-1 truncate text-xs text-muted">
          {info.channel ?? "Unknown channel"}
          {info.duration_sec != null && <> · {formatDuration(info.duration_sec)}</>}
          {info.available_heights.length > 0 && (
            <> · up to {Math.max(...info.available_heights)}p</>
          )}
        </p>
        {info.playlist_id && (
          <p className="mt-1 text-xs text-amber">
            Part of a playlist. Only this video will be downloaded.
          </p>
        )}
      </div>
    </div>
  );
}

function RecentRow({ job }: { job: Job }) {
  const tone = job.mode === "audio" ? "text-amber" : "text-accent";
  return (
    <li className="flex items-center gap-3 px-3 py-2.5">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{job.title ?? job.video_id}</p>
        <p className="truncate text-xs text-muted">
          <span className={`font-medium ${tone}`}>{job.label}</span>
          {" · "}
          {job.status === "done"
            ? job.file_available
              ? formatBytes(job.size_bytes)
              : "link expired"
            : (STAGE_LABEL[job.status] ?? job.status).toLowerCase()}
        </p>
      </div>
      {job.file_available ? (
        <a
          href={api.fileUrl(job.id)}
          download={job.filename ?? undefined}
          className="shrink-0 rounded-md border border-line px-2.5 py-1.5 text-xs font-medium text-ink-2 hover:bg-bg focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
        >
          Save
        </a>
      ) : (
        <StatusPill status={job.status} />
      )}
    </li>
  );
}

function PreviewSkeleton() {
  return (
    <div className="flex animate-pulse gap-3" aria-label="Loading video details">
      <div className="h-16 w-28 shrink-0 rounded-md bg-line-soft" />
      <div className="flex-1 space-y-2 pt-1">
        <div className="h-3.5 w-11/12 rounded bg-line-soft" />
        <div className="h-3.5 w-2/3 rounded bg-line-soft" />
        <div className="h-3 w-1/3 rounded bg-line-soft" />
      </div>
    </div>
  );
}

function ModeButton({
  active,
  onClick,
  tone,
  children,
}: {
  active: boolean;
  onClick: () => void;
  tone: "amber" | "blue";
  children: React.ReactNode;
}) {
  const on = tone === "amber" ? "bg-amber-soft text-amber" : "bg-accent-soft text-accent";
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onClick}
      className={`rounded-lg px-3 py-2.5 text-sm font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 ${
        active ? on : "text-ink-2 hover:bg-bg"
      }`}
    >
      {children}
    </button>
  );
}

function Chip({
  active,
  onClick,
  tone,
  label,
  sub,
}: {
  active: boolean;
  onClick: () => void;
  tone: "amber" | "blue";
  label: string;
  sub: string;
}) {
  const on =
    tone === "amber"
      ? "border-amber bg-amber-soft text-amber"
      : "border-accent bg-accent-soft text-accent";
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`flex flex-col items-center rounded-lg border px-2 py-2 text-center transition focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 ${
        active ? on : "border-line bg-surface text-ink-2 hover:bg-bg"
      }`}
    >
      <span className="text-sm font-semibold leading-tight">{label}</span>
      <span className="mt-0.5 text-[10px] leading-tight opacity-80">{sub}</span>
    </button>
  );
}

function JobCard({
  job,
  onCancel,
  onReset,
}: {
  job: Job;
  onCancel: () => void;
  onReset: () => void;
}) {
  const p = job.progress;
  const active = !TERMINAL.has(job.status);
  const indeterminate = active && job.status !== "downloading";
  const barTone = job.mode === "audio" ? "bg-amber" : "bg-accent";

  return (
    <div className="rounded-xl border border-line bg-surface p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wider text-muted">{job.label}</p>
          <p className="mt-0.5 truncate text-sm font-medium">
            {job.filename ?? STAGE_LABEL[job.status] ?? job.status}
          </p>
        </div>
        <StatusPill status={job.status} />
      </div>

      {active && (
        <>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-line-soft" role="progressbar" aria-valuenow={p.percent} aria-valuemin={0} aria-valuemax={100}>
            <div
              className={`h-full rounded-full ${barTone} transition-[width] duration-300 ${indeterminate ? "w-1/3 animate-pulse" : ""}`}
              style={indeterminate ? undefined : { width: `${p.percent}%` }}
            />
          </div>
          <div className="mt-2 flex justify-between font-mono text-xs tabular-nums text-muted">
            <span>
              {STAGE_LABEL[job.status]}
              {p.detail ? ` · ${p.detail}` : ""}
            </span>
            <span>
              {job.status === "downloading"
                ? [`${p.percent.toFixed(0)}%`, formatSpeed(p.speed_bps), formatEta(p.eta_sec)]
                    .filter(Boolean)
                    .join(" · ")
                : ""}
            </span>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="mt-3 text-sm font-medium text-danger hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-danger/40"
          >
            Cancel
          </button>
        </>
      )}

      {job.status === "done" && (
        <div className="mt-4">
          <div className="flex flex-wrap items-center gap-3">
            <a
              href={api.fileUrl(job.id)}
              download={job.filename ?? undefined}
              className="rounded-lg bg-ok px-4 py-2.5 text-sm font-semibold text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-ok/50"
            >
              Save file{job.size_bytes ? ` · ${formatBytes(job.size_bytes)}` : ""}
            </a>
            <CopyLinkButton url={api.fileUrl(job.id)} />
            <button type="button" onClick={onReset} className="text-sm font-medium text-ink-2 hover:underline">
              Download another
            </button>
          </div>
          {job.expires_at && (
            <p className="mt-2 text-xs text-muted">
              Link works until {formatClock(job.expires_at)}. After that, download again.
            </p>
          )}
        </div>
      )}

      {job.status === "error" && (
        <div className="mt-3">
          <p className="rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">
            {job.error?.message ?? "The download failed."}
          </p>
          <button type="button" onClick={onReset} className="mt-3 text-sm font-medium text-ink-2 hover:underline">
            Try again
          </button>
        </div>
      )}

      {job.status === "cancelled" && (
        <button type="button" onClick={onReset} className="mt-3 text-sm font-medium text-ink-2 hover:underline">
          Start over
        </button>
      )}
    </div>
  );
}

function CopyLinkButton({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard blocked; the Save button still works.
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      className="rounded-lg border border-line px-3 py-2.5 text-sm font-medium text-ink-2 hover:bg-bg focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
    >
      {copied ? "Copied" : "Copy link"}
    </button>
  );
}

function formatClock(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function StatusPill({ status }: { status: Job["status"] }) {
  const tone =
    status === "done"
      ? "bg-ok-soft text-ok"
      : status === "error"
        ? "bg-danger-soft text-danger"
        : status === "cancelled"
          ? "bg-line-soft text-muted"
          : "bg-accent-soft text-accent";
  return (
    <span className={`shrink-0 rounded-md px-2 py-1 font-mono text-[11px] font-medium uppercase tracking-wider ${tone}`}>
      {STAGE_LABEL[status] ?? status}
    </span>
  );
}
