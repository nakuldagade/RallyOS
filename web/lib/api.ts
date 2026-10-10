// Fetch wrapper for the RallyOS API. Base URL from NEXT_PUBLIC_API_URL.
// NEXT_PUBLIC_USE_MOCK=true reads /mock/*.json; otherwise match + tracks fall back to the mock
// when the backend is unreachable, so the demo never shows a blank page.
import { getToken } from "./auth";
import type { Court3DMatch, Scene3DData } from "./court3d";
import type {
  AuthUser, CoachDashboard, HighlightItem, PlayerAnalysis, CourtDetection, CoachReport, DisputeDetail, DrawMatch, Health, MatchJSON, MatchSummary, Player,
  Prediction, RatingPoint, Score, SportConfig, Suggestion, Tournament, Tracks,
} from "./types";

export const API = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
export const USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK === "true";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function mediaUrl(path?: string | null): string | null {
  if (!path) return null;
  return /^https?:\/\//.test(path) ? path : API + path;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    const token = getToken();
    const headers = token ? { ...(init?.headers as Record<string, string> | undefined), Authorization: `Bearer ${token}` } : init?.headers;
    res = await fetch(API + path, { cache: "no-store", ...init, headers });
  } catch {
    throw new ApiError(0, `Backend not reachable at ${API}. Start it with: uvicorn api.main:app --port 8000`);
  }
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

async function local<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new ApiError(res.status, `mock file ${path} missing`);
  return res.json() as Promise<T>;
}

export interface Sourced<T> {
  data: T;
  mock: boolean;
}

async function withMock<T>(live: () => Promise<T>, mockPath: string): Promise<Sourced<T>> {
  if (USE_MOCK) return { data: await local<T>(mockPath), mock: true };
  try {
    return { data: await live(), mock: false };
  } catch (e) {
    if (e instanceof ApiError && e.status === 0) return { data: await local<T>(mockPath), mock: true };
    throw e;
  }
}

const post = (body?: unknown): RequestInit =>
  body === undefined
    ? { method: "POST" }
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };

const q = encodeURIComponent;

export const api = {
  courts3dMatches: () => request<Court3DMatch[]>("/v1/courts3d/matches"),
  matchScene3d: (id: string) => request<Scene3DData>(`/v1/matches/${encodeURIComponent(id)}/scene3d`),
  courts3dScene: (id: string) => request<Scene3DData>(`/v1/courts3d/matches/${encodeURIComponent(id)}`),
  highlights: () => request<{ highlights: HighlightItem[]; matches_without: number }>("/v1/highlights"),
  login: (email: string, password: string, role: "player" | "coach") =>
    request<{ token: string; user: AuthUser }>("/v1/auth/login", post({ email, password, role })),
  registerAccount: (body: { name: string; email: string; password: string; role: "player" | "coach" }) =>
    request<{ token: string; user: AuthUser }>("/v1/auth/register", post(body)),
  me: () => request<AuthUser>("/v1/auth/me"),
  playerChat: (id: string, messages: { role: string; content: string }[]) =>
    request<{ answer: string; source: string; match_ids: string[] }>(`/v1/players/${encodeURIComponent(id)}/chat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages }) }),
  playerAnalysis: (id: string) => request<PlayerAnalysis>(`/v1/players/${encodeURIComponent(id)}/analysis`),
  coachDashboard: () => request<CoachDashboard>("/v1/coach/dashboard"),
  addToRoster: (playerId: string) => request<unknown>("/v1/coach/roster", post({ player_id: playerId })),
  removeFromRoster: (playerId: string) => request<unknown>(`/v1/coach/roster/${encodeURIComponent(playerId)}`, { method: "DELETE" }),
  assignPlayers: (matchId: string, side1: string | null, side2: string | null) =>
    request<unknown>(`/v1/matches/${encodeURIComponent(matchId)}/players`, post({ side1, side2 })),
  health: () => request<Health>("/health"),
  matches: () => request<MatchSummary[]>("/v1/matches"),
  match: (id: string) => withMock(() => request<MatchJSON>(`/v1/matches/${q(id)}`), "/mock/match.json"),
  tracks: (id: string) => withMock(() => request<Tracks>(`/v1/matches/${q(id)}/tracks`), "/mock/tracks.json"),
  report: (id: string, source = "auto") => request<CoachReport>(`/v1/matches/${q(id)}/report?source=${source}`),
  confirmScore: (id: string, body: { games: number[][]; winner_track_id?: number | null }) =>
    request<Score>(`/v1/matches/${q(id)}/score/confirm`, post(body)),
  dispute: (id: string) => request<DisputeDetail>(`/v1/disputes/${q(id)}`),
  players: () => request<Player[]>("/v1/players"),
  player: (id: string) => request<Player>(`/v1/players/${q(id)}`),
  trends: (id: string) => request<{ player_id: string; rating_history: RatingPoint[] }>(`/v1/players/${q(id)}/trends`),
  matchmaking: (id: string, radiusKm = 25) => request<Suggestion[]>(`/v1/matchmaking?player_id=${q(id)}&radius_km=${radiusKm}`),
  predict: (a: string, b: string) => request<Prediction>(`/v1/predict?a=${q(a)}&b=${q(b)}`),
  tournaments: () => request<Tournament[]>("/v1/tournaments"),
  register: (tid: number, playerId: string) => request<unknown>(`/v1/tournaments/${tid}/register`, post({ player_id: playerId })),
  draw: (tid: number) => request<DrawMatch[]>(`/v1/tournaments/${tid}/draw`, post()),
  sports: () => request<SportConfig[]>("/v1/sports"),
  sport: (name: string) => request<SportConfig>(`/v1/sports/${q(name)}`),
  upload: (file: File, sport: string, opts: { taps?: [number, number][] | null; nearName?: string; farName?: string } = {}) => {
    const fd = new FormData();
    fd.append("video", file);
    fd.append("sport", sport);
    if (opts.taps) fd.append("taps", JSON.stringify(opts.taps));
    if (opts.nearName) fd.append("near_name", opts.nearName);
    if (opts.farName) fd.append("far_name", opts.farName);
    return request<{ job_id: string }>("/v1/videos", { method: "POST", body: fd });
  },
  jobStreamUrl: (id: string) => `${API}/v1/jobs/${q(id)}`,
  /** Automatic Court Fingerprint on one frame (JPEG). sport "auto" tries every sport. */
  detectCourt: (frame: Blob, sport = "auto") => {
    const fd = new FormData();
    fd.append("frame", frame, "frame.jpg");
    fd.append("sport", sport);
    return request<CourtDetection>("/v1/calibrate", { method: "POST", body: fd });
  },
  deleteMatches: (ids: string[]) =>
    request<{ deleted: { match_id: string }[]; skipped: { match_id: string; reason: string }[] }>("/v1/matches/delete", post({ ids })),
  recalibrate: (id: string, taps: [number, number][], sport?: string) =>
    request<{ job_id: string }>(`/v1/matches/${q(id)}/recalibrate`, post({ taps, sport })),
};
