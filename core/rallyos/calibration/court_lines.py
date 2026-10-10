"""Court line extraction (AGENTS.md 4.1): white-line mask (top-hat filter), line segments (probabilistic Hough),
merged into infinite lines. Pure OpenCV/numpy; nothing trained.

Everything works at a fixed working width (960 px) and positions are scaled back by the caller.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

WORK_WIDTH = 960


def background_frame(frames: list[np.ndarray]) -> np.ndarray:
    """Per-pixel median of several frames: players and the shuttle move, the court lines don't."""
    if len(frames) == 1:
        return frames[0]
    return np.median(np.stack(frames), axis=0).astype(np.uint8)


def resize_to_work(img: np.ndarray) -> tuple[np.ndarray, float]:
    h, w = img.shape[:2]
    s = WORK_WIDTH / w
    return cv2.resize(img, (WORK_WIDTH, round(h * s)), interpolation=cv2.INTER_AREA), s


def line_mask(img_bgr: np.ndarray, thickness_px: float | None = None, wide: bool = False) -> np.ndarray:
    """uint8 {0,255} mask of thin bright stripes (court lines) at the working width.

    A line is a stripe a few pixels wide that is brighter than the surface on both sides: a top-hat of the
    grey image with a structuring element wider than a line removes everything wider (floor, players), then a
    threshold relative to the strongest stripes keeps the real lines. Light-on-dark and coloured lines on
    dark floors work the same way; very low contrast courts need the 4-tap fallback.
    """
    small, _ = resize_to_work(img_bgr)
    grey = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    k = int(thickness_px or max(7, round(small.shape[1] * 0.0094))) | 1
    mask = np.zeros(grey.shape, np.uint8)
    for kk, rel in ((k, 1.0), (2 * k + 1, 1.15)) if wide else ((k, 1.0),):
        # wide=True adds a second, wider element that keeps merged bands: far-court lines 0.5-1 m apart (baseline +
        # service line) fuse into one 8-12 px stripe that the thin-line filter discards. It also keeps more clutter,
        # so it is used to check where template points land, not to find the lines themselves
        tophat = cv2.morphologyEx(grey, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kk, kk)))
        hi = float(np.percentile(tophat, 99.7))
        # measured on four real clips: true lines respond with ~40-100, the empty floor stays under ~30 (90th pct);
        # no pre-blur, which flattens 1-2 px far-court lines
        thr = float(np.clip(0.22 * hi, 20.0, 34.0)) * rel
        mask |= (tophat >= thr).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))   # drop single-pixel noise
    return mask


def _seg_params(x1, y1, x2, y2):
    """(theta in [0,pi), rho) of the infinite line through a segment; normal form x cos t + y sin t = rho."""
    dx, dy = x2 - x1, y2 - y1
    theta = (math.atan2(dy, dx) + math.pi / 2) % math.pi          # normal direction
    rho = x1 * math.cos(theta) + y1 * math.sin(theta)
    return theta, rho


def mask_distance(mask: np.ndarray) -> np.ndarray:
    """Distance (px) from every pixel to the nearest line pixel."""
    return cv2.distanceTransform(255 - mask, cv2.DIST_L2, 3)


