"use client";

import { useState } from "react";

import { AudioIcon, CheckIcon, VideoIcon } from "@/components/icons";
import { Notice, Skeleton } from "@/components/ui";
import { api, type Info, type Job, type Playlist, type PlaylistStatus } from "@/lib/api";
import { formatBytes, formatDuration, formatEta } from "@/lib/format";

/** One wording for a download's stage, shared by the single job and playlist items. */
export const STAGE_LABEL: Record<string, string> = {
  queued: "Waiting in queue",
  fetching: "Contacting YouTube",
  downloading: "Downloading",
  processing: "Converting",
  done: "Ready",
  error: "Failed",
  cancelled: "Cancelled",
};

const PLAYLIST_STATUS: Record<PlaylistStatus, { label: string; tone: string }> = {
  queued: { label: "Waiting", tone: "bg-accent-soft text-accent" },
  running: { label: "Downloading", tone: "bg-accent-soft text-accent" },
  done: { label: "All done", tone: "bg-ok-soft text-ok" },
  partial: { label: "Partly done", tone: "bg-amber-soft text-amber" },
  error: { label: "Failed", tone: "bg-danger-soft text-danger" },
  cancelled: { label: "Cancelled", tone: "bg-surface-2 text-muted" },
};

const ITEM_RUNNING = new Set(["fetching", "downloading", "processing"]);

export const PLAYLIST_ACTIVE = new Set<PlaylistStatus>(["queued", "running"]);

/**
 * Today's allowance, when the app knows it. Null while auth is off entirely.
 * `used` is null for a guest: the API only reports a running total for an
 * account, so we state the limit without pretending to know what is left.
 */
export type Allowance = { used: number | null; limit: number; guest: boolean } | null;

/* ------------------------------------------------------------------ preview */

/**
 * The choice, when a link carries both a video id and a list id. Pasting
 * `watch?v=...&list=...` is the common case and the two readings are genuinely
 * different, so we ask instead of guessing.
 */
export function PlaylistTargetChoice({
  target,
  onChange,
  count,
}: {
  target: "video" | "playlist";
  onChange: (t: "video" | "playlist") => void;
  count: number | null;
}) {
  const options = [
    { id: "video" as const, label: "This video", hint: "One file" },
    {
      id: "playlist" as const,
      label: "Whole playlist",
      hint: count ? `${count} files` : "Every video",
    },
  ];
  return (
    <div
      role="radiogroup"
      aria-label="Download this video or the whole playlist"
      className="grid grid-cols-2 gap-1 rounded-card border border-line bg-surface p-1"
    >
      {options.map((o) => {
        const active = target === o.id;
        return (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(o.id)}
            onKeyDown={(e) => {
              if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                e.preventDefault();
                onChange(o.id === "video" ? "playlist" : "video");
              }
            }}
            className={`tap flex flex-col items-center justify-center gap-0.5 rounded-control px-3 py-2 transition-ui ${
              active ? "bg-accent-soft text-accent" : "text-ink-2 hover:bg-surface-2"
            }`}
          >
            <span className="text-sm font-semibold">{o.label}</span>
            <span className="text-[11px] opacity-80">{o.hint}</span>
          </button>
        );
      })}
    </div>
  );
}

