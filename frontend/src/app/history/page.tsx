"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { BottomDock } from "@/components/bottom-nav";
import { AppHeader } from "@/components/header";
import { AudioIcon, InboxIcon, VideoIcon } from "@/components/icons";
import { ErrorState, Page, Skeleton } from "@/components/ui";
import { api, type Job } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatBytes, formatDay } from "@/lib/format";

const STAGE: Record<string, string> = {
  queued: "Queued",
  fetching: "Starting",
  downloading: "Downloading",
  processing: "Converting",
  done: "Ready",
  error: "Failed",
  cancelled: "Cancelled",
};

const RUNNING = ["queued", "fetching", "downloading", "processing"];

export default function HistoryPage() {
  const { ready, user, available } = useAuth();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const retry = useCallback(() => {
    setJobs(null);
    setError(false);
    setAttempt((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!ready) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    const load = async () => {
      try {
        const list = await api.listJobs(50);
        if (stopped) return;
        setJobs(list);
        setError(false);
        // Keep refreshing while something is still running.
        if (list.some((j) => RUNNING.includes(j.status))) timer = setTimeout(load, 2000);
      } catch {
        if (!stopped) setError(true);
      }
    };
    void load();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [ready, user, attempt]);

  // Group by the day the download started, newest first.
  const days = useMemo(() => {
    if (!jobs) return [];
    const buckets = new Map<string, Job[]>();
    for (const job of jobs) {
      const key = formatDay(job.created_at);
      const list = buckets.get(key);
      if (list) list.push(job);
      else buckets.set(key, [job]);
    }
    return [...buckets.entries()];
  }, [jobs]);

  return (
    <>
      <Page>
        <AppHeader />
        <h1 className="font-display text-display">
          {user ? "My downloads" : "Downloads on this device"}
        </h1>
        <p className="mt-1 text-sm text-muted">
          {!user && available ? (
            <>
              <Link href="/signin" className="font-medium text-accent hover:underline">
                Sign in
              </Link>{" "}
              to keep your history on every device.
            </>
          ) : (
            "Files are removed from the server an hour after they finish. The list stays."
          )}
        </p>

        <div className="mt-5">
          {error ? (
            <ErrorState
              title="Could not load your downloads"
              body="The server did not answer. It may be starting up after being idle."
              onRetry={retry}
            />
          ) : jobs === null ? (
            <ListSkeleton />
          ) : jobs.length === 0 ? (
            <div className="rounded-card border border-dashed border-line bg-surface/60 px-4 py-10 text-center">
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-surface-2 text-muted">
                <InboxIcon className="h-6 w-6" />
              </div>
              <p className="text-title text-ink">Nothing here yet</p>
              <p className="mx-auto mt-1 max-w-xs text-sm text-muted">
                Paste a YouTube link on the download screen and the file will show up here.
              </p>
              <Link
                href="/"
                className="tap mt-4 inline-flex items-center rounded-control bg-accent px-4 text-sm font-semibold text-on-accent"
              >
                Download something
              </Link>
            </div>
          ) : (
            <div className="space-y-6">
              {days.map(([day, list]) => (
                <section key={day} aria-label={day}>
                  <h2 className="mb-2 text-label uppercase text-muted">{day}</h2>
                  <ul className="divide-y divide-line-soft overflow-hidden rounded-card border border-line bg-surface">
                    {list.map((j) => (
                      <Row key={j.id} job={j} />
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          )}
        </div>
      </Page>
      <BottomDock />
    </>
  );
}

function Row({ job }: { job: Job }) {
  const tone = job.mode === "audio" ? "text-amber" : "text-accent";
  const detail =
    job.status === "done"
      ? job.file_available
        ? formatBytes(job.size_bytes)
        : "link expired"
      : job.status === "error"
        ? (job.error?.message ?? "Failed")
        : (STAGE[job.status] ?? job.status);

  return (
    <li className="flex items-center gap-3 px-3 py-3">
      {job.thumbnail ? (
        // eslint-disable-next-line @next/next/no-img-element -- remote thumbnail, unoptimized on purpose
        <img
          src={job.thumbnail}
          alt=""
          width={64}
          height={40}
          loading="lazy"
          decoding="async"
          className="h-10 w-16 shrink-0 rounded bg-surface-2 object-cover"
        />
      ) : (
        <div className="flex h-10 w-16 shrink-0 items-center justify-center rounded bg-surface-2 text-muted">
          {job.mode === "audio" ? <AudioIcon className="h-4 w-4" /> : <VideoIcon className="h-4 w-4" />}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{job.title ?? job.video_id}</p>
        <p className="truncate text-xs text-muted">
          <span className={`font-medium ${tone}`}>{job.label}</span>
          {" · "}
          {detail}
        </p>
      </div>
      {job.file_available ? (
        <a
          href={api.fileUrl(job.id)}
          download={job.filename ?? undefined}
          aria-label={`Save ${job.title ?? job.video_id}`}
          className="tap flex shrink-0 items-center rounded-control border border-line px-3 text-xs font-semibold text-ink-2 transition-ui hover:bg-surface-2"
        >
          Save
        </a>
      ) : job.status === "done" || job.status === "error" ? (
        <Link
          href={`/?url=${encodeURIComponent(job.url)}`}
          aria-label={`Download ${job.title ?? job.video_id} again`}
          className="tap flex shrink-0 items-center rounded-control border border-line px-3 text-xs font-semibold text-ink-2 transition-ui hover:bg-surface-2"
        >
          Again
        </Link>
      ) : (
        <span className="shrink-0 rounded-md bg-accent-soft px-2 py-1 font-mono text-label uppercase text-accent">
          {STAGE[job.status] ?? job.status}
        </span>
      )}
    </li>
  );
}

function ListSkeleton() {
  return (
    <>
      <p className="sr-only" role="status">
        Loading your downloads.
      </p>
      <div aria-hidden>
        <Skeleton className="mb-2 h-3 w-16" />
        <ul className="divide-y divide-line-soft overflow-hidden rounded-card border border-line bg-surface">
          {[0, 1, 2, 3].map((i) => (
            <li key={i} className="flex items-center gap-3 px-3 py-3">
              <Skeleton className="h-10 w-16 shrink-0 rounded" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-3.5 w-4/5" />
                <Skeleton className="h-3 w-2/5" />
              </div>
              <Skeleton className="h-8 w-14 shrink-0 rounded-control" />
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}
