// Court geometry helpers. Sport configs come from the API (core/rallyos/sports/*.yaml);
// BADMINTON is an offline fallback so the match page still draws a court without the backend.
import type { SportConfig, Tracks } from "./types";

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

/** Court-coverage heatmap for one player from tracks.json court positions. */
export function heatmap(tracks: Tracks, trackId: number, sport: SportConfig, cell = 0.5): HeatGrid {
  const rows = Math.ceil(sport.court.length / cell);
  const cols = Math.ceil(sport.court.width / cell);
  const grid = Array.from({ length: rows }, () => new Array(cols).fill(0));
  for (const fr of tracks.frames) {
    const p = fr.players.find((pl) => pl.track_id === trackId);
    if (!p?.court) continue;
    const r = Math.floor(p.court[1] / cell);
    const c = Math.floor(p.court[0] / cell);
    if (r >= 0 && r < rows && c >= 0 && c < cols) grid[r][c] += 1;
  }
  const max = Math.max(1, ...grid.flat());
  return { cell, grid: grid.map((row) => row.map((v) => v / max)) };
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