/** The playlist card shown before anything is downloaded. */
export function PlaylistPreview({
  info,
  allowance,
  loading,
}: {
  info: Info | null;
  allowance: Allowance;
  loading?: boolean;
}) {
  if (loading || !info) return <PlaylistPreviewSkeleton />;

  const count = info.playlist_count ?? info.items?.length ?? 0;
  const cap = info.playlist_limit ?? null;
  const overCap = !!info.playlist_truncated;
  const remaining =
    allowance && allowance.used !== null ? Math.max(allowance.limit - allowance.used, 0) : null;
  const short = remaining !== null && count > remaining;

  return (
    <div className="animate-rise">
      <div className="flex gap-3">
        <div className="relative shrink-0">
          <Thumb src={info.thumbnail} />
          <span className="absolute bottom-1 right-1 rounded bg-ink/80 px-1.5 py-0.5 font-mono text-[10px] font-medium text-bg">
            {count}
          </span>
        </div>
        <div className="min-w-0">
          <p className="text-label uppercase text-accent">Playlist</p>
          <p className="line-clamp-2 text-sm font-semibold leading-snug">{info.title}</p>
          <p className="mt-1 truncate text-xs text-muted">
            {info.channel ?? "Unknown channel"}
            {" · "}
            {count} videos
            {info.duration_sec != null && <> · {formatDuration(info.duration_sec)} in total</>}
          </p>
        </div>
      </div>

      {overCap && cap ? (
        <Notice tone="error" className="mt-3">
          This playlist has more than {cap} videos, which is the most this server takes at once.
          Open it on YouTube and download it in batches of {cap} or fewer.
        </Notice>
      ) : (
        <div className="mt-3 rounded-control bg-surface-2 px-3 py-2.5">
          <p className="text-xs font-semibold text-ink-2">What happens next</p>
          <ul className="mt-1 space-y-0.5 text-xs text-muted">
            <li>
              Each video becomes its own file, downloaded one after another. Save each one as soon
              as it is ready.
            </li>
            <li>
              {remaining !== null
                ? `This uses ${count} of your ${allowance?.limit} downloads for today, and you have ${remaining} left.`
                : allowance
                  ? `Every video counts on its own, so this uses ${count} of the ${allowance.limit} downloads a guest gets each day.`
                  : `All ${count} videos count separately against the daily download limit.`}
            </li>
            {cap && <li>The most this server takes in one go is {cap} videos.</li>}
          </ul>
        </div>
      )}

      {short && !overCap && (
        <Notice tone="warn" className="mt-2">
          {allowance?.guest
            ? `You have ${remaining} left today, so this playlist will be refused. Sign in for a bigger daily allowance, or pick a shorter playlist.`
            : `You have ${remaining} left today, so this playlist will be refused. Try again tomorrow, or pick a shorter playlist.`}
        </Notice>
      )}
    </div>
  );
}

function PlaylistPreviewSkeleton() {
  return (
    <div aria-hidden>
      <div className="flex gap-3">
        <Skeleton className="h-16 w-28 shrink-0 rounded-md" />
        <div className="flex-1 space-y-2 pt-1">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-3.5 w-11/12" />
          <Skeleton className="h-3 w-2/5" />
        </div>
      </div>
      <Skeleton className="mt-3 h-16 w-full rounded-control" />
    </div>
  );
}

/* --------------------------------------------------------------- the run */

