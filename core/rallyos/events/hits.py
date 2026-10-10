"""Hit detection (§4.4).

trajectory_hits finds vision-only hit candidates from the ball track: a hit is an abrupt reversal with
a speed jump, while an apex is a gradual turn. It works in image pixels, so it needs no calibration.
Audio onsets (audio/onsets.py) will confirm these and add hits hidden in tracking gaps.
"""

from __future__ import annotations

import math

REF_WIDTH = 1920
REF_FPS = 25.0


def _vec(a: dict, b: dict) -> tuple[float, float]:
    return b["px"][0] - a["px"][0], b["px"][1] - a["px"][1]


def _angle(u: tuple[float, float], v: tuple[float, float]) -> float:
    nu, nv = math.hypot(*u), math.hypot(*v)
    if nu == 0 or nv == 0:
        return 0.0
    c = max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / (nu * nv)))
    return math.degrees(math.acos(c))


def trajectory_hits(balls: list[dict | None], fps: float, width: int = REF_WIDTH,
                    min_dv: float = 25.0, min_turn_deg: float = 45.0, min_gap_frames: int = 5,
                    max_bridge: int = 7) -> list[dict]:
    """Hit candidates from a per-frame ball track (tracks.json ball dicts or None).

    Works on real detections only (interpolated frames ignored). For each pair of consecutive detections
    a < b at most max_bridge frames apart, the incoming velocity (ending at a) is compared with the
    outgoing velocity (starting at b). A gap between a and b is normal at a hit: the shuttle is hidden by
    the hitter's arm and racket, or masked with the player box. A candidate needs a velocity change of at
    least min_dv px/frame (scaled to a 1920 px wide, 25 fps reference), a turn of at least min_turn_deg,
    and steady motion on both sides (rejects single outliers).
    Returns [{"frame", "t", "px", "dv", "turn_deg", "confidence"}].

    Who hit it is not decided here: in image pixels a shuttle falling onto the far player also moves down
    the screen, so near and far hits look alike. That needs court calibration + wrist positions (pose).
    """
    scale = (width / REF_WIDTH) * (REF_FPS / fps)
    real = [i for i, b in enumerate(balls) if b is not None and not b.get("interp")]
    pos = {i: balls[i]["px"] for i in real}

    def vel(i: int, j: int) -> tuple[float, float]:
        return ((pos[j][0] - pos[i][0]) / (j - i), (pos[j][1] - pos[i][1]) / (j - i))

    cands = []
    for k in range(2, len(real) - 3):
        a00, a0, a, b, b1, b2 = real[k - 2], real[k - 1], real[k], real[k + 1], real[k + 2], real[k + 3]
        gap = b - a - 1
        if gap > max_bridge or a - a0 > 3 or a0 - a00 > 3 or b1 - b > 3 or b2 - b1 > 3:
            continue
        v_prev, v_in, v_out, v_next = vel(a00, a0), vel(a0, a), vel(b, b1), vel(b1, b2)
        dv = math.hypot(v_out[0] - v_in[0], v_out[1] - v_in[1]) / scale
        turn = _angle(v_in, v_out)
        steady = _angle(v_prev, v_in) <= 45.0 and _angle(v_out, v_next) <= 45.0
        if dv < min_dv or turn < min_turn_deg or not steady:
            continue
        frame = a if gap == 0 else (a + b) // 2
        px = list(pos[a]) if gap == 0 else [round((pos[a][0] + pos[b][0]) / 2, 1), round((pos[a][1] + pos[b][1]) / 2, 1)]
        conf = min(0.9, 0.45 + dv / 250.0) * min(balls[a]["conf"], balls[b]["conf"]) ** 0.25 * (1 - 0.04 * gap)
        cands.append({"frame": frame, "t": round(frame / fps, 3), "px": px, "dv": round(dv, 1),
                      "turn_deg": round(turn, 1), "confidence": round(conf, 2)})
    hits: list[dict] = []
    for c in cands:  # one hit per contact: keep the strongest candidate within min_gap_frames
        if hits and c["frame"] - hits[-1]["frame"] < min_gap_frames:
            if c["dv"] > hits[-1]["dv"]:
                hits[-1] = c
            continue
        hits.append(c)
    return hits


