"""Line calls with an uncertainty ellipse: IN / OUT with a probability, or TOO CLOSE TO CALL (§4.7).

Error sources combined into one 2x2 covariance in court metres:
  detection   blob-centre noise of the shuttle in the image          (sigma_det_px, through the H Jacobian)
  calibration error of the tapped corners                             (sigma_cal_px, same way)
  height      the last frame before contact is up to one frame of fall above the floor; that moves the
              court point along the camera ray (uniform over [0, drop] -> sigma = drop / sqrt(12))
  no camera   without a focal estimate the height can't be corrected: a fixed depth error is added instead
P(IN) treats x and y as independent normals against the in-bounds rectangle (lines are in).
Decision support, not a decision: the call is TOO CLOSE TO CALL unless one side has >= `sure` probability.
"""

from __future__ import annotations

import math

import numpy as np

from rallyos.events.landings import fall_per_frame_m, project_landing, px_jacobian

CALL_SURE = 0.8          # below this either way: TOO CLOSE TO CALL
DISPUTE_BELOW = 0.9      # calls less certain than this get a Fair-Play Replay package
PLAUSIBLE_M = 2.5        # a "landing" farther than this outside the court is a lost shuttle, not a landing


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def in_bounds(cfg: dict, doubles: bool = False) -> list[float]:
    ib = cfg["court"].get("in_bounds")
    if ib:
        return list(ib["doubles" if doubles else "singles"])
    return [0.0, float(cfg["court"]["width"]), 0.0, float(cfg["court"]["length"])]


def landing_estimate(px, H, cfg: dict, fps: float, width: int, camera_m=None,
                     sigma_det_px: float = 3.0, sigma_cal_px: float = 4.0, interpolated: bool = False) -> dict:
    """Court position + covariance of a landing seen at image point px."""
    scale = width / 1920.0
    drop = fall_per_frame_m(cfg, fps)
    court, ray_u, m_per_h = project_landing(px, H, camera_m, height_m=drop / 2, width=width)
    J = px_jacobian(H, px)
    s2 = (sigma_det_px * scale) ** 2 + (sigma_cal_px * scale) ** 2
    cov = J @ (np.eye(2) * s2) @ J.T
    if ray_u is not None:
        sh = drop / math.sqrt(12.0) * m_per_h
        cov += sh ** 2 * np.outer(ray_u, ray_u)
    else:
        cov += np.diag([0.0, 0.15 ** 2])                 # depth along the court, height unknown
    if interpolated:
        cov *= 4.0
    return {"court": [round(court[0], 3), round(court[1], 3)], "cov": cov}


def ellipse_from_cov(cov: np.ndarray, k: float = 2.0) -> list[float]:
    """[semi-axis a, semi-axis b (m), angle (deg, from court x towards y)] of the k-sigma ellipse."""
    w, v = np.linalg.eigh(cov)
    order = np.argsort(w)[::-1]
    w, v = w[order], v[:, order]
    a, b = k * math.sqrt(max(w[0], 0.0)), k * math.sqrt(max(w[1], 0.0))
    ang = math.degrees(math.atan2(v[1, 0], v[0, 0]))
    ang = (ang + 90) % 180 - 90
    return [round(a, 3), round(b, 3), round(ang, 1)]


def prob_in(court, cov: np.ndarray, bounds) -> float:
    x, y = court
    x0, x1, y0, y1 = bounds
    sx = max(math.sqrt(cov[0, 0]), 1e-4)
    sy = max(math.sqrt(cov[1, 1]), 1e-4)
    return _phi((x - x0) / sx) * _phi((x1 - x) / sx) * _phi((y - y0) / sy) * _phi((y1 - y) / sy)


def make_call(p_in: float, sure: float = CALL_SURE) -> tuple[str, float]:
    """("IN" | "OUT" | "TOO CLOSE TO CALL", probability of that call; for too close: P(IN))."""
    if p_in >= sure:
        return "IN", round(p_in, 3)
    if p_in <= 1 - sure:
        return "OUT", round(1 - p_in, 3)
    return "TOO CLOSE TO CALL", round(p_in, 3)


