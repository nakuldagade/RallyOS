// Court geometry helpers. Sport configs come from the API (core/rallyos/sports/*.yaml);
// BADMINTON is an offline fallback so the match page still draws a court without the backend.
import type { SportConfig, Tracks, XY } from "./types";

export const BADMINTON: SportConfig = {
  sport: "badminton",
  display_name: "Badminton",
  court: {
    length: 13.4,
    width: 6.1,
    base_position: [3.05, 3.4],
    lines: [
      { id: "baseline_near", p1: [0, 0], p2: [6.1, 0] },
      { id: "long_service_dbl_n", p1: [0, 0.76], p2: [6.1, 0.76] },
      { id: "short_service_n", p1: [0, 4.72], p2: [6.1, 4.72] },
      { id: "net", p1: [0, 6.7], p2: [6.1, 6.7] },
      { id: "short_service_f", p1: [0, 8.68], p2: [6.1, 8.68] },
      { id: "long_service_dbl_f", p1: [0, 12.64], p2: [6.1, 12.64] },
      { id: "baseline_far", p1: [0, 13.4], p2: [6.1, 13.4] },
      { id: "sideline_dbl_left", p1: [0, 0], p2: [0, 13.4] },
      { id: "sideline_dbl_right", p1: [6.1, 0], p2: [6.1, 13.4] },
      { id: "singles_left", p1: [0.46, 0], p2: [0.46, 13.4] },
      { id: "singles_right", p1: [5.64, 0], p2: [5.64, 13.4] },
      { id: "centre_near", p1: [3.05, 0], p2: [3.05, 4.72] },
      { id: "centre_far", p1: [3.05, 8.68], p2: [3.05, 13.4] },
    ],
  },
  net: { height_center: 1.524 },
  projectile: { kind: "shuttle", size_m: 0.065, bounces: false },
  scoring: { type: "rally_point", points_to_win: 21 },
};

export interface HeatGrid {
  cell: number;
  grid: number[][]; // [row along length][col along width], normalised 0..1
}

/** Court-coverage heatmap for one player from tracks.json court positions (up to frame `upto` if given). */
export function heatmap(tracks: Tracks, trackId: number, sport: SportConfig, cell = 0.5, upto?: number): HeatGrid {
  const rows = Math.ceil(sport.court.length / cell);
  const cols = Math.ceil(sport.court.width / cell);
  const grid = Array.from({ length: rows }, () => new Array(cols).fill(0));
  const frames = upto === undefined ? tracks.frames : tracks.frames.slice(0, upto + 1);
  for (const fr of frames) {
    const p = fr.players.find((pl) => pl.track_id === trackId);
    if (!p?.court) continue;
    const r = Math.floor(p.court[1] / cell);
    const c = Math.floor(p.court[0] / cell);
    if (r >= 0 && r < rows && c >= 0 && c < cols) grid[r][c] += 1;
  }
  const max = Math.max(1, ...grid.flat());
  return { cell, grid: grid.map((row) => row.map((v) => v / max)) };
}

// ---- court zones (same rules as core/rallyos/analytics/movement.py zone_of) ----
type Band = [string, number, number];

function depthBands(sport: SportConfig): Band[] {
  const half = sport.court.length / 2;
  const bands: Band[] = Object.entries(sport.court.zones ?? {})
    .filter(([, v]) => v.y_from_net_m)
    .map(([k, v]) => [k, v.y_from_net_m![0], v.y_from_net_m![1]] as Band);
  return (bands.length ? bands : [["front", 0, half / 3], ["mid", half / 3, (2 * half) / 3], ["rear", (2 * half) / 3, half]] as Band[])
    .sort((a, b) => a[1] - b[1]);
}

/** "rear-left", "front-centre", ... from the player's point of view (facing the net); null in the other half. */
export function zoneOf(c: XY, sport: SportConfig, side: "near" | "far"): string | null {
  const { width: w, length: l } = sport.court;
  const d0 = side === "near" ? l / 2 - c[1] : c[1] - l / 2;
  if (d0 < -0.5) return null;
  const d = Math.max(0, d0);
  const bands = depthBands(sport);
  const depth = (bands.find(([, a, b]) => a <= d && d < b) ?? bands[bands.length - 1])[0];
  const u = side === "near" ? c[0] / w : 1 - c[0] / w;
  return `${depth}-${u < 1 / 3 ? "left" : u < 2 / 3 ? "centre" : "right"}`;
}

/** Court rectangle (metres) of a zone name for a side, for drawing. */
export function zoneRect(zone: string, sport: SportConfig, side: "near" | "far"): { x0: number; x1: number; y0: number; y1: number } | null {
  const [depth, lat] = zone.split("-");
  const band = depthBands(sport).find((b) => b[0] === depth);
  const li = ["left", "centre", "right"].indexOf(lat);
  if (!band || li < 0) return null;
  const { width: w, length: l } = sport.court;
  const i = side === "near" ? li : 2 - li;
  const [x0, x1] = [(i * w) / 3, ((i + 1) * w) / 3];
  const [y0, y1] = side === "near" ? [l / 2 - band[2], l / 2 - band[1]] : [l / 2 + band[1], l / 2 + band[2]];
  return { x0, x1, y0: Math.max(0, y0), y1: Math.min(l, y1) };
}

export interface ZoneShare { zone: string; pct: number }

/** Share of tracked frames per zone for one player (up to frame `upto` if given), most first. */
export function zoneTime(tracks: Tracks, trackId: number, side: "near" | "far", sport: SportConfig, upto?: number): ZoneShare[] {
  const counts = new Map<string, number>();
  const frames = upto === undefined ? tracks.frames : tracks.frames.slice(0, upto + 1);
  for (const fr of frames) {
    const p = fr.players.find((pl) => pl.track_id === trackId);
    const z = p?.court ? zoneOf(p.court, sport, side) : null;
    if (z) counts.set(z, (counts.get(z) ?? 0) + 1);
  }
  const n = [...counts.values()].reduce((a, b) => a + b, 0);
  return [...counts.entries()].map(([zone, c]) => ({ zone, pct: c / Math.max(1, n) })).sort((a, b) => b.pct - a.pct);
}

export function sportLabel(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}

export function scoringSummary(s: SportConfig): string {
  const sc = s.scoring;
  const n = (k: string) => (sc[k] as number | undefined) ?? undefined;
  if (sc.type === "game_set") return `Points → games → sets, best of ${2 * (n("sets_to_win") ?? 2) - 1}, tiebreak at ${n("tiebreak_at") ?? 6}-all`;
  const games = n("games_to_win");
  const base = `${sc.type === "side_out" ? "Side-out" : "Rally point"} to ${n("points_to_win")}, win by ${n("win_by") ?? 2}`;
  return `${base}${n("cap") ? `, cap ${n("cap")}` : ""}${games ? `, best of ${2 * games - 1}` : ""}`;
}
