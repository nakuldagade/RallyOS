"""Hit detection (§4.4).

trajectory_hits finds vision-only hit candidates from the ball track: a hit is an abrupt reversal with
a speed jump, while an apex is a gradual turn. It works in image pixels, so it needs no calibration.
fuse_audio combines them with audio onsets (audio/onsets.py): confirmed hits get sample-precise times,
and onsets inside tracking gaps add hits the shuttle path missed.
"""

from __future__ import annotations

import math

import numpy as np

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
        conf = min(0.9, 0.45 + dv / 250.0) * min(balls[a]["conf"], balls[b]["conf"]) ** 0.25 * max(0.1, 1 - 0.04 * gap)
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
        conf = min(0.9, 0.45 + dv / 250.0) * max(0.1, 1 - 0.03 * max(0, gap - 1))
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


def _hitter(frames: list[dict], frame: int, track_id) -> dict | None:
    if track_id is None or not 0 <= frame < len(frames):
        return None
    return next((p for p in frames[frame]["players"] if p["track_id"] == track_id), None)


def _delay(frames: list[dict], frame: int, track_id, camera_m, contact_h: float) -> float | None:
    """Speed-of-sound delay from the hitter's court position to the camera, or None if unknown."""
    p = _hitter(frames, frame, track_id)
    if camera_m is None or p is None or not p.get("court"):
        return None
    cx, cy, cz = camera_m
    return math.dist((p["court"][0], p["court"][1], contact_h), (cx, cy, cz)) / 343.0


def fuse_audio(hits: list[dict], onsets: list[dict], fps: float, frames: list[dict], camera_m=None,
               allow_audio_only: bool = True, min_gap_s: float = 0.15, contact_h: float = 1.5,
               min_audio_only_conf: float = 0.6) -> tuple[list[dict], dict]:
    """Combine vision hit candidates (after attribute_hits) with audio onsets (§4.4).

    1. A/V sync: phone videos can carry an audio/video offset. With >= 3 onsets near a vision hit, the
       median residual (after the sound delay) is that offset; it is removed from every onset.
    2. Match onsets to vision hits one-to-one within ~2.5 frames. A match is a confirmed hit: its time comes
       from the audio (sample precise, minus distance(hitter, camera) / 343 when the camera is calibrated)
       and the two confidences combine.
    3. Vision hits with no sound are kept but discounted. Onsets with no vision hit (shuttle hidden or
       blurred) become audio-only hits when the sport has no bounces (a bounce sounds like a hit) and the
       onset is strong; the hitter is inferred from alternation and flagged.
    Returns (time-ordered hits, info for stats.audio).
    """
    tol = max(2.5 / fps, 0.06)
    for h in hits:
        h.setdefault("source", ["vision"])
    info = {"onsets": len(onsets), "matched": 0, "audio_only": 0, "vision_only": len(hits),
            "av_offset_s": 0.0, "sound_delay_corrected": camera_m is not None, "mean_sound_delay_ms": None}
    if not onsets:
        return sorted(hits, key=lambda h: h["t"]), info

    def corr(h):
        d = _delay(frames, h["frame"], h.get("track_id"), camera_m, contact_h)
        return d or 0.0

    near = []
    for o in onsets:
        best = min(hits, key=lambda h: abs(o["t"] - corr(h) - h["t"]), default=None)
        if best is not None and abs(o["t"] - corr(best) - best["t"]) < 0.25:
            near.append(o["t"] - corr(best) - best["t"])
    offset = float(np.median(near)) if len(near) >= 3 else 0.0
    info["av_offset_s"] = round(offset, 3)

    pairs = sorted(((abs(o["t"] - offset - corr(h) - h["t"]), oi, hi)
                    for oi, o in enumerate(onsets) for hi, h in enumerate(hits)), key=lambda x: x[0])
    used_o, used_h, out, delays = set(), set(), [], []
    for dt, oi, hi in pairs:
        if dt > tol or oi in used_o or hi in used_h:
            continue
        used_o.add(oi), used_h.add(hi)
        h, o = hits[hi], onsets[oi]
        d = _delay(frames, h["frame"], h.get("track_id"), camera_m, contact_h)
        if d is not None:
            delays.append(d)
        t = o["t"] - offset - (d or 0.0)
        out.append({**h, "t": round(t, 3), "frame": min(len(frames) - 1, max(0, round(t * fps))),
                    "t_audio": o["t"], "sound_delay_ms": round(d * 1000, 1) if d is not None else None,
                    "confidence": round(min(0.97, 1 - (1 - h["confidence"]) * (1 - o["confidence"])), 2),
                    "source": ["audio", "vision"]})
    for hi, h in enumerate(hits):
        if hi not in used_h:
            out.append({**h, "confidence": round(h["confidence"] * 0.8, 2), "source": ["vision"]})
    info["matched"] = len(used_o)
    info["vision_only"] = len(hits) - len(used_h)

    if allow_audio_only:
        for oi, o in enumerate(onsets):
            if oi in used_o or o["confidence"] < min_audio_only_conf:
                continue
            t = o["t"] - offset
            if any(abs(t - h["t"]) < min_gap_s for h in out):
                continue
            f = min(len(frames) - 1, max(0, round(t * fps)))
            ball = frames[f].get("ball") if frames else None
            out.append({"frame": f, "t": round(t, 3), "px": ball["px"] if ball else None, "dv": 0.0, "turn_deg": None,
                        "track_id": None, "t_audio": o["t"], "sound_delay_ms": None,
                        "confidence": round(0.6 * o["confidence"], 2), "source": ["audio"]})
            info["audio_only"] += 1
    out.sort(key=lambda h: h["t"])

    # singles: hits alternate, so a hit with no attributed hitter gets the other player of a neighbour
    ids = {p["track_id"] for fr in frames for p in fr["players"]}
    if ids and ids <= {1, 2} and len(ids) == 2:
        for i, h in enumerate(out):
            if h.get("track_id") is not None:
                continue
            prev = next((x["track_id"] for x in reversed(out[:i]) if x.get("track_id") is not None), None)
            nxt = next((x["track_id"] for x in out[i + 1:] if x.get("track_id") is not None), None)
            guess = (3 - prev) if prev else (3 - nxt) if nxt else None
            if guess is not None:
                h["track_id"], h["hitter_inferred"] = guess, True
                if "audio" in h["source"] and h.get("sound_delay_ms") is None:
                    d = _delay(frames, h["frame"], guess, camera_m, contact_h)
                    if d is not None:
                        h["t"], h["sound_delay_ms"] = round(h["t"] - d, 3), round(d * 1000, 1)
                        h["frame"] = min(len(frames) - 1, max(0, round(h["t"] * fps)))
    if delays:
        info["mean_sound_delay_ms"] = round(1000 * sum(delays) / len(delays), 1)
    return out, info
