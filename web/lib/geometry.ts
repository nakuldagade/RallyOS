// Homography helpers (court metres <-> image pixels).
import type { MatchJSON, Tracks, XY } from "./types";

export type Mat3 = number[][];

export function applyH(h: Mat3, x: number, y: number): XY {
  const w = h[2][0] * x + h[2][1] * y + h[2][2];
  return [(h[0][0] * x + h[0][1] * y + h[0][2]) / w, (h[1][0] * x + h[1][1] * y + h[1][2]) / w];
}

export function det3(m: Mat3): number {
  return (
    m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) -
    m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) +
    m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
  );
}

export function inv3(m: Mat3): Mat3 | null {
  const d = det3(m);
  if (!isFinite(d) || Math.abs(d) < 1e-12) return null;
  const [a, b, c] = m[0];
  const [e, f, g] = m[1];
  const [h, i, k] = m[2];
  return [
    [(f * k - g * i) / d, (c * i - b * k) / d, (b * g - c * f) / d],
    [(g * h - e * k) / d, (a * k - c * h) / d, (c * e - a * g) / d],
    [(e * i - f * h) / d, (b * h - a * i) / d, (a * f - b * e) / d],
  ];
}

function mul3(a: Mat3, b: Mat3): Mat3 {
  return a.map((row) => [0, 1, 2].map((j) => row[0] * b[0][j] + row[1] * b[1][j] + row[2] * b[2][j]));
}

/** Similarity transform that centres points and scales mean distance to sqrt(2) (Hartley normalisation). */
function normaliser(pts: XY[]): Mat3 {
  const n = pts.length;
  const cx = pts.reduce((s, p) => s + p[0], 0) / n;
  const cy = pts.reduce((s, p) => s + p[1], 0) / n;
  const d = pts.reduce((s, p) => s + Math.hypot(p[0] - cx, p[1] - cy), 0) / n || 1;
  const s = Math.SQRT2 / d;
  return [
    [s, 0, -s * cx],
    [0, s, -s * cy],
    [0, 0, 1],
  ];
}

/** Least-squares homography src -> dst (DLT with h33 = 1, normalised). */
export function fitH(src: XY[], dst: XY[]): Mat3 | null {
  if (src.length < 4) return null;
  const ts = normaliser(src);
  const td = normaliser(dst);
  const ata = Array.from({ length: 8 }, () => new Array(8).fill(0));
  const atb = new Array(8).fill(0);
  src.forEach((p, idx) => {
    const [x, y] = applyH(ts, p[0], p[1]);
    const [u, v] = applyH(td, dst[idx][0], dst[idx][1]);
    const rows: [number[], number][] = [
      [[x, y, 1, 0, 0, 0, -u * x, -u * y], u],
      [[0, 0, 0, x, y, 1, -v * x, -v * y], v],
    ];
    for (const [r, b] of rows) {
      for (let i = 0; i < 8; i++) {
        atb[i] += r[i] * b;
        for (let j = 0; j < 8; j++) ata[i][j] += r[i] * r[j];
      }
    }
  });
  // Gaussian elimination with partial pivoting
  for (let col = 0; col < 8; col++) {
    let piv = col;
    for (let r = col + 1; r < 8; r++) if (Math.abs(ata[r][col]) > Math.abs(ata[piv][col])) piv = r;
    if (Math.abs(ata[piv][col]) < 1e-12) return null;
    [ata[col], ata[piv]] = [ata[piv], ata[col]];
    [atb[col], atb[piv]] = [atb[piv], atb[col]];
    for (let r = 0; r < 8; r++) {
      if (r === col) continue;
      const f = ata[r][col] / ata[col][col];
      for (let c = col; c < 8; c++) ata[r][c] -= f * ata[col][c];
      atb[r] -= f * atb[col];
    }
  }
  const h = atb.map((b, i) => b / ata[i][i]);
  const hn: Mat3 = [
    [h[0], h[1], h[2]],
    [h[3], h[4], h[5]],
    [h[6], h[7], 1],
  ];
  const tdInv = inv3(td);
  return tdInv ? mul3(mul3(tdInv, hn), ts) : null;
}

/**
 * Court -> pixel mapping for drawing. Uses the calibration homography (px -> court) when it is valid;
 * otherwise fits one from the tracks' foot points, where each player has both a bbox and a court position.
 */
export function courtToPx(match: MatchJSON, tracks: Tracks | null): Mat3 | null {
  const h = match.calibration?.homography;
  if (h && h.length === 3) {
    const inv = inv3(h);
    if (inv) return inv;
  }
  if (!tracks) return null;
  const src: XY[] = [];
  const dst: XY[] = [];
  tracks.frames.forEach((fr, i) => {
    if (i % 3) return;
    for (const p of fr.players) {
      if (!p.court) continue;
      src.push(p.court);
      dst.push([(p.bbox[0] + p.bbox[2]) / 2, p.bbox[3]]);
    }
  });
  return fitH(src, dst);
}

/** Distance from a point to a segment (metres). */
export function pointSegDist(p: XY, a: XY, b: XY): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy || 1e-12;
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}
