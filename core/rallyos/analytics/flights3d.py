"""Shot paths in 3D for the court viewer: every flight between two contacts (or a contact and a landing) as points in metres.

One camera measures no height, so these paths are RECONSTRUCTED, not measured: the two ends are the measured court positions
(the hitter's feet, the next contact or the called landing) and the measured time between them; the height of each end is the
same prior the speed estimate uses (a contact is at about 2.5 m when the wrist was above the head, 1.2 m otherwise, the ground at
a landing). Between them:

  shuttle (`quadratic_drag`)  the flight is solved with gravity + the config's air drag (analytics/flight.py), the same solution that
                              gives the launch speed, and drawn along the line between the two ends  -> kind "physics"
  a flight no launch can explain, or a ball sport
                              a gravity-only arc between the two ends (a ball sport with a bounce in the middle for a contact
                              to contact flight) -> kind "estimate", drawn dashed and labelled as such

Coordinates are court metres (origin at the near-left corner, x across, y along the length), z up. Nothing here is a tracked 3D
position: it shows where a shot of that distance and duration could have gone.
"""

from __future__ import annotations

import math

from rallyos.analytics.flight import G, solve_launch, trajectory
from rallyos.analytics.speed import LANDING_HEIGHT, MAX_FLIGHT_S, MIN_DIST_M, MIN_FLIGHT_S, _contact, _why_not

BOUNCE_AT = 0.7           # a bouncing ball is taken to land 70% of the way along a contact-to-contact flight
BOUNCE_TIME = 0.6         # ... after 60% of its flight time (it is faster before the bounce than after)
SAMPLE_HZ = 60


def _arc(h0: float, h1: float, T: float, n: int) -> list[float]:
    """Heights at n+1 equally spaced times of a gravity-only parabola from h0 at t=0 to h1 at t=T."""
    vz = (h1 - h0 + 0.5 * G * T * T) / T
    return [h0 + vz * (T * i / n) - 0.5 * G * (T * i / n) ** 2 for i in range(n + 1)]


def _bounce_heights(h0: float, h1: float, T: float, n: int) -> list[float]:
    t1 = T * BOUNCE_TIME
    n1 = max(1, round(n * BOUNCE_TIME))
    first = _arc(h0, 0.0, t1, n1)
    second = _arc(0.0, h1, T - t1, max(1, n - n1))
    return first + second[1:]


def reconstruct(events: list[dict], fps: float, cfg: dict, frames: list[dict] | None = None) -> list[dict]:
    """One dict per flight: {rally_idx, track_id, t0, t1, kind, from, to, samples [[t, x, y, z]...], peak_z, speed_kmh, speed_err_pct, shot}."""
    proj = cfg["projectile"]
    vt = proj.get("terminal_velocity_mps") if proj.get("motion_model") == "quadratic_drag" else None
    bounces = bool(proj.get("bounces"))
    v_max = proj.get("speed_range_kmh", [1, 1000])[1] / 3.6
    by_rally: dict[int, list[dict]] = {}
    for e in events:
        by_rally.setdefault(e["rally_idx"], []).append(e)
    flights = []
    for evs in by_rally.values():
        evs.sort(key=lambda e: e["t"])
        for i, a in enumerate(evs):
            nxt = evs[i + 1] if i + 1 < len(evs) else None
            if a["type"] != "hit" or nxt is None or _why_not(a, nxt) is not None:
                continue
            T = nxt["t"] - a["t"]
            d = math.dist(a["court"], nxt["court"])
            if d < MIN_DIST_M or T < MIN_FLIGHT_S or T > MAX_FLIGHT_S:
                continue
            h0 = _contact(a, frames, fps)[0]
            h1 = LANDING_HEIGHT[0] if nxt["type"] == "landing" else _contact(nxt, frames, fps)[0]
            n = max(2, int(round(T * SAMPLE_HZ)))
            kind, heights, fracs = "estimate", None, None
            sol = solve_launch(d, T, h1 - h0, vt) if vt else None
            if sol is not None and sol[0] <= v_max:
                path = trajectory(sol[0], sol[1], T, vt, dt=T / n)
                x_end = path[-1][1] or 1e-6
                fracs = [min(1.0, max(0.0, p[1] / x_end)) for p in path]            # how far along the line, by the drag law
                heights = [h0 + p[2] + (h1 - h0 - path[-1][2]) * (p[0] / T) for p in path]    # tiny correction so the end meets h1
                kind = "physics"
            elif bounces and nxt["type"] == "hit":
                heights = _bounce_heights(h0, h1, T, n)
                fracs = [min(BOUNCE_AT, BOUNCE_AT * (i / max(1, round(n * BOUNCE_TIME)))) if i <= round(n * BOUNCE_TIME)
                         else BOUNCE_AT + (1 - BOUNCE_AT) * ((i - round(n * BOUNCE_TIME)) / max(1, n - round(n * BOUNCE_TIME))) for i in range(len(heights))]
                kind = "estimate"
            else:
                heights = _arc(h0, h1, T, n)
                fracs = [i / n for i in range(n + 1)]
            ax, ay = a["court"]
            bx, by = nxt["court"]
            samples = [[round(a["t"] + T * i / (len(heights) - 1), 3), round(ax + (bx - ax) * f, 3), round(ay + (by - ay) * f, 3), round(max(0.0, z), 3)]
                       for i, (f, z) in enumerate(zip(fracs, heights))]
            flights.append({"rally_idx": a["rally_idx"], "track_id": a.get("track_id"), "t0": round(a["t"], 3), "t1": round(nxt["t"], 3),
                            "kind": kind, "from": samples[0][1:], "to": samples[-1][1:], "samples": samples,
                            "peak_z": round(max(s[3] for s in samples), 2), "shot": a.get("shot"),
                            "speed_kmh": a.get("speed_kmh") if kind == "physics" else None, "speed_err_pct": a.get("speed_err_pct") if kind == "physics" else None})
    flights.sort(key=lambda f: f["t0"])
    return flights
