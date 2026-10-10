"""Shot speed with an error band (§4.5). It needs no shuttle track in mid-flight, only the two ends of a shot and the time
between them, and for a shuttle it solves for the speed at the racket, not the average over the flight.

    inputs: horizontal distance d between this contact and the next contact or landing (the hitter's feet and the landing
            point through the homography), the time T between them (sound when there is a soundtrack, else video frames),
            and the heights of the two ends (the wrist above the head or not, from body pose; the ground for a landing)

  * shuttle (`quadratic_drag` in the sport config): the LAUNCH speed, i.e. the speed at the moment of contact, found by
    solving the flight with gravity and the config's air drag (see analytics/flight.py for the equations and why the plain
    distance / time is 2-4 times too low for a fast shot). `avg_speed_kmh` keeps the plain average for reference.
  * ball sports (`ballistic_drag`, bounces and walls): the AVERAGE horizontal speed over the flight, a lower bound, as before.

What the number is, and is not:
  * the band is one standard deviation of distance, timing and contact-height errors combined; because drag makes
    launch speed grow like exp(k d), the band on a shuttle is wide (often +-20-40%), and that is the honest answer
  * the contact point is not the feet (the racket reaches about 0.7 m from the body), and the landing point carries its
    uncertainty ellipse; a hit time found from the shuttle track can be a frame or two off
  * a flight that no launch up to the sport's speed limit can produce (a 10 m flight in 0.15 s is faster than any smash ever
    recorded), a flight too short or too slow to time, or missing positions give NO number, never a guess

Flight-plane 3D reconstruction from the image track is still on the cut list.
"""

from __future__ import annotations

import math

from rallyos.analytics.flight import solve_launch

REACH_M = 0.7            # 1-sigma gap between a player's feet and the shuttle at contact (horizontal)
MIN_FLIGHT_S = 0.12      # shorter than this and a frame of timing error is a huge share of the flight
MIN_DIST_M = 1.0
MAX_ERR = 0.6            # relative error above this: report nothing
FASTEST_MAX_ERR = 0.40   # a shot is only called the fastest when its own band is at most +-40%
MAX_FLIGHT_S = 2.4
VIDEO_FRAMES_SIGMA = 1.0  # a hit or landing time from video is placed within about one frame (an assumption: not yet checked against labelled footage)
# height of the shuttle at the racket, metres (1 sigma): above the head / not / unknown. The camera cannot measure it.
CONTACT_HEIGHT = {True: (2.5, 0.4), False: (1.2, 0.5), None: (1.6, 0.8)}
LANDING_HEIGHT = (0.0, 0.05)


def _sigma_t(ev: dict, fps: float) -> float:
    if "audio" in (ev.get("source") or []):
        return 0.004                                  # onset time (1 ms) + hitter-to-microphone delay model
    return VIDEO_FRAMES_SIGMA / fps                   # a hit or landing is placed within about one frame


def _sigma_pos(ev: dict) -> float:
    if ev["type"] == "landing":
        e = ev.get("ellipse_m")
        return max(0.05, e[0] / 2.0) if e else 0.5   # ellipse semi-axis is 2 sigma
    return REACH_M


def _contact(ev: dict, frames: list[dict] | None, fps: float) -> tuple[float, float]:
    """(height, sigma) of the shuttle at a hit: the wrist above the head (overhead) or not, from pose at that frame."""
    flag = None
    if frames and ev.get("track_id") is not None:
        from rallyos.analytics.shots import wrist_above_head

        flag = wrist_above_head(frames, round(ev["t"] * fps), ev["track_id"])
    return CONTACT_HEIGHT[flag]


def _launch(d: float, t: float, sd: float, st: float, h0: tuple, h1: tuple, vt: float, v_max: float):
    """(launch m/s, angle rad, relative 1-sigma band, why-not). The flight is solved at the measurement and again with each of
    distance, time and height moved one standard deviation each way; the three effects are independent errors, so they add in
    quadrature (first-order error propagation through the solver)."""
    dz = h1[0] - h0[0]
    sz = math.hypot(h0[1], h1[1])
    centre = solve_launch(d, t, dz, vt)
    if centre is None or centre[0] > v_max:
        return None, None, None, "distance and flight time do not fit a real shot (timing or position error)"
    v = float(centre[0])
    var = 0.0
    for dd, dt_, dzz in ((sd, 0.0, 0.0), (0.0, st, 0.0), (0.0, 0.0, sz)):
        up = solve_launch(max(0.3, d + dd), max(0.06, t + dt_), dz + dzz, vt)
        dn = solve_launch(max(0.3, d - dd), max(0.06, t - dt_), dz - dzz, vt)
        if up is None and dn is None:                    # one standard deviation of this input already leaves the physical shots
            return None, None, None, "error band too wide"
        spread = abs(float(up[0]) - float(dn[0])) / 2.0 if (up is not None and dn is not None) else abs(float((up or dn)[0]) - v)
        var += spread * spread
    return v, float(centre[1]), math.sqrt(var) / v, None


