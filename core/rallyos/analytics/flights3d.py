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

Which flights are drawn: EVERY hit gets one (a viewer must not show only the shots that happened to be tracked well). A hit's flight runs
to the next event of its rally: the next hit, or a called landing. Where something is missing the flight is still drawn, but as an
estimate (dashed) and it says how it was placed (`placement`):
  measured   both ends are measured: the hit's court position (or its hitter's tracked position at that frame) and the next contact
             or the called landing (or the receiver's tracked position at the next hit)
  nearest    an end was taken from the player's tracked position at the closest moment within 1.5 s (the player was not tracked at
             that exact frame)
  base       a player was not tracked near that moment at all: the end is the sport's base position of that side (`base_position`)
A hit with no attributed hitter is given to the player who did not hit before it (or to the side of its court position). The last hit of
a rally, with no usable landing after it, flies for 0.8 s towards the other player (`open_end`). A gap longer than 2.4 s (a missed hit in
between) is drawn as a 2.4 s flight (`gap`), a flight under 0.12 s as 0.12 s, and a flight whose ends are closer than 0.3 m keeps a
0.3 m run so it is still visible. Where the next hit was attributed to the SAME player, the receiver is taken to be the other player
(`receiver_inferred`).

Coordinates are court metres (origin at the near-left corner, x across, y along the length), z up. Nothing here is a tracked 3D
position: it shows where a shot of that distance and duration could have gone.
"""

from __future__ import annotations

import math

from rallyos.analytics.flight import G, solve_launch, trajectory
from rallyos.analytics.speed import LANDING_HEIGHT, MAX_FLIGHT_S, MIN_DIST_M, MIN_FLIGHT_S, _contact

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


def _track_pos(frames: list[dict] | None, t: float, fps: float, track_id: int | None):
    if not frames or track_id is None:
        return None
    fr = frames[min(max(0, round(t * fps)), len(frames) - 1)]
    p = next((q for q in fr["players"] if q["track_id"] == track_id), None)
    return list(p["court"]) if p and p.get("court") else None


NEAR_WINDOW_S = 1.5
OPEN_FLIGHT_S = 0.8
MIN_RUN_M = 0.3


def _near_pos(frames: list[dict] | None, t: float, fps: float, track_id: int | None):
    """(position, seconds away) of the player's tracked court position closest in time to t, within NEAR_WINDOW_S."""
    if not frames or track_id is None:
        return None
    centre = min(max(0, round(t * fps)), len(frames) - 1)
    reach = int(NEAR_WINDOW_S * fps)
    for k in range(0, reach + 1):
        for f in ((centre,) if k == 0 else (centre - k, centre + k)):
            if 0 <= f < len(frames):
                p = next((q for q in frames[f]["players"] if q["track_id"] == track_id), None)
                if p and p.get("court"):
                    return list(p["court"]), k / fps
    return None


def _base(cfg: dict, track_id: int) -> list:
    bx, by = cfg["court"]["base_position"]
    return [float(bx), float(by)] if track_id == 1 else [float(bx), float(cfg["court"]["length"]) - float(by)]


def _place_player(frames, fps, cfg, t: float, track_id: int, known: list | None = None) -> tuple[list, str]:
    """(court position, placement) of a player at time t: a given position, the tracked one, the nearest tracked one, or the base."""
    if known:
        return list(known), "measured"
    exact = _track_pos(frames, t, fps, track_id)
    if exact:
        return exact, "measured"
    near = _near_pos(frames, t, fps, track_id)
    if near:
        return near[0], "nearest"
    return _base(cfg, track_id), "base"


def _worse(a: str, b: str) -> str:
    order = {"measured": 0, "nearest": 1, "base": 2}
    return a if order[a] >= order[b] else b


def _hitter(a: dict, prev_tid: int | None, cfg: dict) -> tuple[int, bool]:
    """(track id, inferred) of a hit's player: the attributed one, else the other player than the previous hit's, else by side."""
    if a.get("track_id") in (1, 2):
        return a["track_id"], False
    if prev_tid in (1, 2):
        return (2 if prev_tid == 1 else 1), True
    if a.get("court"):
        return (1 if a["court"][1] < float(cfg["court"]["length"]) / 2 else 2), True
    return 1, True


