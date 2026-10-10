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


# ---------------------------------------------------------------------------------------------------------
# Return to base and the fatigue trend (§4.8)
# ---------------------------------------------------------------------------------------------------------

BASE_RADIUS_M = 1.2        # "back at base" = feet within this distance of the base position
MAX_RETURN_S = 4.0         # a return slower than this is a different phase of play (a reset, a dead ball)
GRACE_S = 0.2              # a player may still arrive this long after the opponent's next contact


def base_for(cfg: dict, side: str) -> tuple[float, float]:
    """The sport's base position (given for the near side) for the near or far player (mirrored along the length)."""
    bx, by = cfg["court"]["base_position"]
    return (float(bx), float(by)) if side == "near" else (float(bx), float(cfg["court"]["length"]) - float(by))


def return_to_base(track: list[tuple[float, tuple[float, float]]], hit_times: list[float], next_contact: dict[float, float | None],
                   base: tuple[float, float], radius: float = BASE_RADIUS_M) -> dict[float, dict]:
    """For each of a player's own hits: how long until their feet are back within `radius` of base.

    track: [(t, (x, y) metres)] of the player's feet (smoothed). next_contact[t_hit]: the time of the next contact
    in the rally by anyone else (the opponent's reply), or None. Result per hit time:
    {"return_s": seconds or None, "returned": bool, "was_at_base": bool}. A player who is already at base when
    they hit has return_s = 0.0 and was_at_base = True (kept in the average: staying central is the goal).
    """
    pts = _smooth([p for _, p in track])
    ts = [t for t, _ in track]
    out: dict[float, dict] = {}
    for th in hit_times:
        end = min(th + MAX_RETURN_S, (next_contact.get(th) + GRACE_S) if next_contact.get(th) is not None else th + MAX_RETURN_S)
        idx = [i for i, t in enumerate(ts) if th - 1e-6 <= t <= end]
        if not idx:
            out[th] = {"return_s": None, "returned": False, "was_at_base": False, "why": "player not tracked after the hit"}
            continue
        hit_d = math.dist(pts[idx[0]], base)
        if hit_d <= radius:
            out[th] = {"return_s": 0.0, "returned": True, "was_at_base": True}
            continue
        done = next((i for i in idx if math.dist(pts[i], base) <= radius), None)
        if done is None:
            out[th] = {"return_s": None, "returned": False, "was_at_base": False, "why": "not back at base before the reply"}
        else:
            out[th] = {"return_s": round(ts[done] - th, 2), "returned": True, "was_at_base": False}
    return out


def return_stats(results: dict[float, dict]) -> dict:
    """Per-player summary of return_to_base() results.

    Shots hit from base (the player never left) say nothing about recovery, so they are counted separately and
    kept out of the average: avg_return_to_base_s is the mean over the shots that pulled the player away and
    were followed by a return. returned_pct is the share of those pulled-away shots after which the player was
    back at base before the reply.
    """
    if not results:
        return {}
    stayed = [t for t, r in results.items() if r.get("was_at_base")]
    pulled = {t: r for t, r in results.items() if not r.get("was_at_base")}
    out = {"return_to_base_n": len(results), "stayed_central_n": len(stayed), "pulled_away_n": len(pulled)}
    back = {t: r for t, r in pulled.items() if r["return_s"] is not None}
    if pulled:
        out["returned_pct"] = round(len(back) / len(pulled), 2)
    if back:
        out["avg_return_to_base_s"] = round(sum(r["return_s"] for r in back.values()) / len(back), 2)
        out["slowest_return_t"] = [round(t, 2) for t in sorted(back, key=lambda t: -back[t]["return_s"])[:3]]
    return out


def fatigue_trend(shots: list[dict], min_per_third: int = 3) -> dict:
    """How recovery and movement change over the match: first third of a player's shots against the last third.

    shots: time-ordered [{"t", "return_s" (or None), "speed_mps" (or None)}]. With fewer than 3 * min_per_third
    shots with a measured return, no trend is claimed (a 10 s clip cannot show fatigue).
    """
    measured = [s for s in sorted(shots, key=lambda s: s["t"]) if s.get("return_s") is not None]
    n = len(measured)
    if n < 3 * min_per_third:
        return {"enough_data": False, "n_shots": n,
                "note": f"needs at least {3 * min_per_third} shots with a measured return to compare the start with the end"}
    k = n // 3
    first, last = measured[:k], measured[-k:]

    def mean(rows, key):
        v = [r[key] for r in rows if r.get(key) is not None]
        return sum(v) / len(v) if v else None

    r0, r1 = mean(first, "return_s"), mean(last, "return_s")
    s0, s1 = mean(first, "speed_mps"), mean(last, "speed_mps")
    out = {"enough_data": True, "n_shots": n, "first_third_return_s": round(r0, 2), "last_third_return_s": round(r1, 2),
           "return_change_pct": round(100 * (r1 - r0) / r0) if r0 else None,
           "first_t": round(first[0]["t"], 2), "last_t": round(last[-1]["t"], 2)}
    if s0 and s1:
        out.update(first_third_speed_mps=round(s0, 2), last_third_speed_mps=round(s1, 2), speed_change_pct=round(100 * (s1 - s0) / s0))
    return out


def movement_speed_between(track: list[tuple[float, tuple[float, float]]], t0: float, t1: float) -> float | None:
    """Mean foot speed (m/s) over [t0, t1] from the smoothed track; None with fewer than 3 samples."""
    seg = [(t, p) for (t, p) in zip([t for t, _ in track], _smooth([p for _, p in track])) if t0 <= t <= t1]
    if len(seg) < 3:
        return None
    d = sum(math.dist(seg[i][1], seg[i - 1][1]) for i in range(1, len(seg))
            if (seg[i][0] - seg[i - 1][0]) > 0 and math.dist(seg[i][1], seg[i - 1][1]) / (seg[i][0] - seg[i - 1][0]) <= MAX_STEP_M_PER_S)
    dt = seg[-1][0] - seg[0][0]
    return d / dt if dt > 0 else None
