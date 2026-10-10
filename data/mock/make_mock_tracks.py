"""Generate data/mock/tracks.json: a few seconds of synthetic singles badminton motion (AGENTS.md §11.3).

    python data/mock/make_mock_tracks.py

Players drift around their base positions, the shuttle flies back and forth between
them, and a short gap is filled with interpolated (lower-confidence) frames, so the
web overlay has every case to draw. Writes to data/mock/ and web/public/mock/.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

FPS = 60
SECONDS = 5
W, H = 1920, 1080
ROOT = Path(__file__).resolve().parents[2]

# Synthetic camera: badminton court corners (m) -> image px, behind-baseline view.
COURT = np.array([[0, 0], [6.10, 0], [6.10, 13.40], [0, 13.40]], float)
PX = np.array([[560, 1000], [1360, 1000], [1180, 300], [740, 300]], float)


def homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    rows = []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _, _, vt = np.linalg.svd(np.array(rows))
    h = vt[-1].reshape(3, 3)
    return h / h[2, 2]


HOM = homography(COURT, PX)


def to_px(x: float, y: float) -> tuple[float, float]:
    p = HOM @ np.array([x, y, 1.0])
    return p[0] / p[2], p[1] / p[2]


# COCO-17 keypoints as (dx, dy) fractions of the bbox (dx from centre, dy from top).
SKELETON = [(0, .06), (-.04, .04), (.04, .04), (-.08, .06), (.08, .06),          # nose, eyes, ears
            (-.22, .2), (.22, .2), (-.3, .36), (.3, .36), (-.32, .5), (.32, .5),  # shoulders, elbows, wrists
            (-.14, .52), (.14, .52), (-.16, .75), (.16, .75), (-.16, .98), (.16, .98)]  # hips, knees, ankles


def player(track_id: int, cx: float, cy: float, t: float) -> dict:
    fx, fy = to_px(cx, cy)
    height = 120 + 230 * (fy - 300) / 700          # nearer -> taller
    width = height * 0.45
    x1, y1, x2, y2 = fx - width / 2, fy - height, fx + width / 2, fy
    swing = 0.15 * math.sin(2 * math.pi * t)       # racket-arm swing on the right wrist
    kp = []
    for i, (dx, dy) in enumerate(SKELETON):
        if i == 10:
            dy -= swing
        kp.append([round(fx + dx * width * 2, 1), round(y1 + dy * height, 1), 0.9])
    return {"track_id": track_id, "bbox": [round(v, 1) for v in (x1, y1, x2, y2)],
            "court": [round(cx, 2), round(cy, 2)], "kp": kp}


def main() -> None:
    frames = []
    flight = 1.0                                   # seconds per shuttle flight
    for f in range(FPS * SECONDS):
        t = f / FPS
        near = (3.05 + 1.2 * math.sin(0.9 * t), 3.4 + 0.8 * math.sin(1.3 * t + 1))
        far = (3.05 + 1.0 * math.sin(0.7 * t + 2), 10.0 + 0.9 * math.sin(1.1 * t))
        k, u = divmod(t, flight)
        u /= flight
        a, b = (far, near) if int(k) % 2 == 0 else (near, far)
        ax, ay = to_px(*a)
        bx, by = to_px(*b)
        bx_px = ax + (bx - ax) * u
        by_px = ay + (by - ay) * u - 260 * math.sin(math.pi * u) - 160   # arc above the hitters
        ball = {"px": [round(bx_px, 1), round(by_px, 1)], "court": None, "conf": 0.8, "interp": False}
        if 150 <= f < 158:                         # occluded: physics-filled, flagged
            ball.update(conf=0.35, interp=True)
        elif 200 <= f < 204:                       # lost entirely
            ball = None
        frames.append({"f": f, "players": [player(1, *near, t), player(2, *far, t)], "ball": ball})

    out = json.dumps({"fps": FPS, "frames": frames}, separators=(",", ":"))
    for path in (ROOT / "data/mock/tracks.json", ROOT / "web/public/mock/tracks.json"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(out, encoding="utf-8")
        print(f"wrote {path} ({len(out) // 1024} KB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
