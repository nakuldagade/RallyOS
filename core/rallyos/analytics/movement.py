"""Movement Intelligence (§4.8) from court positions of each player's feet."""

from __future__ import annotations

import math
import statistics

MAX_STEP_M_PER_S = 8.0      # faster than any human sprint: a bad detection, not movement


def _smooth(points: list[tuple[float, float]], k: int = 5) -> list[tuple[float, float]]:
    if len(points) < k:
        return points
    h = k // 2
    return [(statistics.median(p[0] for p in points[max(0, i - h):i + h + 1]),
             statistics.median(p[1] for p in points[max(0, i - h):i + h + 1])) for i in range(len(points))]


def movement_stats(track: list[tuple[float, tuple[float, float]]]) -> dict:
    """track = [(t_seconds, (x_m, y_m)), ...] for one player -> distance, top speed, coverage."""
    if len(track) < 2:
        return {}
    ts = [t for t, _ in track]
    pts = _smooth([p for _, p in track])
    dist = 0.0
    top = 0.0
    for i in range(1, len(pts)):
        dt = ts[i] - ts[i - 1]
        if dt <= 0:
            continue
        step = math.dist(pts[i], pts[i - 1])
        if step / dt > MAX_STEP_M_PER_S:
            continue
        dist += step
        if dt < 0.5:
            top = max(top, step / dt)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return {"distance_m": round(dist, 1), "top_speed_mps": round(top, 1),
            "coverage_m": [round(max(xs) - min(xs), 1), round(max(ys) - min(ys), 1)]}
