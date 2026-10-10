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


def _depth_bands(cfg: dict) -> list[tuple[str, float, float]]:
    """Depth bands measured from the net: the sport's zones (front/mid/rear) if given, else thirds."""
    half = float(cfg["court"]["length"]) / 2
    zones = cfg["court"].get("zones") or {}
    bands = [(k, *map(float, v["y_from_net_m"])) for k, v in zones.items() if "y_from_net_m" in v]
    if not bands:
        bands = [("front", 0.0, half / 3), ("mid", half / 3, 2 * half / 3), ("rear", 2 * half / 3, half)]
    return sorted(bands, key=lambda b: b[1])


def zone_of(court_xy: tuple[float, float], cfg: dict, side: str) -> str | None:
    """'rear-left', 'front-centre', ... from the player's point of view (facing the net)."""
    w, l = float(cfg["court"]["width"]), float(cfg["court"]["length"])
    x, y = court_xy
    d = (l / 2 - y) if side == "near" else (y - l / 2)        # distance from the net into the own half
    if d < -0.5:
        return None                                            # in the opponent's half: not counted
    d = max(0.0, d)
    bands = _depth_bands(cfg)
    depth = next((n for n, a, b in bands if a <= d < b), bands[-1][0])
    u = x / w if side == "near" else 1 - x / w                 # 0 = player's left
    lat = "left" if u < 1 / 3 else "centre" if u < 2 / 3 else "right"
    return f"{depth}-{lat}"


def zone_time(points: list[tuple[float, float]], cfg: dict, side: str) -> dict:
    """Share of tracked time in each zone of the player's own half, and the zone they are in most."""
    counts: dict[str, int] = {}
    for p in points:
        z = zone_of(p, cfg, side)
        if z:
            counts[z] = counts.get(z, 0) + 1
    n = sum(counts.values())
    if not n:
        return {}
    pct = {k: round(v / n, 3) for k, v in sorted(counts.items(), key=lambda kv: -kv[1])}
    top = next(iter(pct))
    return {"zone_pct": pct, "most_zone": top, "most_zone_pct": pct[top]}
