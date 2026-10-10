"""Best shot: what a shot achieved comes first, how it was played places it inside that. Rules, not a trained model (§4.6 / §4.8).

    A back-court shot that won the point is a better shot than a smash that hit the net.

So the outcome sets a band and the technique only moves a shot inside its band, never across it:

    outcome (what the shot did)                              score band
    winner        the rally ended IN on the opponent's side     80-100
    forced error  the opponent's reply went out or into the net 60-80
    kept going    the opponent got it back, the rally went on   40-60
    unknown       the clip or the tracking ends without an end  20-40
    error         this shot went out or into the net             0-20

The outcome is only known for the last two shots of a rally whose landing was seen and called (a rally that ends with the
shuttle lost, the clip ending or a landing too close to call has no known outcome), so the app says which shots it could judge
by outcome and ranks the rest by technique alone. Speed is one small part of technique, not the criterion.

Technique (each part 0-1, only the parts that could be measured count, at least two are needed):
    placement  0.30  how close the shuttle came to a boundary of the opponent's half (a line or the net tape): exp(-gap / 1.2 m)
    pressure   0.30  how far the opponent had to move: their position at the hit to where the shuttle landed or they met it, /5 m
    power      0.15  the launch speed's rank among the measured shots of the match (only when its own band is within +-40%)
    recovery   0.15  back at base before the opponent's reply (an error when not)
    mechanics  0.10  an overhead shot (smash, clear, drop) played with the wrist above the head

Everything is measured on the court plane from the homography; the numbers have the accuracy of those positions (about a metre).
"""

from __future__ import annotations

import math

BANDS = {"winner": (80.0, 100.0), "forced_error": (60.0, 80.0), "kept_going": (40.0, 60.0), "unknown": (20.0, 40.0), "error": (0.0, 20.0)}
WEIGHTS = {"placement": 0.30, "pressure": 0.30, "power": 0.15, "recovery": 0.15, "mechanics": 0.10}
MIN_PARTS = 2
LINE_SCALE_M = 1.2
PRESSURE_FULL_M = 5.0
POWER_MAX_ERR = 40
OVERHEAD_SHOTS = ("smash", "clear", "drop")
LABEL = {"winner": "won the point", "forced_error": "forced an error", "kept_going": "kept the rally going",
         "unknown": "outcome not seen", "error": "lost the point"}


def _opponent(tid: int) -> int:
    return 2 if tid == 1 else 1


def _player_at(frames: list[dict], t: float, fps: float, tid: int):
    if not frames:
        return None
    f = min(max(0, round(t * fps)), len(frames) - 1)
    p = next((q for q in frames[f]["players"] if q["track_id"] == tid), None)
    return p["court"] if p and p.get("court") else None


def _outcomes(rally_hits: list[dict], rally: dict | None) -> dict[int, tuple[str, str, float]]:
    """index in rally_hits -> (tier, reason, confidence) for every shot whose outcome the rally tells."""
    out: dict[int, tuple[str, str, float]] = {}
    if not rally_hits or not rally:
        return out
    winner, reason, conf = rally.get("winner_track_id"), rally.get("end_reason"), rally.get("winner_confidence") or 0.0
    if winner is None:
        return out
    last = len(rally_hits) - 1
    hitter = rally_hits[last].get("track_id")
    if hitter is None:
        return out
    last_result = None
    if reason == "landing_in" and winner == hitter:
        out[last] = ("winner", "landed in on the opponent's side", conf)
    elif reason in ("landing_out", "net_fault") and winner != hitter:
        last_result = "went out" if reason == "landing_out" else "hit the net"
        out[last] = ("error", last_result, conf)
        if last >= 1 and rally_hits[last - 1].get("track_id") == winner:
            out[last - 1] = ("forced_error", f"the reply {last_result}", conf)
    return out


def _parts(e: dict, nxt: dict | None, tier: str, frames: list[dict], fps: float, cfg: dict, speeds: list[float]) -> dict[str, float]:
    from rallyos.analytics.linecall import in_bounds

    parts: dict[str, float] = {}
    where = nxt.get("court") if nxt else None
    if where and tier != "error":
        x0, x1, y0, y1 = in_bounds(cfg, doubles=False)
        net = next((l for l in cfg["court"]["lines"] if l["id"] == "net"), None)
        net_y = float(net["p1"][1]) if net else float(cfg["court"]["length"]) / 2
        x, y = where
        far_side = y > net_y
        gap = min(x - x0, x1 - x, (y1 - y) if far_side else (y - y0), abs(y - net_y))
        if nxt["type"] == "landing" and nxt.get("call") == "OUT":
            gap = 0.0
        parts["placement"] = round(math.exp(-max(0.0, gap) / LINE_SCALE_M), 3)
        opp = _player_at(frames, e["t"], fps, _opponent(e["track_id"]))
        if opp:
            parts["pressure"] = round(min(1.0, math.dist(opp, where) / PRESSURE_FULL_M), 3)
    if e.get("speed_kmh") is not None and (e.get("speed_err_pct") or 0) <= POWER_MAX_ERR and len(speeds) >= 4:
        parts["power"] = round(sum(1 for s in speeds if s <= e["speed_kmh"]) / len(speeds), 3)
    if e.get("returned_to_base") is not None:
        parts["recovery"] = 1.0 if e["returned_to_base"] else 0.2
    feat = e.get("shot_features") or {}
    if e.get("shot") in OVERHEAD_SHOTS and feat.get("wrist_above_head") is not None:
        parts["mechanics"] = 1.0 if feat["wrist_above_head"] else 0.3
    return parts