def tracklet_hits(balls: list[dict | None], fps: float, width: int = REF_WIDTH, min_dv: float = 20.0,
                  min_turn_deg: float = 45.0, max_gap_s: float = 0.5) -> list[dict]:
    """Hits at tracklet boundaries: one flight ends, the next starts within max_gap_s in a new direction.

    Uses the "seg" tracklet ids written by track.ball_dp.link_candidates. The incoming velocity is fitted
    over the last 3 points of a flight and the outgoing one over the first 3 of the next, so a shuttle
    hidden by the hitter for several frames still yields a hit. Same output shape as trajectory_hits.
    """
    scale = (width / REF_WIDTH) * (REF_FPS / fps)
    segs: dict[int, list[int]] = {}
    for i, b in enumerate(balls):
        if b is not None and not b.get("interp") and "seg" in b:
            segs.setdefault(b["seg"], []).append(i)
    order = sorted(segs.values(), key=lambda idx: idx[0])
    hits = []
    for a, b in zip(order, order[1:]):
        if len(a) < 2 or len(b) < 2:
            continue
        gap = b[0] - a[-1]
        if gap > max_gap_s * fps:
            continue
        ia, ib = a[-3:], b[:3]
        pa, pb = balls[ia[0]]["px"], balls[ia[-1]]["px"]
        qa, qb = balls[ib[0]]["px"], balls[ib[-1]]["px"]
        v_in = ((pb[0] - pa[0]) / (ia[-1] - ia[0]), (pb[1] - pa[1]) / (ia[-1] - ia[0]))
        v_out = ((qb[0] - qa[0]) / (ib[-1] - ib[0]), (qb[1] - qa[1]) / (ib[-1] - ib[0]))
        dv = math.hypot(v_out[0] - v_in[0], v_out[1] - v_in[1]) / scale
        turn = _angle(v_in, v_out)
        if dv < min_dv or turn < min_turn_deg:
            continue
        frame = (a[-1] + b[0]) // 2
        conf = min(0.9, 0.45 + dv / 250.0) * (1 - 0.03 * max(0, gap - 1))
        hits.append({"frame": frame, "t": round(frame / fps, 3),
                     "px": [round((pb[0] + qa[0]) / 2, 1), round((pb[1] + qa[1]) / 2, 1)],
                     "dv": round(dv, 1), "turn_deg": round(turn, 1), "confidence": round(conf, 2)})
    return hits


def detect_hits(balls: list[dict | None], fps: float, width: int = REF_WIDTH, min_gap_frames: int = 5) -> list[dict]:
    """Union of trajectory reversals and tracklet-boundary hits, one per contact (strongest kept)."""
    merged = sorted(trajectory_hits(balls, fps, width) + tracklet_hits(balls, fps, width), key=lambda h: h["frame"])
    out: list[dict] = []
    for h in merged:
        if out and h["frame"] - out[-1]["frame"] < min_gap_frames:
            if h["dv"] > out[-1]["dv"]:
                out[-1] = h
            continue
        out.append(h)
    return out


WRISTS = (9, 10)  # COCO keypoint indices


def attribute_hits(hits: list[dict], frames: list[dict], frame_h: int, max_dist_frac: float = 0.2) -> list[dict]:
    """Who hit it: the player whose wrist is closest to the hit point (§4.4), within max_dist_frac * frame height.

    frames[t]["players"] holds tracks.json players with "kp". Adds "track_id" (or None) to each hit and
    lowers the confidence when no wrist is close enough.
    """
    out = []
    for h in hits:
        best = None
        for p in frames[h["frame"]]["players"] if h["frame"] < len(frames) else []:
            pts = [p["kp"][i] for i in WRISTS if p.get("kp") and p["kp"][i][2] > 0.3]
            if not pts:
                x1, y1, x2, y2 = p["bbox"]
                pts = [((x1 + x2) / 2, y1 + 0.3 * (y2 - y1), 0.0)]      # no wrist visible: upper body
            d = min(math.hypot(x - h["px"][0], y - h["px"][1]) for x, y, _ in pts)
            if best is None or d < best[0]:
                best = (d, p["track_id"])
        ok = best is not None and best[0] < max_dist_frac * frame_h
        out.append({**h, "track_id": best[1] if ok else None,
                    "confidence": h["confidence"] if ok else round(h["confidence"] * 0.7, 2)})
    return out
