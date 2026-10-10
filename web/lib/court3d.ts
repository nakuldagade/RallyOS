// Types and small helpers for the 3D court viewer (Smart Courts). Court coordinates: metres, origin at the near-left corner,
// x across the width, y along the length, z up. In the three.js scene: X = x - width/2, Z = length/2 - y, Y = z (up), so the near
// baseline is toward the default camera and the far end is away from it.

export interface Flight3D {
  rally_idx: number;
  track_id: number | null;
  t0: number;
  t1: number;
  kind: "physics" | "estimate";
  from: [number, number, number];
  to: [number, number, number];
  samples: [number, number, number, number][];   // [t, x, y, z]
  peak_z: number;
  shot: string | null;
  speed_kmh: number | null;
  speed_err_pct: number | null;
}

export interface Court3DPlayer {
  track_id: number;
  player_id: string | null;
  name: string;
  side?: string | null;
  color: string;
}

export interface HeatGrid3D {
  cell: number;
  grid: number[][];                              // [row along the length][col along the width], 0..1
  frames: number;
}

export interface Scene3DData {
  match_id: string;
  date: string;
  sport: string;
  fps: number;
  duration_s: number | null;
  court: { length: number; width: number; lines: { id: string; p1: [number, number]; p2: [number, number] }[]; net: { height_center?: number; height_post?: number } };
  players: Court3DPlayer[];
  flights: Flight3D[];
  positions: Record<string, [number, number, number][]>;   // track_id -> [t, x, y]
  heat: Record<string, HeatGrid3D | null>;
  notes: { heights: string; positions: string };
}

export interface Court3DMatch {
  match_id: string;
  date: string;
  sport: string;
  duration_s: number | null;
  players: Court3DPlayer[];
}

/** One drawn thing: one player's flights, positions and heat in one match, in one colour. */
export interface Layer3D {
  id: string;                                     // e.g. "m_x:1"
  label: string;
  color: string;
  ghost?: boolean;                                // a previous match drawn lighter, for comparison
  flights: Flight3D[];
  positions: [number, number, number][];
  heat: HeatGrid3D | null;
  showHeat: boolean;
  visible: boolean;
}

/** Index of the last sample at or before t (binary search), or -1. */
export function sampleIndex(samples: number[][], t: number): number {
  let lo = 0, hi = samples.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (samples[mid][0] <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans;
}

/** Position of a player at time t, interpolated between the stored samples (held before the first and after the last). */
export function positionAt(pos: [number, number, number][], t: number): [number, number] | null {
  if (!pos.length) return null;
  const i = sampleIndex(pos, t);
  if (i < 0) return [pos[0][1], pos[0][2]];
  if (i >= pos.length - 1) return [pos[i][1], pos[i][2]];
  const a = pos[i], b = pos[i + 1];
  const u = b[0] > a[0] ? (t - a[0]) / (b[0] - a[0]) : 0;
  return [a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u];
}

/** The flight in the air at time t and the shuttle's [x, y, z] on it, or null between flights. */
export function shuttleAt(flights: Flight3D[], t: number): { flight: Flight3D; at: [number, number, number]; index: number } | null {
  const f = flights.find((x) => t >= x.t0 && t <= x.t1);
  if (!f) return null;
  const i = Math.max(0, sampleIndex(f.samples, t));
  const a = f.samples[i], b = f.samples[Math.min(i + 1, f.samples.length - 1)];
  const u = b[0] > a[0] ? (t - a[0]) / (b[0] - a[0]) : 0;
  return { flight: f, index: i, at: [a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u, a[3] + (b[3] - a[3]) * u] };
}
