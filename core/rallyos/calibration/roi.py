"""Image regions of interest from the 4-tap calibration: look for players and the shuttle only where they
can be. People in the stands, at the scorer's table or walking behind the court never reach the pose model,
and motion outside the court (crowd, screens) never becomes a shuttle candidate.

  players  the court floor plus a margin (sides / behind the baselines), raised to head height
  ball     the court floor plus a small margin, raised to the highest a shot can go (the air above the court)

With the self-calibrated camera the raised corners are projected exactly; without it the floor polygon is
stretched upwards by a fixed fraction of its image height.
"""

from __future__ import annotations

import numpy as np

from rallyos.calibration.template_fit import apply_h

PLAYER_MARGIN_SIDE_M = 1.0
PLAYER_MARGIN_BACK_M = 2.5
PLAYER_HEIGHT_M = 2.4          # head + raised racket
BALL_MARGIN_M = 1.0


def _hull(pts: np.ndarray) -> np.ndarray:
    import cv2

    return cv2.convexHull(np.asarray(pts, np.float32)).reshape(-1, 2)


def _box(court: dict, side: float, back: float) -> list[tuple[float, float]]:
    w, l = float(court["width"]), float(court["length"])
    return [(-side, -back), (w + side, -back), (w + side, l + back), (-side, l + back)]


def _depth(camera: dict, X: float, Y: float, Z_up: float) -> float:
    R, t = np.asarray(camera["R"], float), np.asarray(camera["t"], float)
    sign = 1.0 if (-R.T @ t)[2] > 0 else -1.0
    return float((R @ np.array([X, Y, sign * Z_up]) + t)[2])


def region(H, court: dict, frame_w: int, frame_h: int, side: float, back: float, height: float,
           camera: dict | None = None) -> np.ndarray:
    """Convex image polygon (N x 2 px) covering the court box raised from the floor to `height` metres,
    intersected with the frame. Raised corners are capped so they stay in front of the camera."""
    import cv2

    from rallyos.events.landings import project_world

    floor = _box(court, side, back)
    if camera:
        pts = []
        for x, y in floor:
            d0 = _depth(camera, x, y, 0.0)
            if d0 <= 0.5:                                    # floor corner behind the camera: skip it
                continue
            dz = _depth(camera, x, y, 1.0) - d0              # depth is linear in height
            top = height if dz >= 0 else min(height, (d0 - 0.5) / -dz)
            pts += [project_world(camera, x, y, 0.0), project_world(camera, x, y, top)]
        if len(pts) < 3:
            return np.array([[0, 0], [frame_w - 1, 0], [frame_w - 1, frame_h - 1], [0, frame_h - 1]], float)
    else:
        G = np.linalg.inv(np.asarray(H, float))          # court -> image
        base = apply_h(G, floor)
        span = base[:, 1].max() - base[:, 1].min()
        up = base.copy()
        up[:, 1] -= max(span, 0.25 * frame_h) * height / 2.0
        pts = np.vstack([base, up])
    poly = _hull(np.asarray(pts, float).clip(-1e5, 1e5))
    frame = np.array([[0, 0], [frame_w - 1, 0], [frame_w - 1, frame_h - 1], [0, frame_h - 1]], np.float32)
    area, inter = cv2.intersectConvexConvex(poly.astype(np.float32), frame)
    if area <= 0 or inter is None:
        return frame.astype(float)
    return inter.reshape(-1, 2).astype(float)


def player_region(H, cfg: dict, frame_w: int, frame_h: int, camera: dict | None = None) -> np.ndarray:
    return region(H, cfg["court"], frame_w, frame_h, PLAYER_MARGIN_SIDE_M, PLAYER_MARGIN_BACK_M,
                  PLAYER_HEIGHT_M, camera)


def ball_region(H, cfg: dict, frame_w: int, frame_h: int, camera: dict | None = None) -> np.ndarray:
    height = float(cfg["projectile"].get("max_height_m", 10.0))
    return region(H, cfg["court"], frame_w, frame_h, BALL_MARGIN_M, BALL_MARGIN_M, height, camera)


def bbox(poly: np.ndarray, frame_w: int, frame_h: int, pad: int = 16) -> tuple[int, int, int, int]:
    x1, y1 = poly.min(axis=0)
    x2, y2 = poly.max(axis=0)
    return (max(0, int(x1) - pad), max(0, int(y1) - pad), min(frame_w, int(x2) + pad), min(frame_h, int(y2) + pad))


def mask(poly: np.ndarray, frame_w: int, frame_h: int, scale: float = 1.0) -> np.ndarray:
    """uint8 mask (1 inside) at `scale` x the frame size."""
    import cv2

    m = np.zeros((int(round(frame_h * scale)), int(round(frame_w * scale))), np.uint8)
    cv2.fillConvexPoly(m, np.round(poly * scale).astype(np.int32), 1)
    return m


def cropped(detector, frame: np.ndarray, box: tuple[int, int, int, int]) -> list[dict]:
    """Run a pose detector on a crop and shift its boxes/keypoints back to full-frame pixels."""
    x1, y1, x2, y2 = box
    dets = detector(frame[y1:y2, x1:x2])
    for d in dets:
        b = d["bbox"]
        d["bbox"] = [round(b[0] + x1, 1), round(b[1] + y1, 1), round(b[2] + x1, 1), round(b[3] + y1, 1)]
        if d.get("kp"):
            d["kp"] = [[round(k[0] + x1, 1), round(k[1] + y1, 1), k[2]] if (k[0] or k[1]) else k for k in d["kp"]]
    return dets