def detect_lines(mask: np.ndarray, min_len_frac: float = 0.05, merge_deg: float = 2.0, merge_px: float = 4.0,
                 max_lines: int = 40, min_cover: float = 0.6, min_extent_frac: float = 0.07) -> list[dict]:
    """Merged infinite lines supported by white-line pixels.

    Returns [{"theta","rho","p": (x, y) point, "d": (dx, dy) unit direction, "support" (px of segment length),
    "ext": (t_min, t_max) extent along d from p, "cover": fraction of the extent that lies on line pixels}],
    strongest first. Lines whose pixels are not really continuous along their length (ad-board text and logos
    that the segment detector bridges across letters) are dropped by the `cover` check.
    """
    w = mask.shape[1]
    segs = cv2.HoughLinesP(mask, 1, np.pi / 360, threshold=40, minLineLength=int(min_len_frac * w),
                           maxLineGap=max(4, int(0.008 * w)))
    if segs is None:
        return []
    items = []
    for x1, y1, x2, y2 in segs.reshape(-1, 4):
        theta, rho = _seg_params(x1, y1, x2, y2)
        items.append({"theta": theta, "rho": rho, "len": math.hypot(x2 - x1, y2 - y1), "pts": ((x1, y1), (x2, y2))})
    items.sort(key=lambda s: -s["len"])
    groups: list[dict] = []
    tol = math.radians(merge_deg)
    for s in items:
        for g in groups:
            dth = abs(s["theta"] - g["theta"])
            dth = min(dth, math.pi - dth)
            rho = s["rho"] if dth == abs(s["theta"] - g["theta"]) else -s["rho"]
            if dth <= tol and abs(rho - g["rho"]) <= merge_px:
                g["members"].append(s)
                wt = sum(m["len"] for m in g["members"])
                g["rho"] = (g["rho"] * (wt - s["len"]) + rho * s["len"]) / wt
                break
        else:
            groups.append({"theta": s["theta"], "rho": s["rho"], "members": [s]})
    lines = []
    dt = mask_distance(mask)
    for g in groups:
        th, rho = g["theta"], g["rho"]
        d = np.array([-math.sin(th), math.cos(th)])
        n = np.array([math.cos(th), math.sin(th)])
        p0 = n * rho
        ts = [float((np.array(pt) - p0) @ d) for m in g["members"] for pt in m["pts"]]
        support = sum(m["len"] for m in g["members"])
        t0, t1 = min(ts), max(ts)
        if t1 - t0 < min_extent_frac * w:
            continue
        ss = np.linspace(t0, t1, max(8, int(t1 - t0) // 3))
        xy = p0[None, :] + ss[:, None] * d[None, :]
        ix = np.clip(np.round(xy[:, 0]).astype(int), 0, mask.shape[1] - 1)
        iy = np.clip(np.round(xy[:, 1]).astype(int), 0, mask.shape[0] - 1)
        cover = float(np.mean(dt[iy, ix] <= 2.0))
        if cover < min_cover:
            continue
        lines.append({"theta": th, "rho": rho, "p": tuple(p0), "d": tuple(d), "support": support * cover,
                      "ext": (t0, t1), "cover": round(cover, 2)})
    lines.sort(key=lambda l: -l["support"])
    return lines[:max_lines]


def line_angle_deg(line: dict) -> float:
    """Angle of the line from the image x axis, in [0, 90] (0 = horizontal, 90 = vertical)."""
    a = abs(math.degrees(math.atan2(line["d"][1], line["d"][0]))) % 180
    return min(a, 180 - a)


def intersect(l1: dict, l2: dict) -> tuple[float, float] | None:
    """Intersection of two infinite lines (image px), or None if (nearly) parallel."""
    c1, s1, c2, s2 = math.cos(l1["theta"]), math.sin(l1["theta"]), math.cos(l2["theta"]), math.sin(l2["theta"])
    det = c1 * s2 - s1 * c2
    if abs(det) < 1e-3:
        return None
    return ((l1["rho"] * s2 - s1 * l2["rho"]) / det, (c1 * l2["rho"] - l1["rho"] * c2) / det)


def union_lines(primary: list[dict], extra: list[dict], deg: float = 2.0, px: float = 5.0) -> list[dict]:
    """primary lines first, then the extra lines that are not (nearly) the same infinite line as one already kept."""
    out = list(primary)
    tol = math.radians(deg)
    for l in extra:
        dup = False
        for k in out:
            dth = abs(l["theta"] - k["theta"])
            dth = min(dth, math.pi - dth)
            rho = l["rho"] if abs(l["theta"] - k["theta"]) <= math.pi / 2 else -l["rho"]
            if dth <= tol and abs(rho - k["rho"]) <= px:
                dup = True
                break
        if not dup:
            out.append(l)
    return out
