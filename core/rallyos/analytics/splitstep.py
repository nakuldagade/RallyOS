"""Split-step detection (§4.8): did the player hop (both feet off the ground together) just before the opponent's hit?

A split-step is a small in-place hop, about 100-250 ms long, timed so the player lands as the opponent makes
contact. The ordinary pose pass samples every 3rd frame (about 8 per second), which cannot resolve it, so this
module re-reads the frames around each opponent hit at full frame rate and runs a light pose model on just the
receiving player's crop. No training anywhere: pretrained pose keypoints plus a threshold on ankle height.

The rule, in body-height units so it works at any distance from the camera:
  * both ankles rise at the same time above their own motion trend (so running up the court is not a hop), each
    by at least LIFT_MIN of the player's height (about 5 cm),
  * for at least MIN_RUN consecutive frames, with planted frames before and after (a bump that lands),
  * while the player is not running (a running stride also has both feet off the ground for an instant).
This is a detector of a plausible hop, not an official measurement: ankle keypoints jitter by a few pixels, and a
hop of 5 cm is only 4-10 px for a far player. Results are reported as "detected", with the number of shots they
are out of, and are not validated against labelled footage yet.
"""

from __future__ import annotations

import math

import numpy as np

LIFT_MIN = 0.03            # fraction of body height both ankles must rise (about 5 cm for a 1.7 m player)
MIN_RUN = 2                # consecutive frames both ankles stay lifted
MIN_SAMPLES = 6            # frames with both ankles visible needed to judge a window
MAX_RUNNING_MPS = 2.5      # faster than this the player is running to the shot, not split-stepping
WINDOW_BEFORE_S = 0.40     # look this long before the opponent's contact...
WINDOW_AFTER_S = 0.05      # ...and a hair after it (timing error of the hit)
ANKLES = (15, 16)
MIN_CONF = 0.3


HEAD_FRAMES, TAIL_FRAMES = 3, 2     # planted frames at the edges of the window that define the ankle's own path


def _lift_px(y: np.ndarray) -> np.ndarray:
    """How far above its own path an ankle is at each frame (px, > 0 = raised).

    The player's overall motion (running up the court, a lunge) makes the ankle drift in the image; a hop is a bump
    on top of that drift. A split-step is timed to land as the opponent makes contact, so the first frames of the
    window and the last ones are planted: the ankle's path is the straight line through those edge frames, and the
    lift is how far each frame sits above that line. (A free-form fit of the whole window was tried and rejected:
    over 10-12 frames it follows the hop and absorbs it.)
    """
    n = len(y)
    t = np.arange(n, dtype=float)
    idx = np.r_[0:HEAD_FRAMES, n - TAIL_FRAMES:n]
    fit = np.polyval(np.polyfit(t[idx], y[idx], 1), t)
    return fit - y


def detect_split_step(samples: list[dict], moving_mps: float | None = None) -> dict:
    """samples: [{"t", "ay": (left_y, right_y) in pixels, "h": player height in pixels}] in time order.

    A split-step is a transient: both ankles rise by LIFT_MIN of the body height for at least MIN_RUN frames, with
    planted frames (not raised) before and after, measured against the ankles' own path through the planted edge frames. Returns
    {"split_step": True | False | None, "max_lift": fraction, "run": longest raised run in frames, "n": usable
    frames, "why": reason when None or a notable False}. None = too few usable frames to judge.
    """
    ok = [s for s in samples if s.get("ay") and s.get("h", 0) > 20]
    if len(ok) < MIN_SAMPLES:
        return {"split_step": None, "max_lift": None, "run": 0, "n": len(ok), "why": "too few frames with both ankles visible"}
    scale = float(np.median([s["h"] for s in ok]))
    y = np.array([s["ay"] for s in ok], float)               # (n, 2): left, right ankle image y (down is larger)
    lift = np.stack([_lift_px(y[:, 0]), _lift_px(y[:, 1])], axis=1) / scale
    both = np.minimum(lift[:, 0], lift[:, 1])                # both feet must be up: the smaller of the two
    up = both >= LIFT_MIN
    planted = both < LIFT_MIN / 2
    best, i = 0, 0
    found = False
    while i < len(up):
        if not up[i]:
            i += 1
            continue
        j = i
        while j < len(up) and up[j]:
            j += 1
        best = max(best, j - i)
        if j - i >= MIN_RUN and planted[:i].any() and planted[j:].any():          # rose from the ground and landed
            found = True
        i = j
    out = {"split_step": found, "max_lift": round(float(both.max()), 3), "run": best, "n": len(ok)}
    if found and moving_mps is not None and moving_mps > MAX_RUNNING_MPS:
        out.update(split_step=False, why=f"moving at {moving_mps:.1f} m/s: a running stride, not a split-step")
    return out