def line_call(px, H, cfg: dict, fps: float, width: int, camera_m=None, doubles: bool = False,
              interpolated: bool = False) -> dict:
    est = landing_estimate(px, H, cfg, fps, width, camera_m, interpolated=interpolated)
    bounds = in_bounds(cfg, doubles)
    p = prob_in(est["court"], est["cov"], bounds)
    call, prob = make_call(p)
    x, y = est["court"]
    margin = min(x - bounds[0], bounds[1] - x, y - bounds[2], bounds[3] - y)   # + inside, - outside (m)
    return {"court": est["court"], "p_in": round(p, 3), "call": call, "call_prob": prob,
            "ellipse_m": ellipse_from_cov(est["cov"]), "margin_m": round(margin, 3)}


def rally_winner(call: dict, net_y: float, last_hitter: int | None, landing_conf: float,
                 side_of: dict[int, str], net_zone_m: float = 1.5) -> dict:
    """Who won the rally from where it landed and the call (singles, sides near/far).

    IN on a side -> the player on the other side hit the winner. OUT on a side -> it came from the other
    side, so the player on the landing side wins. A known last hitter on the other side agrees.
    A last hitter on the landing side means one of two things: a shot that never crossed the net (it then
    lands close to the net -> the hitter loses) or, far more often with one camera, a missed final hit by
    the opponent (deep landing -> landing logic, lower confidence, flagged hitter_conflict).
    Returns {"winner_track_id", "end_reason", "confidence", "hitter_conflict"}.
    """
    side = "near" if call["court"][1] < net_y else "far"
    owner = {s: tid for tid, s in side_of.items()}
    other = "far" if side == "near" else "near"
    p_in = call["p_in"]
    conflict = last_hitter is not None and side_of.get(last_hitter) == side
    if conflict and abs(call["court"][1] - net_y) <= net_zone_m:
        winner, reason, p = owner.get(other), "net_fault", 0.6
    elif p_in >= 0.5:
        winner, reason, p = owner.get(other), "landing_in", p_in
    else:
        winner, reason, p = owner.get(side), "landing_out", 1 - p_in
    if call["call"] == "TOO CLOSE TO CALL" and reason != "net_fault":
        reason = "too_close"
    agree = 1.0 if (last_hitter is not None and side_of.get(last_hitter) == other) else 0.7 if conflict else 0.85
    return {"winner_track_id": winner, "end_reason": reason, "confidence": round(p * landing_conf * agree, 2),
            "hitter_conflict": conflict}


def score_rallies(sport_cfg: dict, rallies: list[dict], side_of_track: dict[int, int],
                  min_conf: float = 0.0) -> dict:
    """Run the sport's scoring engine over suggested rally winners. Sets rallies[i]["score_after"].

    Points only count from the start of the clip (the match score before it is unknown). Rallies with no
    suggested winner are skipped and counted, so the score is marked incomplete rather than guessed.
    """
    from rallyos.rules.engine import MatchOver, engine_for

    eng = engine_for(sport_cfg)
    unresolved = 0
    for r in rallies:
        w = r.get("winner_track_id")
        if w is None or w not in side_of_track or (r.get("winner_confidence") or 0) < min_conf:
            unresolved += 1
            r["score_after"] = None
            continue
        try:
            snap = eng.point(side_of_track[w])
        except MatchOver:
            break
        r["score_after"] = snap["score_str"]
    snap = eng.snapshot()
    if "sets" in snap:                                   # game_set family: sets, then games in the current set
        games, cur = [list(x) for x in snap["sets"]], snap.get("games")
    else:                                                # points families: games, then points in the current game
        games, cur = [list(x) for x in snap.get("games", [])], snap.get("current")
    if cur and any(cur):
        games.append(list(cur))
    winner_side = snap.get("winner")
    track_of = {s: t for t, s in side_of_track.items()}
    return {"games": games, "winner_track_id": track_of.get(winner_side) if winner_side is not None else None,
            "confirmed_by_human": False, "score_str": snap["score_str"], "source": "suggested from line calls",
            "unresolved_rallies": unresolved, "from_clip_start": True}


