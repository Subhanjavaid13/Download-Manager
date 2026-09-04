"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppHeader, SubNav } from "@/components/header";
import { Card, Notice, Page } from "@/components/ui";
import { api, type Job } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatBytes } from "@/lib/format";

const STAGE: Record<string, string> = {
  queued: "Queued",
  fetching: "Starting",
  downloading: "Downloading",
  processing: "Converting",
  done: "Ready",
  error: "Failed",
  cancelled: "Cancelled",
};

export default function HistoryPage() {
  const { ready, user, available } = useAuth();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    const load = async () => {
      try {
        const list = await api.listJobs(50);
        if (stopped) return;
        setJobs(list);
        // Keep refreshing while something is still running.
        if (list.some((j) => !["done", "error", "cancelled"].includes(j.status))) {
          timer = setTimeout(load, 2000);
        }
      } catch {
        if (!stopped) setError("Could not load your downloads.");
      }
    };
    void load();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [ready, user]);

  return (
    <Page>
      <AppHeader />
      <SubNav />
      <h1 className="font-display text-xl font-semibold">
        {user ? "My downloads" : "Downloads on this device"}
      </h1>
      {!user && available && (
        <p className="mt-1 text-sm text-muted">
          <Link href="/signin" className="font-medium text-accent hover:underline">
            Sign in
          </Link>{" "}
          to keep history across devices.
        </p>
      )}
      <div className="mt-4">
        {error && <Notice tone="error">{error}</Notice>}
        {jobs && jobs.length === 0 && (
          <Card>
            <p className="text-sm text-muted">Nothing yet. Your downloads will show up here.</p>
          </Card>
        )}
        {jobs && jobs.length > 0 && (
          <ul className="divide-y divide-line-soft rounded-xl border border-line bg-surface">
            {jobs.map((j) => (
              <li key={j.id} className="flex items-center gap-3 px-3 py-3">
                {j.thumbnail ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={j.thumbnail} alt="" className="h-10 w-16 shrink-0 rounded bg-line-soft object-cover" />
                ) : (
                  <div className="h-10 w-16 shrink-0 rounded bg-line-soft" />
                )}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{j.title ?? j.video_id}</p>
                  <p className="truncate text-xs text-muted">
                    <span className={j.mode === "audio" ? "font-medium text-amber" : "font-medium text-accent"}>
                      {j.label}
                    </span>
                    {" · "}
                    {new Date(j.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                    {" · "}
                    {j.status === "done"
                      ? j.file_available
                        ? formatBytes(j.size_bytes)
                        : "expired"
                      : j.status === "error"
                        ? (j.error?.message ?? "Failed")
                        : STAGE[j.status] ?? j.status}
                  </p>
                </div>
                {j.file_available ? (
                  <a
                    href={api.fileUrl(j.id)}
                    download={j.filename ?? undefined}
                    className="shrink-0 rounded-md border border-line px-2.5 py-1.5 text-xs font-medium text-ink-2 hover:bg-bg"
                  >
                    Save
                  </a>
                ) : j.status === "done" || j.status === "error" ? (
                  <Link
                    href={`/?url=${encodeURIComponent(j.url)}`}
                    className="shrink-0 rounded-md border border-line px-2.5 py-1.5 text-xs font-medium text-ink-2 hover:bg-bg"
                  >
                    Again
                  </Link>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Page>
  );
}
