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
  require_auth: boolean;
  signup_enabled: boolean;
  database: "sqlite" | "postgresql" | "other";
  /** Result of a live query, not a value cached at startup. */
  database_ok: boolean;
};

export type PlaylistItemPreview = {
  id: string;
  title: string;
  duration_sec: number | null;
  thumbnail: string | null;
};

export type Info = {
  id: string;
  title: string;
  channel: string | null;
  duration_sec: number | null;
  thumbnail: string | null;
  webpage_url: string;
  is_live: boolean;
  /** Empty for a playlist: the API would have to resolve every video to know. */
  available_heights: number[];
  has_audio: boolean;
  kind: "video" | "playlist";
  playlist_id: string | null;
  /** Playlist previews only. */
  playlist_count?: number | null;
  /** True when the playlist holds more videos than the server accepts at once. */
  playlist_truncated?: boolean;
  playlist_limit?: number | null;
  items?: PlaylistItemPreview[] | null;
};

/** The address of a playlist, which is what the preview and the job endpoints take. */
export function playlistUrl(playlistId: string): string {
  return `https://www.youtube.com/playlist?list=${playlistId}`;
}

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
  video_id: string;
  url: string;
  title: string | null;
  channel: string | null;
  thumbnail: string | null;
  duration_sec: number | null;
  mode: "audio" | "video";
  format: string;
  quality: string | null;
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
  file_available: boolean;
  /** API path that streams the file from the server's download folder. */
  file_url: string | null;
  /**
   * When the server will delete the file. Null - the default - means it is
   * kept until someone deletes it, so do not tell anyone about a deadline.
   */
  expires_at: string | null;
  error: { code: string; message: string } | null;
  created_at: string;
  finished_at: string | null;
  /** Set when this download is one video of a playlist run. */
  playlist_job_id?: string | null;
  playlist_index?: number | null;
};

export type PlaylistStatus =
  | "queued"
  | "running"
  | "done"
  /** Finished, but some videos failed or were cancelled one by one. */
  | "partial"
  | "error"
  | "cancelled";

export type Playlist = {
  id: string;
  playlist_id: string;
  url: string;
  title: string | null;
  channel: string | null;
  thumbnail: string | null;
  mode: "audio" | "video";
  format: string;
  quality: string | null;
  label: string;
  status: PlaylistStatus;
  total_items: number;
  completed_items: number;
  failed_items: number;
  cancelled_items: number;
  percent: number;
  error: { code: string; message: string } | null;
  created_at: string;
  finished_at: string | null;
  /** Null in list views. Fetch the playlist by id to get its videos. */
  items: Job[] | null;
};

type TokenProvider = () => Promise<string | null>;
let tokenProvider: TokenProvider = async () => null;

export function setTokenProvider(fn: TokenProvider) {
  tokenProvider = fn;
}

const CLIENT_ID_KEY = "dm.clientId";

/**
 * Anonymous identity for this browser, so history works before sign-in.
 * Generated once, kept in localStorage, sent as X-Client-Id.
 */
export function getClientId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    let id = window.localStorage.getItem(CLIENT_ID_KEY);
    if (!id || !/^[A-Za-z0-9_-]{8,64}$/.test(id)) {
      id = crypto.randomUUID().replace(/-/g, "");
      window.localStorage.setItem(CLIENT_ID_KEY, id);
    }
    return id;
  } catch {
    return null; // private mode or storage blocked: downloads still work, history does not
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  const token = await tokenProvider();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const clientId = getClientId();
  if (clientId) headers.set("X-Client-Id", clientId);

  // A dead server, DNS failure, or blocked CORS preflight rejects with a bare
  // TypeError. Turn it into an ApiError here so every caller gets one shape and
  // one sentence, instead of each screen inventing its own wording.
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err; // caller cancelled
    throw new ApiError(0, "The server did not answer. Check your connection and try again.");
  }

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

export type AuthConfig = {
  enabled: boolean;
  signup_enabled: boolean;
  require_auth: boolean;
  anon_daily_limit: number;
  turnstile_required: boolean;
};

export type Profile = {
  id: string;
  email: string | null;
  display_name: string | null;
  role: "user" | "admin";
  daily_quota: number;
  downloads_today: number;
  email_verified: boolean;
  email_risk: string;
  created_at: string | null;
};

export type SignupRequest = {
  email: string;
  password: string;
  display_name?: string;
  turnstile_token?: string;
  redirect_to?: string;
};

export type SignupResponse = {
  user_id: string | null;
  email: string;
  confirmation_required: boolean;
  session: {
    access_token: string;
    refresh_token: string;
    expires_in?: number;
    expires_at?: number;
  } | null;
  message: string;
};

export const api = {
  health: () => request<Health>("/health"),
  authConfig: () => request<AuthConfig>("/api/v1/auth/config"),
  signup: (body: SignupRequest) =>
    request<SignupResponse>("/api/v1/auth/signup", { method: "POST", body: JSON.stringify(body) }),
  me: () => request<Profile>("/api/v1/auth/me"),
  claimHistory: () => request<{ claimed: number }>("/api/v1/auth/claim", { method: "POST" }),
  deleteAccount: () => request<void>("/api/v1/auth/me", { method: "DELETE" }),
  info: (url: string, signal?: AbortSignal) =>
    request<Info>(`/api/v1/info?url=${encodeURIComponent(url)}`, { signal }),
  createJob: (body: JobCreate) =>
    request<Job>("/api/v1/jobs", { method: "POST", body: JSON.stringify(body) }),
  getJob: (id: string) => request<Job>(`/api/v1/jobs/${id}`),
  listJobs: (limit = 10) => request<Job[]>(`/api/v1/jobs?limit=${limit}`),
  /** Stop a download that is still running. The row stays in history. */
  cancelJob: (id: string) =>
    request<void>(`/api/v1/jobs/${id}/cancel`, { method: "POST" }),
  /** Throw a finished download away: the file on the server and the history row. */
  deleteJob: (id: string) => request<void>(`/api/v1/jobs/${id}`, { method: "DELETE" }),
  fileUrl: (id: string) => `${API_URL}/api/v1/jobs/${id}/file`,

  // Playlists. Every video becomes an ordinary job, so the item files come from
  // fileUrl() above and one item can be cancelled with cancelJob(). Deleting is
  // all-or-nothing: deletePlaylist() takes the whole run away, because the
  // counts on the playlist would otherwise describe rows that had gone.
  createPlaylist: (body: JobCreate) =>
    request<Playlist>("/api/v1/playlists", { method: "POST", body: JSON.stringify(body) }),
  getPlaylist: (id: string) => request<Playlist>(`/api/v1/playlists/${id}`),
  listPlaylists: (limit = 20) => request<Playlist[]>(`/api/v1/playlists?limit=${limit}`),
  cancelPlaylist: (id: string) =>
    request<void>(`/api/v1/playlists/${id}/cancel`, { method: "POST" }),
  deletePlaylist: (id: string) =>
    request<void>(`/api/v1/playlists/${id}`, { method: "DELETE" }),
};
