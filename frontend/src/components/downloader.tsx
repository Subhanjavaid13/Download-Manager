"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  api,
  ApiError,
  type AudioBitrate,
  type AudioFormat,
  type Health,
  type Info,
  type Job,
  type JobCreate,
  type Playlist,
  playlistUrl,
  type VideoHeight,
} from "@/lib/api";
import {
  formatBytes,
  formatClock,
  formatDuration,
  formatEta,
  formatSpeed,
  looksLikeYouTube,
  parseSharedLink,
  spokenDuration,
  type Mode,
  type SharedLink,
} from "@/lib/format";
import { loadPrefs, savePrefs } from "@/lib/prefs";
import { BottomDock } from "@/components/bottom-nav";
import { AppHeader } from "@/components/header";
import {
  AudioIcon,
  CheckIcon,
  CloseIcon,
  DownloadIcon,
  LinkIcon,
  VideoIcon,
} from "@/components/icons";
import { InstallPrompt } from "@/components/install-prompt";
import {
  type Allowance,
  PLAYLIST_ACTIVE,
  PlaylistCard,
  PlaylistPreview,
  PlaylistTargetChoice,
  STAGE_LABEL,
} from "@/components/playlist";
import {
  Card,
  EmptyState,
  Notice,
  Page,
  SectionLabel,
  SiteFooter,
  Skeleton,
} from "@/components/ui";
import { useAuth } from "@/lib/auth";

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

/** What the link offers: one video, a whole playlist, or the choice of both. */
type Target = "video" | "playlist";

function toHeight(n: number | null): VideoHeight | null {
  if (n === null) return null;
  return VIDEO_HEIGHTS.find((h) => h === n) ?? 1080;
}

export default function Downloader() {
  const params = useSearchParams();

  // The Android share sheet arrives as ?url= (or ?text= with the title glued on).
  const sharedUrl = params.get("url");
  const sharedText = params.get("text");
  const sharedTitle = params.get("title");
  const shared = useMemo(
    () => parseSharedLink({ url: sharedUrl, text: sharedText, title: sharedTitle }),
    [sharedUrl, sharedText, sharedTitle],
  );

  // A newly shared link is a fresh start: the key remounts the screen so the
  // field, the preview, and any finished job all reset in one go.
  return <DownloadScreen key={shared?.url ?? "blank"} shared={shared} />;
}

