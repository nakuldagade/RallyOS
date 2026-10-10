"use client";

// Live mode state: one reducer for everything that arrives over SSE (and the local chunk states the capture page adds),
// so the dashboard looks the same whether the source is the mock replay or the real StreamAnalyzer.
import { useCallback, useEffect, useReducer, useRef } from "react";
import { API } from "./api";
import type { MatchEvent, PlayerRef, Rally, XY } from "./types";

export type ChunkState = "recording" | "buffered" | "uploading" | "received" | "processed" | "failed";

export interface ChunkRow {
  seq: number;
  t0: number;
  t1: number;
  state: ChunkState;
  process_s?: number;
  lag_s?: number;
  reduced_quality?: boolean;
  tries?: number;
}

export interface PositionSample {
  t: number;
  players: { track_id: number; court: XY | null; px: XY }[];
  ball: { px: XY; court: XY | null; conf?: number; interp?: boolean } | null;
}

export interface LiveStats {
  provisional?: boolean;
  rallies?: number;
  hits?: number;
  score?: { suggested?: string | null; games?: number[][]; provisional?: boolean; score_str?: string; unresolved_rallies?: number };
  per_player?: Record<string, Record<string, number | string | null>>;
  match?: Record<string, number>;
  ball?: Record<string, number | string | null>;
}

export interface LiveState {
  sessionId: string | null;
  status: "idle" | "connecting" | "live" | "finalising" | "done" | "error";
  mode: string | null;
  sport: string | null;
  chunkSeconds: number;
  calibration: { quality: string; sport?: string; precision?: number | null; method?: string | null; note?: string | null; corners_px?: XY[] | null } | null;
  chunks: ChunkRow[];
  events: (MatchEvent & { provisional?: boolean })[];
  rallies: (Rally & { provisional?: boolean })[];
  stats: LiveStats | null;
  players: PlayerRef[];
  position: PositionSample | null;
  ballTrail: XY[];                                  // recent shuttle positions in video pixels
  lag: { lag_s: number; max_lag_s: number; avg_latency_s: number } | null;
  matchId: string | null;
  error: string | null;
  lastId: number;
}

export const initialLive: LiveState = {
  sessionId: null, status: "idle", mode: null, sport: null, chunkSeconds: 5, calibration: null, chunks: [], events: [],
  rallies: [], stats: null, players: [], position: null, ballTrail: [], lag: null, matchId: null, error: null, lastId: -1,
};

export type LiveAction =
  | { type: "reset" }
  | { type: "connecting"; sessionId: string }
  | { type: "local_chunk"; chunk: ChunkRow }                      // the capture page's own chunk bookkeeping
  | { type: "server"; event: { id: number; type: string; [k: string]: any } };

const TRAIL = 14;

function upsert(chunks: ChunkRow[], row: Partial<ChunkRow> & { seq: number }): ChunkRow[] {
  const i = chunks.findIndex((c) => c.seq === row.seq);
  if (i < 0) return [...chunks, { t0: 0, t1: 0, state: "received", ...row } as ChunkRow].sort((a, b) => a.seq - b.seq);
  const next = chunks.slice();
  next[i] = { ...next[i], ...row };
  return next;
}

export function liveReducer(s: LiveState, a: LiveAction): LiveState {
  if (a.type === "reset") return initialLive;
  if (a.type === "connecting") return { ...initialLive, sessionId: a.sessionId, status: "connecting" };
  if (a.type === "local_chunk") return { ...s, chunks: upsert(s.chunks, a.chunk) };
  const e = a.event;
  if (e.id <= s.lastId) return s;                                 // reconnects replay events: ignore ones already applied
  const base = { ...s, lastId: e.id };
  switch (e.type) {
    case "session":
      return { ...base, status: "live", mode: e.mode ?? null, sport: e.sport ?? null, chunkSeconds: e.chunk_seconds ?? s.chunkSeconds,
               players: e.players ?? s.players };
    case "calibration_status":
      return { ...base, calibration: { quality: e.quality, sport: e.sport, precision: e.precision, method: e.method, note: e.note, corners_px: e.corners_px } };
    case "chunk_received":
      return { ...base, chunks: upsert(s.chunks, { seq: e.seq, t0: e.t0, t1: e.t1, state: "received" }) };
    case "chunk_processed":
      return { ...base, chunks: upsert(s.chunks, { seq: e.seq, t0: e.t0, t1: e.t1, state: "processed", process_s: e.process_s, lag_s: e.lag_s, reduced_quality: e.reduced_quality }) };
    case "positions": {
      const samples: PositionSample[] = e.samples ?? [];
      const last = samples[samples.length - 1];
      const trail = [...s.ballTrail, ...samples.filter((p) => p.ball).map((p) => p.ball!.px)].slice(-TRAIL);
      return { ...base, position: last ?? s.position, ballTrail: trail };
    }
    case "new_events": {
      const seen = new Set(s.events.map((x) => x.id));
      return { ...base, events: [...s.events, ...(e.events as MatchEvent[]).filter((x) => !seen.has(x.id))] };
    }
    case "rally_closed":
      return { ...base, rallies: [...s.rallies.filter((r) => r.idx !== e.rally.idx), e.rally].sort((x, y) => x.idx - y.idx) };
    case "stats":
      return { ...base, stats: e as unknown as LiveStats };
    case "lag":
      return { ...base, lag: { lag_s: e.lag_s, max_lag_s: e.max_lag_s, avg_latency_s: e.avg_latency_s } };
    case "finalising":
      return { ...base, status: "finalising" };
    case "finalised":
      return { ...base, status: "done", matchId: e.match_id ?? null };
    case "error":
      return { ...base, status: "error", error: e.message ?? "error" };
    default:
      return base;
  }
}

export function useLive() {
  const [state, dispatch] = useReducer(liveReducer, initialLive);
  const es = useRef<EventSource | null>(null);
  const lastId = useRef(-1);
  lastId.current = state.lastId;

  const disconnect = useCallback(() => {
    es.current?.close();
    es.current = null;
  }, []);

  /** Open the SSE stream of a session. The browser reconnects by itself and sends Last-Event-ID, so no event is lost. */
  const connect = useCallback((sessionId: string) => {
    disconnect();
    dispatch({ type: "connecting", sessionId });
    const source = new EventSource(`${API}/v1/live/sessions/${encodeURIComponent(sessionId)}/stream`);
    es.current = source;
    source.onmessage = (m) => {
      try {
        const ev = JSON.parse(m.data);
        dispatch({ type: "server", event: ev });
        if (ev.type === "finalised" || ev.type === "error") source.close();
      } catch { /* a malformed frame must not stop the stream */ }
    };
    source.onerror = () => { /* EventSource retries on its own; the dashboard shows the last known state meanwhile */ };
  }, [disconnect]);

  useEffect(() => disconnect, [disconnect]);
  return { state, dispatch, connect, disconnect };
}

/** "green" under 10 s of lag (the target), amber under 20 s, red beyond. */
export function lagTone(lag: number | undefined): "green" | "amber" | "red" | "neutral" {
  if (lag === undefined) return "neutral";
  return lag <= 10 ? "green" : lag <= 20 ? "amber" : "red";
}