def _technique(parts: dict[str, float]) -> float | None:
    if len(parts) < MIN_PARTS:
        return None
    return round(sum(WEIGHTS[k] * v for k, v in parts.items()) / sum(WEIGHTS[k] for k in parts), 3)


def _why(e: dict, tier: str, reason: str | None, parts: dict[str, float], technique: float | None, nxt: dict | None) -> str:
    bits = [f"{(e.get('shot') or 'shot').capitalize()} that {LABEL[tier]}" + (f" ({reason})" if reason and tier in ('winner', 'forced_error', 'error') else "")]
    if "placement" in parts and nxt and nxt.get("court"):
        bits.append("placed " + ("on a line" if parts["placement"] > 0.9 else f"about {-LINE_SCALE_M * math.log(max(parts['placement'], 1e-3)):.1f} m from the nearest boundary"))
    if "pressure" in parts:
        bits.append(f"opponent had to move about {parts['pressure'] * PRESSURE_FULL_M:.1f} m")
    if "power" in parts:
        bits.append(f"faster than {round(parts['power'] * 100)}% of the measured shots ({e['speed_kmh']} km/h at the racket)")
    if "recovery" in parts:
        bits.append("back at base in time" if parts["recovery"] > 0.5 else "late back to base")
    if "mechanics" in parts:
        bits.append("hit from above the head" if parts["mechanics"] > 0.5 else "not hit from above the head")
    if technique is None:
        bits.append("too little measured to judge the technique")
    return "; ".join(bits) + "."


def rate_shots(events: list[dict], rallies: list[dict], frames: list[dict], fps: float, cfg: dict, per_player: dict | None = None) -> dict:
    """Rate every hit (e["shot_rating"]) and fill per_player[tid]["best_shot"] / ["best_shots"]. Returns a summary."""
    by_idx = {r["idx"]: r for r in rallies}
    ordered = sorted(events, key=lambda e: e["t"])
    speeds = sorted(float(e["speed_kmh"]) for e in ordered if e["type"] == "hit" and e.get("speed_kmh") is not None
                    and (e.get("speed_err_pct") or 0) <= POWER_MAX_ERR)
    rated, with_outcome = [], 0
    by_rally: dict[int, list[dict]] = {}
    for e in ordered:
        if e["type"] == "hit" and e.get("track_id") is not None:
            by_rally.setdefault(e["rally_idx"], []).append(e)
    for ridx, hits in by_rally.items():
        outcomes = _outcomes(hits, by_idx.get(ridx))
        for i, e in enumerate(hits):
            nxt = next((n for n in ordered if n["t"] > e["t"] and n["rally_idx"] == ridx), None)
            if i in outcomes:
                tier, reason, oc = outcomes[i]
                with_outcome += 1
            elif i < len(hits) - 1:
                tier, reason, oc = "kept_going", None, 1.0
            else:
                tier, reason, oc = "unknown", None, 1.0
            parts = _parts(e, nxt, tier, frames, fps, cfg, speeds)
            tech = _technique(parts)
            lo, hi = BANDS[tier]
            score = round(lo + (hi - lo) * (tech if tech is not None else 0.5), 1)
            conf = round(min(e.get("confidence") or 0.5, 1.0) * (oc if tier in ("winner", "forced_error", "error") else 1.0) * (0.6 + 0.4 * min(1.0, len(parts) / 3)), 2)
            e["shot_rating"] = {"outcome": tier, "technique": tech, "score": score, "parts": parts, "confidence": conf,
                                "why": _why(e, tier, reason, parts, tech, nxt)}
            rated.append(e)
    summary = {"rated": len(rated), "with_known_outcome": with_outcome,
               "what": "outcome first (won the point > forced an error > kept the rally going > outcome not seen > lost the point), technique places a shot inside its band"}
    if per_player is not None:
        for tid_s, stats in per_player.items():
            mine = [e for e in rated if str(e["track_id"]) == str(tid_s) and e["shot_rating"]["confidence"] >= 0.25]
            if not mine:
                continue
            mine.sort(key=lambda e: (e["shot_rating"]["score"], e["shot_rating"]["confidence"]), reverse=True)

            def card(e):
                r = e["shot_rating"]
                return {"t": e["t"], "shot": e.get("shot"), "outcome": r["outcome"], "score": r["score"], "technique": r["technique"],
                        "confidence": r["confidence"], "why": r["why"]}

            stats["best_shots"] = [card(e) for e in mine[:3]]
            stats["best_shot"] = stats["best_shots"][0]
            decided = any(e["shot_rating"]["outcome"] in ("winner", "forced_error") for e in mine)
            stats["best_shot"]["basis"] = ("outcome" if decided else
                                           "technique only: no point-ending shot of this player was seen in the clip")
    return summary