def windows_for(opponent_hits: list[dict], fps: float, n_frames: int, limit: int = 40) -> list[dict]:
    """Frame ranges to examine: just before each opponent hit. Evenly thinned to `limit` windows to bound the cost."""
    wins = []
    for h in opponent_hits:
        f0 = max(0, int(round((h["t"] - WINDOW_BEFORE_S) * fps)))
        f1 = min(n_frames - 1, int(round((h["t"] + WINDOW_AFTER_S) * fps)))
        if f1 > f0:
            wins.append({"t_hit": h["t"], "f0": f0, "f1": f1, "event_id": h.get("id")})
    if len(wins) > limit:
        keep = np.linspace(0, len(wins) - 1, limit).round().astype(int)
        wins = [wins[i] for i in sorted(set(keep))]
    return wins


def collect_samples(video_path, detector, receiver_track_id: int, wins: list[dict], tracks_frames: list[dict],
                    pad: float = 0.35) -> dict[int, list[dict]]:
    """Read the frames of each window and run `detector` on the receiving player's crop (a few frames at a time).

    detector(frame_bgr) -> [{"bbox", "conf", "kp"}] in the crop's own pixels. Returns {window index: samples}.
    The crop comes from where the player was tracked at the end of the window (grown by `pad`), so a hop at a
    fixed place stays inside it. Returns an empty list for a window when the player cannot be located.
    """
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    out: dict[int, list[dict]] = {}
    try:
        fw, fh = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
        for wi, w in enumerate(wins):
            box = _player_box(tracks_frames, receiver_track_id, w["f0"], w["f1"])
            out[wi] = []
            if box is None:
                continue
            x1, y1, x2, y2 = box
            bw, bh = x2 - x1, y2 - y1
            cx1, cy1 = max(0, int(x1 - pad * bw)), max(0, int(y1 - pad * bh))
            cx2, cy2 = min(fw, int(x2 + pad * bw)), min(fh, int(y2 + pad * bh))
            centre = ((x1 + x2) / 2 - cx1, (y1 + y2) / 2 - cy1)
            cap.set(cv2.CAP_PROP_POS_FRAMES, w["f0"])
            for f in range(w["f0"], w["f1"] + 1):
                ok, frame = cap.read()
                if not ok:
                    break
                dets = detector(frame[cy1:cy2, cx1:cx2])
                if not dets:
                    continue
                d = min(dets, key=lambda d: math.hypot((d["bbox"][0] + d["bbox"][2]) / 2 - centre[0],
                                                       (d["bbox"][1] + d["bbox"][3]) / 2 - centre[1]))
                kp = d.get("kp")
                if not kp or any(kp[i][2] < MIN_CONF for i in ANKLES):
                    continue
                out[wi].append({"t": f / fps, "ay": (kp[ANKLES[0]][1], kp[ANKLES[1]][1]), "h": d["bbox"][3] - d["bbox"][1]})
    finally:
        cap.release()
    return out


def _player_box(frames: list[dict], track_id: int, f0: int, f1: int):
    """The player's tracked box nearest the end of the window (pose is held between sampled frames)."""
    for f in list(range(min(f1, len(frames) - 1), max(f0 - 1, -1), -1)) + list(range(f1 + 1, min(len(frames), f1 + 6))):
        p = next((q for q in frames[f]["players"] if q["track_id"] == track_id), None)
        if p:
            return p["bbox"]
    return None


def summarise(results: list[dict]) -> dict:
    """Per-player split-step stats from detect_split_step results (only windows that could be judged count)."""
    judged = [r for r in results if r["split_step"] is not None]
    if not judged:
        return {}
    hits = sum(1 for r in judged if r["split_step"])
    return {"split_step_pct": round(hits / len(judged), 2), "split_step_n": len(judged), "split_step_detected": hits}
