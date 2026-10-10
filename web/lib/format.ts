export function fmtTime(s: number): string {
  if (!isFinite(s)) return "--:--";
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  return `${m}:${sec.toFixed(1).padStart(4, "0")}`;
}

export const pct = (x: number | null | undefined, digits = 0) =>
  x === null || x === undefined ? "—" : `${(x * 100).toFixed(digits)}%`;

export const num = (x: number | null | undefined, digits = 1) =>
  x === null || x === undefined ? "—" : x.toFixed(digits);

/** A speed with its error band, never false precision (AGENTS.md rule 5). */
export function speed(kmh?: number | null, errPct?: number | null): string {
  if (kmh === null || kmh === undefined) return "—";
  return errPct ? `≈ ${Math.round(kmh)} km/h ± ${Math.round(errPct)}%` : `≈ ${Math.round(kmh)} km/h`;
}

export function shortHash(h?: string | null): string {
  if (!h || h.length < 16) return "not computed (mock)";
  return `${h.slice(0, 8)}…${h.slice(-6)}`;
}

export const confColor = (c: number) => (c >= 0.85 ? "text-emerald-500" : c >= 0.7 ? "text-amber-500" : "text-rose-500");