def resolve_rally_ends(rallies: list[dict], hits: list[dict], balls: list[dict | None], frames: list[dict],
                       cfg: dict, fps: float, width: int, H=None, camera: dict | None = None,
                       side_of: dict[int, str] | None = None) -> list[dict]:
    """For each rally (with "hit_frames"): find the landing, call it, suggest the winner.

    Updates the rallies in place (winner_track_id, winner_confidence, end_reason, t_end) and returns one
    landing event dict per rally whose landing was found (ids/rally_idx filled by the caller's order).
    No call is made (winner stays None, reason says why) when the clip ends while the shuttle is in flight,
    when the "landing" projects far outside the court, or when the shuttle vanished inside the image of the
    net while travelling towards the camera (last hitter on the far side, or unknown): it may be on the floor
    behind the net or still in the air in front of it, and one camera can't tell. Travelling away from the
    camera, a point seen through the net mesh is a real far-court landing and is called.
    """
    from rallyos.events.landings import find_landing, in_polygon, net_polygon_px

    camera_m = camera["position_m"] if camera else None
    net_poly = net_polygon_px(camera, cfg) if camera else None

    side_of = side_of or {1: "near", 2: "far"}
    net = next((l for l in cfg["court"]["lines"] if l["id"] == "net"), None)
    net_y = float(net["p1"][1]) if net else float(cfg["court"]["length"]) / 2
    bounces = bool(cfg["projectile"].get("bounces"))
    far_from_camera = "far" if camera_m is None or camera_m[1] < net_y else "near"
    hitter_at = {h["frame"]: h.get("track_id") for h in hits}
    landings = []
    for k, r in enumerate(rallies):
        last = max(r["hit_frames"])
        nxt = min(rallies[k + 1]["hit_frames"]) if k + 1 < len(rallies) else len(balls)
        land = find_landing(balls, frames, last, min(nxt, last + int(3 * fps)), fps, bounces=bounces)
        if land is None:
            r.update(end_reason="shuttle_lost", winner_track_id=None, winner_confidence=None)
            continue
        r["t_end"] = round(max(r["t_end"], min(land["t"] + 0.5, len(balls) / fps)), 2)
        ev = {"rally_idx": r["idx"], "t": land["t"], "type": "landing", "track_id": None, "px": land["px"],
              "court": None, "shot": None, "speed_kmh": None, "speed_err_pct": None,
              "confidence": land["confidence"], "source": ["vision"], "interpolated": land["interpolated"],
              "frame": land["frame"]}
        if land["clip_ended"]:
            r.update(end_reason="clip_ended", winner_track_id=None, winner_confidence=None)
            continue
        towards_camera = side_of.get(hitter_at.get(last)) in (None, far_from_camera)
        if net_poly and towards_camera and in_polygon(land["px"], net_poly):
            r.update(end_reason="landing_hidden_by_net", winner_track_id=None, winner_confidence=None)
            landings.append({**ev, "confidence": round(0.3 * land["confidence"], 2),
                             "note": "shuttle lost against the net: floor behind the net or still in the air"})
            continue
        if H is None:
            r.update(end_reason="landing_uncalibrated", winner_track_id=None, winner_confidence=None)
        else:
            c = line_call(land["px"], H, cfg, fps, width, camera_m, interpolated=land["interpolated"])
            x0, x1, y0, y1 = in_bounds(cfg, doubles=True)
            x, y = c["court"]
            if not (x0 - PLAUSIBLE_M <= x <= x1 + PLAUSIBLE_M and y0 - PLAUSIBLE_M <= y <= y1 + PLAUSIBLE_M):
                r.update(end_reason="landing_implausible", winner_track_id=None, winner_confidence=None)
                landings.append({**ev, "court": c["court"], "confidence": round(0.3 * land["confidence"], 2),
                                 "note": "projects far outside the court: shuttle probably still in the air"})
                continue
            ev.update(court=c["court"], call=c["call"], call_prob=c["call_prob"], p_in=c["p_in"],
                      ellipse_m=c["ellipse_m"], margin_m=c["margin_m"])
            w = rally_winner(c, net_y, hitter_at.get(last), land["confidence"], side_of)
            r.update(winner_track_id=w["winner_track_id"], winner_confidence=w["confidence"], end_reason=w["end_reason"],
                     hitter_conflict=w["hitter_conflict"])
        landings.append(ev)
    return landings