/** A playlist that is running or has finished: overall progress, then every item. */
export function PlaylistCard({
  playlist,
  onCancel,
  onStartOver,
}: {
  playlist: Playlist;
  onCancel: () => void;
  onStartOver: () => void;
}) {
  const active = PLAYLIST_ACTIVE.has(playlist.status);
  const state = PLAYLIST_STATUS[playlist.status];
  const items = playlist.items ?? [];
  const ready = items.filter((i) => i.file_available);
  const barTone = playlist.mode === "audio" ? "bg-amber" : "bg-accent";

  return (
    <div className="animate-rise rounded-card border border-line bg-surface p-card shadow-card">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-label uppercase text-muted">Playlist · {playlist.label}</p>
          <p className="mt-0.5 truncate text-sm font-semibold">
            {playlist.title ?? "Playlist download"}
          </p>
        </div>
        <span
          className={`shrink-0 rounded-md px-2 py-1 font-mono text-label uppercase ${state.tone}`}
        >
          {state.label}
        </span>
      </div>

      <div
        className="mt-3 h-2 overflow-hidden rounded-full bg-surface-2"
        role="progressbar"
        aria-label="Playlist progress"
        aria-valuenow={Math.round(playlist.percent)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuetext={`${playlist.completed_items} of ${playlist.total_items} videos done`}
      >
        <div
          className={`h-full rounded-full transition-[width] duration-300 ease-soft ${barTone}`}
          style={{ width: `${Math.max(playlist.percent, 1)}%` }}
        />
      </div>
      <p className="mt-2 font-mono text-data tabular-nums text-muted">
        {playlist.completed_items} of {playlist.total_items} done
        {playlist.failed_items > 0 && ` · ${playlist.failed_items} failed`}
        {playlist.cancelled_items > 0 && ` · ${playlist.cancelled_items} cancelled`}
      </p>

      {playlist.error && (
        <p className="mt-2 rounded-control bg-danger-soft px-3 py-2 text-sm text-danger">
          {playlist.error.message}
        </p>
      )}

      {active ? (
        <button
          type="button"
          onClick={onCancel}
          className="tap mt-1 text-sm font-semibold text-danger underline-offset-2 hover:underline"
        >
          Stop the whole playlist
        </button>
      ) : (
        <div className="mt-2 flex flex-wrap items-center gap-3">
          {ready.length > 0 && (
            <p className="text-xs text-muted">{ready.length} files ready to save below.</p>
          )}
          <button
            type="button"
            onClick={onStartOver}
            className="tap text-sm font-semibold text-ink-2 underline-offset-2 hover:underline"
          >
            Download something else
          </button>
        </div>
      )}

      {items.length > 0 && (
        <ul className="mt-3 divide-y divide-line-soft overflow-hidden rounded-control border border-line">
          {items.map((item, i) => (
            <PlaylistItemRow key={item.id} job={item} index={i + 1} />
          ))}
        </ul>
      )}
    </div>
  );
}

/** One video of a playlist, with its own state and its own save button. */
export function PlaylistItemRow({ job, index }: { job: Job; index: number }) {
  const running = ITEM_RUNNING.has(job.status);
  const tone = job.mode === "audio" ? "text-amber" : "text-accent";

  return (
    <li className="flex items-center gap-3 bg-surface px-3 py-2.5">
      <span className="w-5 shrink-0 text-right font-mono text-data tabular-nums text-muted">
        {index}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{job.title ?? job.video_id}</p>
        {running ? (
          <>
            <div className="mt-1 h-1 overflow-hidden rounded-full bg-surface-2">
              <div
                className={`h-full rounded-full transition-[width] duration-300 ease-soft ${
                  job.mode === "audio" ? "bg-amber" : "bg-accent"
                } ${job.status === "downloading" ? "" : "w-1/3 animate-slide"}`}
                style={
                  job.status === "downloading" ? { width: `${job.progress.percent}%` } : undefined
                }
              />
            </div>
            {/* One line on a 390px phone, next to a pill that already names the
                stage: while downloading the numbers say more than the word does. */}
            <p className="mt-1 truncate font-mono text-data tabular-nums text-muted">
              {job.status === "downloading"
                ? [
                    `${job.progress.percent.toFixed(0)}%`,
                    job.progress.eta_sec != null ? formatEta(job.progress.eta_sec) : "",
                  ]
                    .filter(Boolean)
                    .join(" · ")
                : STAGE_LABEL[job.status]}
            </p>
          </>
        ) : (
          <p className="truncate text-xs text-muted">
            {job.status === "error" ? (
              <span className="text-danger">{job.error?.message ?? "Failed"}</span>
            ) : job.status === "done" ? (
              <>
                <span className={`font-medium ${tone}`}>{job.label}</span>
                {job.file_available ? ` · ${formatBytes(job.size_bytes)}` : " · link expired"}
              </>
            ) : (
              (STAGE_LABEL[job.status] ?? job.status)
            )}
          </p>
        )}
      </div>
      {job.file_available ? (
        <a
          href={api.fileUrl(job.id)}
          download={job.filename ?? undefined}
          aria-label={`Save ${job.title ?? job.video_id}`}
          className="tap flex shrink-0 items-center gap-1 rounded-control bg-ok px-3 text-xs font-semibold text-on-ok transition-ui hover:opacity-90"
        >
          <CheckIcon className="h-3.5 w-3.5" />
          Save
        </a>
      ) : (
        <span
          className={`shrink-0 rounded-md px-2 py-1 font-mono text-label uppercase ${
            job.status === "error"
              ? "bg-danger-soft text-danger"
              : job.status === "cancelled"
                ? "bg-surface-2 text-muted"
                : running
                  ? "bg-accent-soft text-accent"
                  : "bg-surface-2 text-muted"
          }`}
        >
          {job.status === "queued" ? "Waiting" : (STAGE_LABEL[job.status] ?? job.status)}
        </span>
      )}
    </li>
  );
}

/* ------------------------------------------------------------------ history */

/** A playlist in the history list, expandable to the videos inside it. */
export function PlaylistHistoryRow({ playlist }: { playlist: Playlist }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Job[] | null>(playlist.items);
  const [loading, setLoading] = useState(false);
  const state = PLAYLIST_STATUS[playlist.status];

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (!next || items) return;
    setLoading(true);
    try {
      const full = await api.getPlaylist(playlist.id);
      setItems(full.items ?? []);
    } catch {
      setItems(null); // reopening asks again
    } finally {
      setLoading(false);
    }
  };

  return (
    <li className="bg-surface">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="tap flex w-full items-center gap-3 px-3 py-3 text-left transition-ui hover:bg-surface-2"
      >
        <span className="relative shrink-0">
          {playlist.thumbnail ? (
            // eslint-disable-next-line @next/next/no-img-element -- remote thumbnail, unoptimized on purpose
            <img
              src={playlist.thumbnail}
              alt=""
              width={64}
              height={40}
              loading="lazy"
              decoding="async"
              className="h-10 w-16 rounded bg-surface-2 object-cover"
            />
          ) : (
            <span className="flex h-10 w-16 items-center justify-center rounded bg-surface-2 text-muted">
              {playlist.mode === "audio" ? (
                <AudioIcon className="h-4 w-4" />
              ) : (
                <VideoIcon className="h-4 w-4" />
              )}
            </span>
          )}
          <span className="absolute bottom-0.5 right-0.5 rounded bg-ink/80 px-1 font-mono text-[10px] font-medium text-bg">
            {playlist.total_items}
          </span>
        </span>
        {/* The title gets the whole line: on a 390px phone a chip beside it
            leaves room for about three words. */}
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">
            {playlist.title ?? playlist.playlist_id}
          </span>
          <span className="mt-0.5 flex items-center gap-1.5 truncate text-xs text-muted">
            <span className="shrink-0 rounded bg-accent-soft px-1.5 py-0.5 text-[10px] font-semibold uppercase text-accent">
              Playlist
            </span>
            <span className="truncate">
              {playlist.completed_items} of {playlist.total_items} saved
              {playlist.failed_items > 0 && ` · ${playlist.failed_items} failed`}
            </span>
          </span>
        </span>
        <span
          className={`shrink-0 rounded-md px-2 py-1 font-mono text-label uppercase ${state.tone}`}
        >
          {state.label}
        </span>
        <svg
          aria-hidden
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`h-4 w-4 shrink-0 text-muted transition-ui ${open ? "rotate-180" : ""}`}
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div className="border-t border-line-soft px-3 py-2">
          {loading ? (
            <div className="space-y-2 py-1" aria-hidden>
              <Skeleton className="h-3.5 w-4/5" />
              <Skeleton className="h-3.5 w-3/5" />
            </div>
          ) : items && items.length > 0 ? (
            <ul className="divide-y divide-line-soft overflow-hidden rounded-control border border-line">
              {items.map((item, i) => (
                <PlaylistItemRow key={item.id} job={item} index={i + 1} />
              ))}
            </ul>
          ) : (
            <p className="py-2 text-xs text-muted">
              The videos in this playlist could not be loaded. Close this and open it again.
            </p>
          )}
        </div>
      )}
    </li>
  );
}

function Thumb({ src }: { src: string | null }) {
  if (!src) return <div className="h-16 w-28 rounded-md bg-surface-2" aria-hidden />;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- remote thumbnail, unoptimized on purpose
    <img
      src={src}
      alt=""
      width={112}
      height={63}
      decoding="async"
      fetchPriority="high"
      className="h-16 w-28 rounded-md bg-surface-2 object-cover"
    />
  );
}