def annotate_speeds(events: list[dict], fps: float, cfg: dict, frames: list[dict] | None = None) -> dict:
    """Fill speed_kmh / speed_err_pct / speed_basis (and avg_speed_kmh, launch_angle_deg) on the hit events in place.
    Returns a summary for stats.

    events: time-ordered match events (hits with `court`, `track_id`, `source`; landings with `court`,
    `ellipse_m`, `confidence`, optional `note`), each with `rally_idx`. frames: the per-frame player poses, used to tell an
    overhead contact from a low one (optional: without them the contact height is a wide guess and the band says so).
    """
    proj = cfg["projectile"]
    lo, hi = proj.get("speed_range_kmh", [1, 1000])
    vt = proj.get("terminal_velocity_mps") if proj.get("motion_model") == "quadratic_drag" else None
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
                avg = d / t * 3.6
                basis = "hit-to-landing" if nxt["type"] == "landing" else "hit-to-hit"
                if d < MIN_DIST_M or t < MIN_FLIGHT_S:
                    reason = "flight too short to time"
                elif vt and t > MAX_FLIGHT_S:
                    reason = "flight too long to time"
                elif vt:
                    h1 = LANDING_HEIGHT if nxt["type"] == "landing" else _contact(nxt, frames, fps)
                    v, theta, err, reason = _launch(d, t, sd, st, _contact(a, frames, fps), h1, vt, hi / 3.6)
                    if reason is None and err > MAX_ERR:
                        reason = "error band too wide"
                    elif reason is None and v * 3.6 < lo:
                        reason = "outside the plausible speed range"
                    elif reason is None:
                        a.update(speed_kmh=round(v * 3.6), speed_err_pct=round(100 * err), speed_basis=basis, speed_kind="launch",
                                 avg_speed_kmh=round(avg), launch_angle_deg=round(math.degrees(theta)))
                        done += 1
                        continue
                else:
                    err = math.hypot(sd / d, st / t)
                    if err > MAX_ERR:
                        reason = "error band too wide"
                    elif not lo <= avg <= hi:
                        reason = "outside the plausible speed range"
                    else:
                        a.update(speed_kmh=round(avg), speed_err_pct=round(100 * err), speed_basis=basis, speed_kind="average",
                                 avg_speed_kmh=round(avg))
                        done += 1
                        continue
            a.update(speed_kmh=None, speed_err_pct=None, speed_why_not=reason or "no next contact")
            skipped += 1
    what = ("launch speed at the racket, from the distance, the flight time and air drag (gravity + the config's quadratic drag); "
            "the band covers distance, timing and contact-height errors" if vt else
            "average horizontal speed from contact to the next contact or landing (a lower bound of peak speed)")
    return {"computed": done, "skipped": skipped, "what": what, "kind": "launch" if vt else "average"}


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
    """Per player: how many shots got a speed, the average, and the fastest. The fastest is picked only among shots whose own
    error band is at most +-40%: the maximum of many noisy numbers would otherwise be the most mistimed one."""
    out: dict[int, list[dict]] = {}
    for e in events:
        if e["type"] == "hit" and e.get("speed_kmh") is not None and e.get("track_id") is not None:
            out.setdefault(e["track_id"], []).append(e)
    stats = {}
    for tid, shots in out.items():
        speeds = [e["speed_kmh"] for e in shots]
        stats[tid] = {"shots_with_speed": len(shots), "avg_shot_kmh": round(sum(speeds) / len(speeds))}
        sure = [e for e in shots if (e.get("speed_err_pct") or 0) <= 100 * FASTEST_MAX_ERR]
        if sure:
            best = max(sure, key=lambda e: e["speed_kmh"])
            stats[tid].update(fastest_shot_kmh=best["speed_kmh"], fastest_shot_err_pct=best["speed_err_pct"], fastest_shot_t=best["t"])
    return stats