def reconstruct(events: list[dict], fps: float, cfg: dict, frames: list[dict] | None = None) -> list[dict]:
    """One dict per hit: {rally_idx, track_id, t0, t1, kind, placement, from, to, samples [[t, x, y, z]...], peak_z, speed_kmh, speed_err_pct, shot, ...}."""
    proj = cfg["projectile"]
    vt = proj.get("terminal_velocity_mps") if proj.get("motion_model") == "quadratic_drag" else None
    bounces = bool(proj.get("bounces"))
    view = cfg.get("view3d") or {}
    plane_z = float(view.get("plane_height_m") or 0.0)           # a table top is above the floor; heights below are relative to it
    fixed_contact = view.get("contact_above_plane_m")             # a sport whose contact height does not depend on the pose
    v_max = proj.get("speed_range_kmh", [1, 1000])[1] / 3.6
    by_rally: dict[int, list[dict]] = {}
    for e in events:
        by_rally.setdefault(e["rally_idx"], []).append(e)
    flights = []
    for evs in by_rally.values():
        evs.sort(key=lambda e: e["t"])
        prev_tid = None
        for i, ev in enumerate(evs):
            if ev["type"] != "hit":
                continue
            tid, hitter_inferred = _hitter(ev, prev_tid, cfg)
            prev_tid = tid
            a = {**ev, "track_id": tid}                              # the hitter used for this flight (a copy: the event itself is never changed)
            nxt = evs[i + 1] if i + 1 < len(evs) else None
            other = 2 if tid == 1 else 1
            start, p0 = _place_player(frames, fps, cfg, a["t"], tid, ev.get("court") if ev.get("track_id") == tid else None)
            usable_landing = bool(nxt is not None and nxt["type"] == "landing" and nxt.get("court") and not nxt.get("note")
                                  and "call" in nxt and nxt.get("confidence", 0) >= 0.5)
            open_end = False
            receiver_inferred = False
            if usable_landing:
                end, p1 = list(nxt["court"]), "measured"
                T = nxt["t"] - a["t"]
                far = nxt
            elif nxt is not None and nxt["type"] == "hit":
                nt = nxt.get("track_id")
                receiver_inferred = nt not in (1, 2) or nt == tid
                recv = other if receiver_inferred else nt
                end, p1 = _place_player(frames, fps, cfg, nxt["t"], recv, None if receiver_inferred else nxt.get("court"))
                T = nxt["t"] - a["t"]
                far = {**nxt, "track_id": recv}
            else:                                                    # the last hit of its rally, or an untrusted landing: fly on towards the other player
                open_end = True
                T = (nxt["t"] - a["t"]) if nxt is not None and MIN_FLIGHT_S <= nxt["t"] - a["t"] <= MAX_FLIGHT_S else OPEN_FLIGHT_S
                end, p1 = _place_player(frames, fps, cfg, a["t"] + T, other)
                far = {"type": "hit", "track_id": other, "t": a["t"] + T}
            gap = T > MAX_FLIGHT_S
            T = min(max(T, MIN_FLIGHT_S), MAX_FLIGHT_S)
            placement = _worse(p0, p1)
            d = math.dist(start, end)
            if d < MIN_RUN_M:                                        # keep a visible run for a net shot / a double-detected hit
                ux, uy = end[0] - start[0], end[1] - start[1]
                norm = math.hypot(ux, uy)
                dirx, diry = (ux / norm, uy / norm) if norm > 1e-6 else (0.0, 1.0 if tid == 1 else -1.0)
                end = [start[0] + dirx * MIN_RUN_M, start[1] + diry * MIN_RUN_M]
                d = MIN_RUN_M
            h0 = fixed_contact[0] if fixed_contact else _contact(a, frames, fps)[0]
            h1 = LANDING_HEIGHT[0] if usable_landing else (fixed_contact[0] if fixed_contact else _contact(far, frames, fps)[0])
            n = max(2, int(round(T * SAMPLE_HZ)))
            kind, heights, fracs = "estimate", None, None
            sol = solve_launch(d, T, h1 - h0, vt) if vt and placement == "measured" and not (gap or open_end) else None
            if sol is not None and sol[0] <= v_max:
                path = trajectory(sol[0], sol[1], T, vt, dt=T / n)
                x_end = path[-1][1] or 1e-6
                fracs = [min(1.0, max(0.0, p[1] / x_end)) for p in path]            # how far along the line, by the drag law
                heights = [h0 + p[2] + (h1 - h0 - path[-1][2]) * (p[0] / T) for p in path]    # tiny correction so the end meets h1
                kind = "physics"
            elif bounces and not usable_landing:
                heights = _bounce_heights(h0, h1, T, n)
                fracs = [min(BOUNCE_AT, BOUNCE_AT * (i / max(1, round(n * BOUNCE_TIME)))) if i <= round(n * BOUNCE_TIME)
                         else BOUNCE_AT + (1 - BOUNCE_AT) * ((i - round(n * BOUNCE_TIME)) / max(1, n - round(n * BOUNCE_TIME))) for i in range(len(heights))]
            else:
                heights = _arc(h0, h1, T, n)
                fracs = [i / n for i in range(n + 1)]
            ax, ay = start
            bx, by = end
            samples = [[round(a["t"] + T * i / (len(heights) - 1), 3), round(ax + (bx - ax) * f, 3), round(ay + (by - ay) * f, 3), round(max(0.0, float(z)) + plane_z, 3)]
                       for i, (f, z) in enumerate(zip(fracs, heights))]
            flights.append({"rally_idx": a["rally_idx"], "track_id": tid, "t0": round(a["t"], 3), "t1": round(a["t"] + T, 3),
                            "kind": kind, "placement": placement, "receiver_inferred": receiver_inferred, "hitter_inferred": hitter_inferred,
                            "open_end": open_end, "gap": gap, "from": samples[0][1:], "to": samples[-1][1:], "samples": samples,
                            "peak_z": round(max(s[3] for s in samples) - plane_z, 2), "shot": a.get("shot"),
                            "speed_kmh": a.get("speed_kmh") if kind == "physics" else None, "speed_err_pct": a.get("speed_err_pct") if kind == "physics" else None})
    flights.sort(key=lambda f: f["t0"])
    return flights