function DownloadScreen({ shared }: { shared: SharedLink | null }) {
  const auth = useAuth();

  const [prefs] = useState(loadPrefs);
  const [url, setUrl] = useState(() => shared?.url ?? "");
  const [mode, setMode] = useState<Mode>(() => shared?.mode ?? prefs.mode);
  const [audioChoice, setAudioChoice] = useState(() => prefs.audio);
  const [height, setHeight] = useState<VideoHeight | null>(() => toHeight(prefs.height));
  // True while the link we are previewing came from a share or a deep link.
  const [fromShare, setFromShare] = useState(() => !!shared);

  const [health, setHealth] = useState<Health | null | "offline">(null);
  const [info, setInfo] = useState<Info | null>(null);
  const [infoError, setInfoError] = useState<string | null>(null);

  const [job, setJob] = useState<Job | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [recent, setRecent] = useState<Job[] | null>(null);

  // Playlists. `target` is only a real question when the link carries a video
  // id and a list id at once; a bare playlist link can only mean the playlist.
  const [target, setTarget] = useState<Target>("video");
  const [playlistInfo, setPlaylistInfo] = useState<Info | null>(null);
  const [playlist, setPlaylist] = useState<Playlist | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const jobRef = useRef<HTMLElement>(null);
  // A shared link should show its preview at once, not after the typing pause.
  const skipDebounce = useRef(!!shared);

  // The preview is loading whenever we have a plausible link and neither a
  // result nor an error for it yet. Derived, so it can never get out of step.
  const loadingInfo = looksLikeYouTube(url.trim()) && !info && !infoError;

  const refreshRecent = useCallback(() => {
    api
      .listJobs(8)
      .then(setRecent)
      .catch(() => setRecent((r) => r ?? []));
  }, []);

  // Backend status for the header dot, and this browser's recent downloads.
  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch(() => setHealth("offline"));
    refreshRecent();
  }, [refreshRecent]);

  // Remember the choices for next time.
  useEffect(() => {
    savePrefs({ mode, audio: audioChoice, height });
  }, [mode, audioChoice, height]);

  // Changing the link invalidates the preview immediately.
  const updateUrl = useCallback((next: string) => {
    setUrl(next);
    setInfo(null);
    setInfoError(null);
    setFromShare(false);
    setTarget("video");
    setPlaylistInfo(null);
  }, []);

  // Metadata preview: instant for a shared link, debounced while typing.
  useEffect(() => {
    const candidate = url.trim();
    if (!looksLikeYouTube(candidate)) return;
    const wait = skipDebounce.current ? 0 : 450;
    skipDebounce.current = false;

    const ctrl = new AbortController();
    const timer = setTimeout(async () => {
      try {
        setInfo(await api.info(candidate, ctrl.signal));
      } catch (e) {
        if (ctrl.signal.aborted) return;
        setInfoError(e instanceof ApiError ? e.message : "Could not load the video details.");
      }
    }, wait);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [url]);

  // Bring the progress card into view the moment a download starts, so the
  // user does not have to hunt for it below the quality chips.
  const jobId = job?.id ?? null;
  useEffect(() => {
    if (!jobId) return;
    jobRef.current?.scrollIntoView({ block: "center" });
  }, [jobId]);

  // Poll the running job once a second until it reaches a final state.
  const jobActive = !!job && !TERMINAL.has(job.status);
  useEffect(() => {
    if (!jobId || !jobActive) return;
    const timer = setInterval(async () => {
      try {
        const next = await api.getJob(jobId);
        setJob(next);
        if (TERMINAL.has(next.status)) {
          refreshRecent();
          void auth.refreshMe();
        }
      } catch {
        // keep the last known state; the next tick retries
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [jobId, jobActive, refreshRecent, auth]);

  // Today's allowance, so a playlist can say what it will cost before it starts.
  // A signed-in user has a running total; a guest only has the limit.
  const allowance: Allowance = useMemo(() => {
    if (!auth.config?.enabled) return null; // auth off: no quota to speak of
    if (auth.me) return { used: auth.me.downloads_today, limit: auth.me.daily_quota, guest: false };
    return { used: null, limit: auth.config.anon_daily_limit, guest: true };
  }, [auth.config, auth.me]);

  // What the pasted link can mean. A bare playlist link has no video to choose,
  // so the question is only asked for `watch?v=…&list=…`.
  const playlistOnly = info?.kind === "playlist";
  const bothOptions = info?.kind === "video" && !!info.playlist_id;
  const wantsPlaylist = playlistOnly || (bothOptions && target === "playlist");
  // For a bare playlist link the preview we already have IS the playlist.
  const playlistPreview = playlistOnly ? info : playlistInfo;
  const playlistPreviewLoading = wantsPlaylist && !playlistPreview;

  // Asking for the playlist behind a video link costs a second preview call,
  // so it only happens once the user actually picks "Whole playlist".
  const listId = info?.playlist_id ?? null;
  useEffect(() => {
    if (!wantsPlaylist || playlistOnly || !listId || playlistInfo) return;
    const ctrl = new AbortController();
    api
      .info(playlistUrl(listId), ctrl.signal)
      .then(setPlaylistInfo)
      .catch((e) => {
        if (ctrl.signal.aborted) return;
        setInfoError(
          e instanceof ApiError ? e.message : "Could not load the playlist details.",
        );
        setTarget("video");
      });
    return () => ctrl.abort();
  }, [wantsPlaylist, playlistOnly, listId, playlistInfo]);

  // Poll the playlist the same way as a single job: its items carry their own
  // progress, so one request keeps the whole list up to date.
  const playlistId = playlist?.id ?? null;
  const playlistActive = !!playlist && PLAYLIST_ACTIVE.has(playlist.status);
  useEffect(() => {
    if (!playlistId || !playlistActive) return;
    const timer = setInterval(async () => {
      try {
        const next = await api.getPlaylist(playlistId);
        setPlaylist(next);
        if (!PLAYLIST_ACTIVE.has(next.status)) {
          refreshRecent();
          void auth.refreshMe();
        }
      } catch {
        // keep the last known state; the next tick retries
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [playlistId, playlistActive, refreshRecent, auth]);

  // Bring a starting playlist into view, exactly as a single job does.
  useEffect(() => {
    if (!playlistId) return;
    jobRef.current?.scrollIntoView({ block: "center" });
  }, [playlistId]);

  // Video presets that make sense for this video (never above what YouTube has).
  // A playlist reports no heights, so every preset is offered and each video
  // falls back on its own.
  const maxAvailable =
    !wantsPlaylist && info?.available_heights.length ? Math.max(...info.available_heights) : null;
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
      if (text) {
        skipDebounce.current = true;
        updateUrl(text.trim());
      }
    } catch {
      // Clipboard permission denied; focus the field so it can be pasted by hand.
      inputRef.current?.focus();
    }
  }, [updateUrl]);

  // A playlist over the server's item cap can never start, so the button says so
  // by being unavailable rather than by failing after a round trip.
  const overCap = wantsPlaylist && !!playlistPreview?.playlist_truncated;
  const canSubmit =
    !!info &&
    !loadingInfo &&
    !submitting &&
    !jobActive &&
    !playlistActive &&
    !overCap &&
    (!wantsPlaylist || !!playlistPreview);

  const submit = useCallback(async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setJobError(null);
    // A playlist is started from the playlist address, so the server is never
    // left guessing which of the two ids in `watch?v=…&list=…` we meant.
    const link = wantsPlaylist && listId ? playlistUrl(listId) : url.trim();
    const base = { url: link, mode };
    const body: JobCreate =
      mode === "audio"
        ? (() => {
            const opt = AUDIO_OPTIONS.find((o) => o.id === audioChoice) ?? AUDIO_OPTIONS[1];
            return { ...base, audio_format: opt.audio_format, audio_bitrate: opt.audio_bitrate };
          })()
        : { ...base, video_height: effectiveHeight };
    try {
      if (wantsPlaylist) setPlaylist(await api.createPlaylist(body));
      else setJob(await api.createJob(body));
    } catch (e) {
      // The server's refusals (over the cap, not enough quota left today) are
      // already plain English, so they are shown exactly as they arrive.
      setJobError(e instanceof ApiError ? e.message : "Could not start the download.");
    } finally {
      setSubmitting(false);
    }
  }, [canSubmit, url, mode, audioChoice, effectiveHeight, wantsPlaylist, listId]);

  const cancel = useCallback(async () => {
    try {
      if (playlistId) await api.cancelPlaylist(playlistId);
      else if (jobId) await api.cancelJob(jobId);
    } catch {
      // The download may already have finished.
    }
  }, [jobId, playlistId]);

  const reset = useCallback(() => {
    setJob(null);
    setPlaylist(null);
    setJobError(null);
  }, []);

  const startOver = useCallback(() => {
    reset();
    updateUrl("");
    inputRef.current?.focus();
  }, [reset, updateUrl]);

  const selectedLabel =
    mode === "audio"
      ? (() => {
          const o = AUDIO_OPTIONS.find((x) => x.id === audioChoice);
          return o ? `${o.label} · ${o.sub}` : "";
        })()
      : effectiveHeight
        ? `MP4 · ${effectiveHeight}p`
        : "MP4 · best available";

  // One polite live region for the whole flow, so a screen reader hears the
  // progress without the percentage being read out every second.
  const percentBucket = job ? Math.floor(job.progress.percent / 20) * 20 : 0;
  const playlistDone = playlist ? playlist.completed_items : 0;
  const announcement = useMemo(() => {
    // Errors that are already marked up with role="alert" are left out here,
    // so a screen reader reads them once rather than twice.
    if (playlist) {
      switch (playlist.status) {
        case "queued":
        case "running":
          return `Playlist downloading. ${playlistDone} of ${playlist.total_items} videos done.`;
        case "cancelled":
          return "Playlist cancelled.";
        default:
          return `Playlist finished. ${playlist.completed_items} of ${playlist.total_items} videos saved${
            playlist.failed_items ? `, ${playlist.failed_items} failed` : ""
          }. Save each file from the list.`;
      }
    }
    if (job) {
      switch (job.status) {
        case "done":
          return `Ready. ${job.filename ?? job.label}${
            job.size_bytes ? `, ${formatBytes(job.size_bytes)}` : ""
          }. Use the Save file button.`;
        case "error":
          return `Download failed. ${job.error?.message ?? ""}`;
        case "cancelled":
          return "Download cancelled.";
        case "downloading":
          return `Downloading, ${percentBucket} percent.`;
        default:
          return STAGE_LABEL[job.status] ?? job.status;
      }
    }
    if (loadingInfo) return "Loading video details.";
    if (wantsPlaylist && playlistPreview)
      return `Found the playlist ${playlistPreview.title}, ${playlistPreview.playlist_count ?? 0} videos.`;
    if (info)
      return `Found ${info.title}${info.channel ? ` by ${info.channel}` : ""}${
        info.duration_sec != null ? `, ${spokenDuration(info.duration_sec)}` : ""
      }.`;
    return "";
  }, [job, info, loadingInfo, percentBucket, playlist, playlistDone, wantsPlaylist, playlistPreview]);

  const others = (recent ?? []).filter((r) => r.id !== job?.id).slice(0, 5);

  return (
    <>
      <Page dock="action">
        <AppHeader asHeading right={<HealthDot health={health} />} />

        <p className="sr-only" role="status" aria-live="polite">
          {announcement}
        </p>

        <AuthBanners />
        <InstallPrompt />

        {/* Link + preview */}
        <Card className="p-3">
          <label htmlFor="url" className="mb-1.5 block text-label uppercase text-muted">
            YouTube link
          </label>
          <div className="flex gap-2">
            <div className="relative min-w-0 flex-1">
              <span
                aria-hidden
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted"
              >
                <LinkIcon className="h-4 w-4" />
              </span>
              <input
                ref={inputRef}
                id="url"
                type="url"
                inputMode="url"
                autoComplete="off"
                autoCapitalize="off"
                spellCheck={false}
                enterKeyHint="go"
                placeholder="https://youtu.be/…"
                aria-describedby="url-help"
                value={url}
                onChange={(e) => updateUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submit()}
                className="tap w-full rounded-control border border-line bg-bg py-2.5 pl-9 pr-9 text-base text-ink transition-ui placeholder:text-muted focus:border-accent"
              />
              {url && (
                <button
                  type="button"
                  onClick={startOver}
                  aria-label="Clear the link"
                  className="absolute right-1 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full text-muted transition-ui hover:bg-surface-2 hover:text-ink-2"
                >
                  <CloseIcon className="h-4 w-4" />
                </button>
              )}
            </div>
            <button
              type="button"
              onClick={pasteFromClipboard}
              className="tap shrink-0 rounded-control border border-line px-3 text-sm font-medium text-ink-2 transition-ui hover:bg-surface-2"
            >
              Paste
            </button>
          </div>

          {/* Fixed height so nothing below moves as the states swap. */}
          <div className="mt-3 flex min-h-18 flex-col justify-center">
            {loadingInfo ? (
              <PreviewSkeleton />
            ) : info && wantsPlaylist ? (
              <PlaylistPreview
                info={playlistPreview}
                allowance={allowance}
                loading={playlistPreviewLoading}
              />
            ) : info ? (
              <Preview info={info} shared={fromShare} />
            ) : infoError ? (
              <div className="rounded-control bg-danger-soft px-3 py-2" role="alert">
                <p className="text-sm font-medium text-danger">{infoError}</p>
                <p className="mt-0.5 text-xs text-ink-2">
                  Check the link, or try a different video.
                </p>
              </div>
            ) : (
              <p id="url-help" className="px-1 text-sm text-muted">
                Paste a video link. The title, channel, and length show up here before you download
                anything.
              </p>
            )}
          </div>

          {/* The link holds a video and a playlist: ask which one they meant. */}
          {bothOptions && (
            <div className="mt-3">
              <PlaylistTargetChoice
                target={target}
                onChange={setTarget}
                count={playlistInfo?.playlist_count ?? null}
              />
            </div>
          )}
        </Card>

        {/* Mode */}
        <section className="mt-section" aria-labelledby="mode-label">
          <SectionLabel id="mode-label">Save as</SectionLabel>
          <div
            role="radiogroup"
            aria-labelledby="mode-label"
            className="grid grid-cols-2 gap-1 rounded-card border border-line bg-surface p-1"
          >
            <ModeButton
              active={mode === "audio"}
              onSelect={() => setMode("audio")}
              onArrow={() => setMode("video")}
              tone="amber"
              icon={<AudioIcon />}
              label="Audio"
              hint="MP3, M4A, Opus"
            />
            <ModeButton
              active={mode === "video"}
              onSelect={() => setMode("video")}
              onArrow={() => setMode("audio")}
              tone="blue"
              icon={<VideoIcon />}
              label="Video"
              hint="MP4 with sound"
            />
          </div>
        </section>

        {/* Quality */}
        <section className="mt-5" aria-labelledby="quality-label">
          <SectionLabel id="quality-label">Quality</SectionLabel>
          {mode === "audio" ? (
            <div role="group" aria-labelledby="quality-label" className="grid grid-cols-3 gap-2 sm:grid-cols-5">
              {AUDIO_OPTIONS.map((o) => (
                <Chip
                  key={o.id}
                  active={audioChoice === o.id}
                  tone="amber"
                  onClick={() => setAudioChoice(o.id)}
                  label={o.label}
                  sub={o.sub}
                  describe={`${o.label}, ${o.sub}`}
                />
              ))}
            </div>
          ) : (
            <div role="group" aria-labelledby="quality-label" className="grid grid-cols-4 gap-2 sm:grid-cols-7">
              {videoPresets.map((h) => (
                <Chip
                  key={h}
                  active={effectiveHeight === h}
                  tone="blue"
                  onClick={() => setHeight(h)}
                  label={`${h}p`}
                  sub={h >= 720 ? "HD" : "SD"}
                  describe={`${h}p, MP4`}
                />
              ))}
              <Chip
                active={effectiveHeight === null}
                tone="blue"
                onClick={() => setHeight(null)}
                label="Best"
                sub="available"
                describe="Best available quality"
              />
            </div>
          )}

          {mode === "video" && maxAvailable && height !== null && height > maxAvailable && (
            <p className="mt-2 text-xs text-muted">
              This video only goes up to {maxAvailable}p, so {effectiveHeight}p is the best it can
              do.
            </p>
          )}
          {mode === "video" && wantsPlaylist && (
            <p className="mt-2 text-xs text-muted">
              Every quality is offered because the videos have not been checked one by one: each
              one falls back to the best it actually has, so a 4K pick can still save a 720p file.
            </p>
          )}
          {mode === "audio" && audioChoice === "mp3-320" && (
            <p className="mt-2 text-xs text-muted">
              YouTube&apos;s source audio is about 128 to 160 kbps. 320 kbps makes a bigger file, not
              a better one.
            </p>
          )}
          {auth.me && (
            <p className="mt-2 text-xs tabular-nums text-muted">
              {auth.me.downloads_today} of {auth.me.daily_quota} downloads used today.
            </p>
          )}
        </section>

        {/* Job */}
        {(job || playlist || jobError) && (
          <section ref={jobRef} className="mt-section" aria-label="Download status">
            {jobError && !job && !playlist && (
              <div className="rounded-card border border-danger/40 bg-danger-soft px-3 py-3" role="alert">
                <p className="text-sm font-medium text-danger">{jobError}</p>
                <button
                  type="button"
                  onClick={submit}
                  className="mt-2 text-sm font-semibold text-ink-2 underline underline-offset-2"
                >
                  Try again
                </button>
              </div>
            )}
            {playlist && (
              <PlaylistCard playlist={playlist} onCancel={cancel} onStartOver={startOver} />
            )}
            {job && <JobCard job={job} onCancel={cancel} onReset={reset} onNext={startOver} />}
          </section>
        )}

        {/* Recent */}
        <section className="mt-8" aria-labelledby="recent-label">
          <SectionLabel id="recent-label">Recent on this device</SectionLabel>
          {recent === null ? (
            <ul className="divide-y divide-line-soft overflow-hidden rounded-card border border-line bg-surface">
              {[0, 1, 2].map((i) => (
                <li key={i} className="flex items-center gap-3 px-3 py-3">
                  <Skeleton className="h-4 w-4 rounded-full" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-3.5 w-3/4" />
                    <Skeleton className="h-3 w-1/3" />
                  </div>
                </li>
              ))}
            </ul>
          ) : others.length === 0 ? (
            <EmptyState
              icon={<DownloadIcon />}
              title="No downloads yet"
              body="Finished files show up here for an hour, so you can save them again without waiting."
            />
          ) : (
            <>
              <ul className="divide-y divide-line-soft overflow-hidden rounded-card border border-line bg-surface">
                {others.map((r) => (
                  <RecentRow key={r.id} job={r} />
                ))}
              </ul>
              <Link
                href="/history"
                className="mt-2 inline-block text-sm font-medium text-accent underline-offset-2 hover:underline"
              >
                See all downloads
              </Link>
            </>
          )}
        </section>

        <SiteFooter className="mt-10" />
      </Page>

      <BottomDock
        action={
          <ActionBar
            mode={mode}
            info={info}
            job={job}
            playlist={playlist}
            selectedLabel={selectedLabel}
            canSubmit={canSubmit}
            submitting={submitting}
            onSubmit={submit}
            onShowFiles={() => jobRef.current?.scrollIntoView({ block: "start" })}
          />
        }
      />
    </>
  );
}

/* ---------- pieces ---------- */

function ActionBar({
  mode,
  info,
  job,
  playlist,
  selectedLabel,
  canSubmit,
  submitting,
  onSubmit,
  onShowFiles,
}: {
  mode: Mode;
  info: Info | null;
  job: Job | null;
  playlist: Playlist | null;
  selectedLabel: string;
  canSubmit: boolean;
  submitting: boolean;
  onSubmit: () => void;
  onShowFiles: () => void;
}) {
  const playlistRunning = !!playlist && PLAYLIST_ACTIVE.has(playlist.status);
  const playlistFinished = !!playlist && !playlistRunning;
  // Job-only, and written as one expression so TypeScript keeps narrowing `job`
  // for the branches below. The playlist path returns before any of it.
  const active = !!job && !TERMINAL.has(job.status);
  const done = job?.status === "done" && job.file_available;
  const percent = playlist ? playlist.percent : (job?.progress.percent ?? 0);

  // A finished playlist has many files, so the bar points at the list instead of
  // pretending there is one thing to save.
  if (playlist) {
    return (
      <>
        {playlistRunning && (
          <span
            aria-hidden
            className={`absolute inset-x-0 top-0 h-0.5 origin-left transition-[transform] duration-300 ease-soft ${
              mode === "audio" ? "bg-amber" : "bg-accent"
            }`}
            style={{ transform: `scaleX(${Math.max(percent, 3) / 100})` }}
          />
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-ink">
            {playlistRunning
              ? `Playlist · ${playlist.completed_items} of ${playlist.total_items}`
              : `${playlist.completed_items} of ${playlist.total_items} files ready`}
          </p>
          <p className="truncate text-xs text-muted">{playlist.title ?? "Playlist"}</p>
        </div>
        <button
          type="button"
          onClick={playlistFinished ? onShowFiles : onSubmit}
          disabled={playlistRunning}
          className="tap shrink-0 rounded-control bg-ok px-5 text-sm font-semibold text-on-ok transition-ui disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-muted disabled:opacity-100"
        >
          {playlistRunning ? "Working…" : "See files"}
        </button>
      </>
    );
  }

  return (
    <>
      {/* A hairline of progress along the top edge of the bar. */}
      {active && (
        <span
          aria-hidden
          className={`absolute inset-x-0 top-0 h-0.5 origin-left transition-[transform] duration-300 ease-soft ${
            mode === "audio" ? "bg-amber" : "bg-accent"
          }`}
          style={{ transform: `scaleX(${Math.max(percent, 3) / 100})` }}
        />
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold text-ink">
          {done ? "Your file is ready" : selectedLabel}
        </p>
        <p className="truncate text-xs text-muted">
          {active
            ? `${STAGE_LABEL[job.status]}${job.status === "downloading" ? ` · ${percent.toFixed(0)}%` : ""}`
            : (job?.title ?? info?.title ?? "Paste a link to start")}
        </p>
      </div>
      {done && job ? (
        <a
          href={api.fileUrl(job.id)}
          download={job.filename ?? undefined}
          className="tap inline-flex shrink-0 items-center gap-1.5 rounded-control bg-ok px-5 text-sm font-semibold text-on-ok transition-ui hover:opacity-90"
        >
          <CheckIcon className="h-4 w-4" />
          Save file
        </a>
      ) : (
        <button
          type="button"
          onClick={onSubmit}
          disabled={!canSubmit}
          className={`tap shrink-0 rounded-control px-5 text-sm font-semibold transition-ui disabled:cursor-not-allowed disabled:opacity-40 ${
            mode === "audio" ? "bg-amber text-on-amber" : "bg-accent text-on-accent"
          }`}
        >
          {submitting ? "Starting…" : active ? "Working…" : "Download"}
        </button>
      )}
    </>
  );
}

function AuthBanners() {
  const { available, ready, user, me, config } = useAuth();
  const params = useSearchParams();
  if (!available || !ready) return null;
  if (params.get("verified") && user && me?.email_verified) {
    return <Notice tone="ok" className="mb-4">Email verified. You are signed in.</Notice>;
  }
  if (params.get("deleted")) {
    return (
      <Notice tone="info" className="mb-4">
        Your account and its history are gone. You can still download as a guest.
      </Notice>
    );
  }
  if (user && me && !me.email_verified) {
    return (
      <Notice tone="warn" className="mb-4">
        Verify your email to start downloading. Check your inbox, or{" "}
        <Link href="/account" className="font-semibold underline">
          resend the link
        </Link>
        .
      </Notice>
    );
  }
  if (!user && config?.enabled) {
    return (
      <Notice tone="info" className="mb-4">
        Guests get {config.anon_daily_limit} downloads a day.{" "}
        <Link href="/signup" className="font-semibold underline">
          Create a free account
        </Link>{" "}
        for 20 a day and history on every device.
      </Notice>
    );
  }
  return null;
}

function HealthDot({ health }: { health: Health | null | "offline" }) {
  const state =
    health === null
      ? { color: "bg-muted", text: "Checking the server" }
      : health === "offline"
        ? { color: "bg-danger", text: "Server offline" }
        : !health.ffmpeg
          ? { color: "bg-amber", text: "FFmpeg missing" }
          : { color: "bg-ok", text: "Ready" };
  return (
    <span className="flex shrink-0 items-center gap-1.5 text-xs text-muted">
      <span className={`h-2 w-2 rounded-full ${state.color}`} aria-hidden />
      <span className="sr-only sm:not-sr-only">{state.text}</span>
    </span>
  );
}

function Thumb({
  src,
  className,
  width,
  height,
}: {
  src: string | null;
  className: string;
  width: number;
  height: number;
}) {
  if (!src) return <div className={`${className} bg-surface-2`} aria-hidden />;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- remote thumbnail, unoptimized on purpose
    <img
      src={src}
      alt=""
      // Width and height are set so the box never resizes once the image lands.
      width={width}
      height={height}
      // The preview thumbnail is the one image that is always on screen when
      // it appears, so it loads eagerly. List thumbnails stay lazy.
      decoding="async"
      fetchPriority="high"
      className={`${className} bg-surface-2 object-cover`}
    />
  );
}

function Preview({ info, shared }: { info: Info; shared: boolean }) {
  return (
    <div className="animate-rise">
      {shared && (
        <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-ok">
          <CheckIcon className="h-3.5 w-3.5" />
          Link received. Pick a format and download.
        </p>
      )}
      <div className="flex gap-3">
        <Thumb
          src={info.thumbnail}
          width={112}
          height={63}
          className="h-16 w-28 shrink-0 rounded-md"
        />
        <div className="min-w-0">
          <p className="line-clamp-2 text-sm font-semibold leading-snug">{info.title}</p>
          <p className="mt-1 truncate text-xs text-muted">
            {info.channel ?? "Unknown channel"}
            {info.duration_sec != null && <> · {formatDuration(info.duration_sec)}</>}
            {info.available_heights.length > 0 && (
              <> · up to {Math.max(...info.available_heights)}p</>
            )}
          </p>
          {info.playlist_id && (
            <p className="mt-1 text-xs font-medium text-amber">
              This link is part of a playlist. Choose below.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function PreviewSkeleton() {
  return (
    <div className="flex gap-3" aria-hidden>
      <Skeleton className="h-16 w-28 shrink-0 rounded-md" />
      <div className="flex-1 space-y-2 pt-1">
        <Skeleton className="h-3.5 w-11/12" />
        <Skeleton className="h-3.5 w-2/3" />
        <Skeleton className="h-3 w-1/3" />
      </div>
    </div>
  );
}

function RecentRow({ job }: { job: Job }) {
  const tone = job.mode === "audio" ? "text-amber" : "text-accent";
  return (
    <li className="flex items-center gap-3 px-3 py-2.5">
      <span className={`shrink-0 ${tone}`} aria-hidden>
        {job.mode === "audio" ? <AudioIcon className="h-4 w-4" /> : <VideoIcon className="h-4 w-4" />}
      </span>
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
          aria-label={`Save ${job.title ?? job.video_id}`}
          className="shrink-0 rounded-control border border-line px-2.5 py-1.5 text-xs font-semibold text-ink-2 transition-ui hover:bg-surface-2"
        >
          Save
        </a>
      ) : (
        <StatusPill status={job.status} />
      )}
    </li>
  );
}

function ModeButton({
  active,
  onSelect,
  onArrow,
  tone,
  icon,
  label,
  hint,
}: {
  active: boolean;
  onSelect: () => void;
  onArrow: () => void;
  tone: "amber" | "blue";
  icon: React.ReactNode;
  label: string;
  hint: string;
}) {
  const on = tone === "amber" ? "bg-amber-soft text-amber" : "bg-accent-soft text-accent";
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      tabIndex={active ? 0 : -1}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          e.preventDefault();
          onArrow();
        }
      }}
      className={`tap flex flex-col items-center justify-center gap-0.5 rounded-control px-3 py-2 transition-ui ${
        active ? on : "text-ink-2 hover:bg-surface-2"
      }`}
    >
      <span className="flex items-center gap-2 text-sm font-semibold">
        {icon}
        {label}
      </span>
      <span className="text-[11px] opacity-80">{hint}</span>
    </button>
  );
}

function Chip({
  active,
  onClick,
  tone,
  label,
  sub,
  describe,
}: {
  active: boolean;
  onClick: () => void;
  tone: "amber" | "blue";
  label: string;
  sub: string;
  describe: string;
}) {
  const on =
    tone === "amber"
      ? "border-amber bg-amber-soft text-amber"
      : "border-accent bg-accent-soft text-accent";
  return (
    <button
      type="button"
      aria-pressed={active}
      aria-label={describe}
      onClick={onClick}
      className={`tap flex flex-col items-center justify-center rounded-control border px-2 py-2 text-center transition-ui ${
        active ? on : "border-line bg-surface text-ink-2 hover:bg-surface-2"
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
  onNext,
}: {
  job: Job;
  onCancel: () => void;
  onReset: () => void;
  onNext: () => void;
}) {
  const p = job.progress;
  const active = !TERMINAL.has(job.status);
  const indeterminate = active && job.status !== "downloading";
  const barTone = job.mode === "audio" ? "bg-amber" : "bg-accent";

  return (
    <div className="animate-rise rounded-card border border-line bg-surface p-card shadow-card">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-label uppercase text-muted">{job.label}</p>
          <p className="mt-0.5 truncate text-sm font-semibold">
            {job.filename ?? job.title ?? STAGE_LABEL[job.status] ?? job.status}
          </p>
        </div>
        <StatusPill status={job.status} />
      </div>

      {active && (
        <>
          <div
            className="mt-3 h-2 overflow-hidden rounded-full bg-surface-2"
            role="progressbar"
            aria-label="Download progress"
            aria-valuenow={indeterminate ? undefined : Math.round(p.percent)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuetext={indeterminate ? STAGE_LABEL[job.status] : `${Math.round(p.percent)}%`}
          >
            {indeterminate ? (
              <div className={`h-full w-1/3 rounded-full animate-slide ${barTone}`} />
            ) : (
              <div
                className={`h-full rounded-full transition-[width] duration-300 ease-soft ${barTone}`}
                style={{ width: `${p.percent}%` }}
              />
            )}
          </div>
          <div className="mt-2 flex justify-between gap-3 font-mono text-data tabular-nums text-muted">
            <span className="truncate">
              {STAGE_LABEL[job.status]}
              {p.detail ? ` · ${p.detail}` : ""}
            </span>
            <span className="shrink-0">
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
            className="tap mt-1 text-sm font-semibold text-danger underline-offset-2 hover:underline"
          >
            Cancel
          </button>
        </>
      )}

      {job.status === "done" && (
        <div className="mt-4">
          <div className="flex flex-wrap items-center gap-2">
            <a
              href={api.fileUrl(job.id)}
              download={job.filename ?? undefined}
              className="tap inline-flex items-center gap-1.5 rounded-control bg-ok px-4 text-sm font-semibold text-on-ok transition-ui hover:opacity-90"
            >
              <CheckIcon className="h-4 w-4" />
              Save file{job.size_bytes ? ` · ${formatBytes(job.size_bytes)}` : ""}
            </a>
            <CopyLinkButton url={api.fileUrl(job.id)} />
            <button
              type="button"
              onClick={onNext}
              className="tap px-1 text-sm font-semibold text-ink-2 underline-offset-2 hover:underline"
            >
              Download another
            </button>
          </div>
          {job.expires_at && (
            <p className="mt-2 text-xs text-muted">
              The link works until {formatClock(job.expires_at)}. After that, download it again.
            </p>
          )}
        </div>
      )}

      {job.status === "error" && (
        <div className="mt-3">
          <p className="rounded-control bg-danger-soft px-3 py-2 text-sm text-danger">
            {job.error?.message ?? "The download failed."}
          </p>
          <button
            type="button"
            onClick={onReset}
            className="tap mt-1 text-sm font-semibold text-ink-2 underline-offset-2 hover:underline"
          >
            Try again
          </button>
        </div>
      )}

      {job.status === "cancelled" && (
        <button
          type="button"
          onClick={onReset}
          className="tap mt-1 text-sm font-semibold text-ink-2 underline-offset-2 hover:underline"
        >
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
      className="tap rounded-control border border-line px-3 text-sm font-medium text-ink-2 transition-ui hover:bg-surface-2"
    >
      {copied ? "Copied" : "Copy link"}
    </button>
  );
}

function StatusPill({ status }: { status: Job["status"] }) {
  const tone =
    status === "done"
      ? "bg-ok-soft text-ok"
      : status === "error"
        ? "bg-danger-soft text-danger"
        : status === "cancelled"
          ? "bg-surface-2 text-muted"
          : "bg-accent-soft text-accent";
  return (
    <span className={`shrink-0 rounded-md px-2 py-1 font-mono text-label uppercase ${tone}`}>
      {STAGE_LABEL[status] ?? status}
    </span>
  );
}
