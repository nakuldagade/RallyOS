"""Event-timing speed with an error band (§4.5). The robust half of the speed story: it needs no shuttle track
in mid-flight, only the two ends of a shot and the time between them.

    speed of the shot a hit produced = distance(this contact, next contact or landing) / (time between them)

Both points are positions on the court plane (the hitter's feet through the homography; the landing point from the
line-call stage). Timing comes from the sound of the hit when there is a soundtrack (about 1 ms), else from video
frames (+-1 frame). What this number is, and is not:

  * it is the AVERAGE HORIZONTAL speed over the flight: the shuttle also moves vertically and slows down, so the
    true peak speed is higher (a lower bound for a smash); `speed_basis` says which two points were used
  * the contact point is not the feet: the racket reaches about 1 m from the body, so each contact end carries
    that as its position uncertainty, and so does the landing point (its uncertainty ellipse)
  * a speed outside the sport's plausible range, a flight that is too short or too slow to time, or missing
    positions give NO number: the app shows "insufficient tracking" rather than a guess

Flight-plane 3D reconstruction (peak speed) is on the cut list and not built.
"""

from __future__ import annotations

import math

REACH_M = 0.7            # 1-sigma gap between a player's feet and the shuttle at contact (horizontal)
MIN_FLIGHT_S = 0.12      # shorter than this and a frame of timing error is a huge share of the flight
MIN_DIST_M = 1.0
MAX_ERR = 0.6            # relative error above this: report nothing


def _sigma_t(ev: dict, fps: float) -> float:
    if "audio" in (ev.get("source") or []):
        return 0.004                                  # onset time (1 ms) + hitter-to-microphone delay model
    return 1.0 / fps                                  # a hit or landing is placed within about one frame


def _sigma_pos(ev: dict) -> float:
    if ev["type"] == "landing":
        e = ev.get("ellipse_m")
        return max(0.05, e[0] / 2.0) if e else 0.5   # ellipse semi-axis is 2 sigma
    return REACH_M


def annotate_speeds(events: list[dict], fps: float, cfg: dict) -> dict:
    """Fill speed_kmh / speed_err_pct / speed_basis on the hit events in place. Returns a summary for stats.

    events: time-ordered match events (hits with `court`, `track_id`, `source`; landings with `court`,
    `ellipse_m`, `confidence`, optional `note`), each with `rally_idx`.
    """
    lo, hi = cfg["projectile"].get("speed_range_kmh", [1, 1000])
    done = skipped = 0
    by_rally: dict[int, list[dict]] = {}
    for e in events:
        by_rally.setdefault(e["rally_idx"], []).append(e)
    for evs in by_rally.values():
        evs.sort(key=lambda e: e["t"])
        for i, a in enumerate(evs):
            if a["type"] != "hit":
                continue
            nxt = evs[i + 1] if i + 1 < len(evs) else None
            reason = _why_not(a, nxt)
            if reason is None and nxt is not None:
                d = math.dist(a["court"], nxt["court"])
                t = nxt["t"] - a["t"]
                sd = math.hypot(_sigma_pos(a), _sigma_pos(nxt))
                st = math.hypot(_sigma_t(a, fps), _sigma_t(nxt, fps))
                kmh = d / t * 3.6
                err = math.hypot(sd / d, st / t)
                if d < MIN_DIST_M or t < MIN_FLIGHT_S:
                    reason = "flight too short to time"
                elif err > MAX_ERR:
                    reason = "error band too wide"
                elif not lo <= kmh <= hi:
                    reason = "outside the plausible speed range"
                else:
                    a.update(speed_kmh=round(kmh), speed_err_pct=round(100 * err),
                             speed_basis="hit-to-landing" if nxt["type"] == "landing" else "hit-to-hit")
                    done += 1
                    continue
            a.update(speed_kmh=None, speed_err_pct=None, speed_why_not=reason or "no next contact")
            skipped += 1
    return {"computed": done, "skipped": skipped,
            "what": "average horizontal speed from contact to the next contact or landing (a lower bound of peak speed)"}


def _why_not(a: dict, nxt: dict | None) -> str | None:
    if nxt is None:
        return "no landing or next hit"
    if not a.get("court"):
        return "hitter's court position unknown (needs calibration)"
    if not nxt.get("court"):
        return "next contact position unknown"
    if nxt["type"] == "hit":
        if a.get("track_id") is None or nxt.get("track_id") is None or a["track_id"] == nxt["track_id"]:
            return "the two hits are not clearly by different players"
    elif nxt["type"] == "landing":
        if nxt.get("note") or "call" not in nxt or nxt.get("confidence", 0) < 0.5:
            return "landing not reliable enough"
    else:
        return "no landing or next hit"
    return None


def player_speed_stats(events: list[dict]) -> dict[int, dict]:
    """Per player: how many shots got a speed, the average and the fastest (still average horizontal speeds)."""
    out: dict[int, list[float]] = {}
    for e in events:
        if e["type"] == "hit" and e.get("speed_kmh") is not None and e.get("track_id") is not None:
            out.setdefault(e["track_id"], []).append(e["speed_kmh"])
    return {tid: {"shots_with_speed": len(v), "avg_shot_kmh": round(sum(v) / len(v)), "fastest_shot_kmh": max(v)}
            for tid, v in out.items()}
