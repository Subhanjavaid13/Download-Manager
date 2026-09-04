/**
 * Typed client for the FastAPI backend.
 *
 * Phase 2: call `setTokenProvider(() => supabase.auth.getSession()...)` once at
 * startup so every request carries the user's Supabase access token.
 */

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export type Health = {
  status: "ok";
  environment: string;
  ffmpeg: boolean;
  ffmpeg_version: string | null;
  ytdlp_version: string;
  auth_enabled: boolean;
};

export type Info = {
  id: string;
  title: string;
  channel: string | null;
  duration_sec: number | null;
  thumbnail: string | null;
  webpage_url: string;
  is_live: boolean;
  available_heights: number[];
  has_audio: boolean;
  kind: "video" | "playlist";
  playlist_id: string | null;
};

export type AudioFormat = "mp3" | "m4a" | "opus";
export type AudioBitrate = 128 | 192 | 320;
export type VideoHeight = 360 | 480 | 720 | 1080 | 1440 | 2160;

export type JobCreate = {
  url: string;
  mode: "audio" | "video";
  audio_format?: AudioFormat;
  audio_bitrate?: AudioBitrate;
  video_height?: VideoHeight | null;
};

export type JobStatus =
  | "queued"
  | "fetching"
  | "downloading"
  | "processing"
  | "done"
  | "error"
  | "cancelled";

export type Job = {
  id: string;
  url: string;
  mode: "audio" | "video";
  label: string;
  status: JobStatus;
  progress: {
    stage: JobStatus;
    percent: number;
    downloaded_bytes: number;
    total_bytes: number | null;
    speed_bps: number | null;
    eta_sec: number | null;
    detail: string | null;
  };
  filename: string | null;
  size_bytes: number | null;
  error: { code: string; message: string } | null;
  created_at: number;
  finished_at: number | null;
};

type TokenProvider = () => Promise<string | null>;
let tokenProvider: TokenProvider = async () => null;

export function setTokenProvider(fn: TokenProvider) {
  tokenProvider = fn;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  const token = await tokenProvider();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    let message = res.statusText || "Request failed";
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail) && body.detail[0]?.msg) message = body.detail[0].msg;
      else if (body.error) message = String(body.error);
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  health: () => request<Health>("/health"),
  info: (url: string, signal?: AbortSignal) =>
    request<Info>(`/api/v1/info?url=${encodeURIComponent(url)}`, { signal }),
  createJob: (body: JobCreate) =>
    request<Job>("/api/v1/jobs", { method: "POST", body: JSON.stringify(body) }),
  getJob: (id: string) => request<Job>(`/api/v1/jobs/${id}`),
  cancelJob: (id: string) => request<void>(`/api/v1/jobs/${id}`, { method: "DELETE" }),
  fileUrl: (id: string) => `${API_URL}/api/v1/jobs/${id}/file`,
};
