"""Court template fitting (§4.1).

Implemented now: the 4-tap fallback ("always available, always works"). The user taps the 4 outer court
corners; with the sport template from YAML that gives the homography H (image px -> court metres).
Automatic fitting (line segments + RANSAC over every sport template) will plug in behind the same output.
"""

from __future__ import annotations

import numpy as np

# Tap order expected from the UI: near-left, near-right, far-right, far-left (as seen from the camera).
TAP_ORDER = ("near_left", "near_right", "far_right", "far_left")


def court_corners(sport_cfg: dict) -> np.ndarray:
    """Outer court corners in metres, in TAP_ORDER (origin = near-left corner, y along the length)."""
    w, l = float(sport_cfg["court"]["width"]), float(sport_cfg["court"]["length"])
    return np.array([[0, 0], [w, 0], [w, l], [0, l]], dtype=float)


def homography_dlt(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Least-squares homography src -> dst (N >= 4 points), normalised so H[2,2] = 1."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    if len(src) < 4 or len(src) != len(dst):
        raise ValueError("need at least 4 point pairs")
    rows = []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _, s, vt = np.linalg.svd(np.array(rows))
    h = vt[-1].reshape(3, 3)
    if abs(h[2, 2]) < 1e-12 or s[-2] < 1e-9:
        raise ValueError("degenerate points (three or more taps on one line?)")
    return h / h[2, 2]


def apply_h(h: np.ndarray, pts) -> np.ndarray:
    pts = np.atleast_2d(np.asarray(pts, float))
    hom = np.c_[pts, np.ones(len(pts))] @ np.asarray(h, float).T
    return hom[:, :2] / hom[:, 2:3]


def homography_from_taps(taps_px, sport_cfg: dict) -> dict:
    """4 tapped corners (image px, TAP_ORDER) -> calibration block for match.json."""
    taps = np.asarray(taps_px, float)
    if taps.shape != (4, 2):
        raise ValueError("expected 4 taps as [[x, y], ...]")
    # convex, non-self-intersecting quad: the cross products of consecutive edges share one sign
    edges = [taps[(i + 1) % 4] - taps[i] for i in range(4)]
    turns = [edges[i][0] * edges[(i + 1) % 4][1] - edges[i][1] * edges[(i + 1) % 4][0] for i in range(4)]
    if not (all(c > 0 for c in turns) or all(c < 0 for c in turns)):
        raise ValueError("taps must be the 4 court corners in order: near-left, near-right, far-right, far-left")
    h = homography_dlt(taps, court_corners(sport_cfg))
    return {"method": "4-tap", "homography": h.round(10).tolist(), "focal_px": None,
            "reprojection_error_px": None,      # 4 points fit exactly; error needs extra lines (auto fit)
            "taps_px": taps.round(1).tolist()}
