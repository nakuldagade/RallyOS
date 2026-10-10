"""Explainable rule-based shot classification from the sport YAML thresholds (§4.6). No trained classifier.

For each hit, the shot is what the next event shows it to be: where it was hit from, where it went, how long it
was in the air, and (from pose) whether the wrist was above the head. Rules come from `shots:` in the sport
YAML, tried in file order, first match wins. Every label carries a one-sentence reason and a confidence.

What is measured, and what is not:

  measured    first_hit_of_rally, not_serve, wrist_above_head (pose keypoints), from_zone / land_zone (the
              court zone of the hitter, and of the landing - or, with no landing call, of the opponent's next
              contact), min/max_flight_s, min/max_speed_kmh (the average horizontal speed of speed.py)
  proxy       apex_over_net_m_*, apex_m_min: the shuttle's height is not measured (3D is on the cut list). The
              height gained above the contact point is estimated from the flight time as a vacuum parabola,
              g t^2 / 8. Air drag makes the real apex lower, so treat it as an upper estimate; labels that
              rest on it say so and carry a lower confidence
  soft        descent_deg_min, underarm: refinements that cannot be checked; a rule may still fire without
              them, with a lower confidence and the condition listed as unchecked
  not measured (bounces, wall hits, front-wall height, ...): a rule that lists one of these CANNOT fire, so
              the shot stays unlabelled with that reason instead of being guessed (tennis volley and
              groundstroke, padel wall returns, squash boasts need bounce / wall detection)
"""

from __future__ import annotations

from collections import Counter

G = 9.81
SOFT = {"descent_deg_min", "underarm"}
PROXY_APEX = {"apex_over_net_m_min", "apex_over_net_m_max", "apex_m_min"}
MEASURED = {"first_hit_of_rally", "not_serve", "wrist_above_head", "from_zone", "land_zone", "min_flight_s",
            "max_flight_s", "min_speed_kmh", "max_speed_kmh"} | PROXY_APEX
NOSE, EYES, WRISTS = 0, (1, 2), (9, 10)


def apex_estimate_m(flight_s: float) -> float:
    """Height gained above the contact point for a flight of this length, as a vacuum parabola (an upper estimate)."""
    return G * flight_s ** 2 / 8.0


def net_y(cfg: dict) -> float:
    net = next((l for l in cfg["court"]["lines"] if l["id"] == "net"), None)
    return float(net["p1"][1]) if net else float(cfg["court"]["length"]) / 2


def zone_by_net_distance(y: float, cfg: dict) -> str | None:
    """Named zone (front / mid / rear, ...) of a court point by its distance from the net, on either side.

    The deepest zone also covers everything beyond it: a player hitting from behind the baseline, or a shot landing
    just past it, is still in the rear court.
    """
    zones = {n: z["y_from_net_m"] for n, z in (cfg["court"].get("zones") or {}).items() if z.get("y_from_net_m")}
    if not zones:
        return None                                  # a sport whose zones are not net-relative (squash)
    d = abs(y - net_y(cfg))
    for name, (lo, hi) in zones.items():
        if lo <= d < hi:
            return name
    deepest = max(zones, key=lambda n: zones[n][1])
    return deepest if d >= zones[deepest][1] else None


def wrist_above_head(frames: list[dict], frame: int, track_id, margin: int = 2) -> bool | None:
    """True/False from the pose keypoints around the hit frame; None when no usable pose is available."""
    seen = False
    for f in range(max(0, frame - margin), min(len(frames), frame + margin + 1)):
        p = next((q for q in frames[f]["players"] if q["track_id"] == track_id), None)
        kp = p.get("kp") if p else None
        if not kp:
            continue
        eyes = [kp[i][1] for i in EYES if kp[i][2] > 0.3] or ([kp[NOSE][1]] if kp[NOSE][2] > 0.3 else [])
        wrists = [kp[i][1] for i in WRISTS if kp[i][2] > 0.3]
        if not eyes or not wrists:
            continue
        seen = True
        if min(wrists) < min(eyes):                  # smaller y = higher in the image
            return True
    return False if seen else None


def _features(hit: dict, nxt: dict | None, first: bool, frames: list[dict], fps: float, cfg: dict) -> dict:
    f: dict = {"first_hit_of_rally": first, "not_serve": not first}
    if hit.get("court"):
        f["from_zone"] = zone_by_net_distance(hit["court"][1], cfg)
    f["wrist_above_head"] = wrist_above_head(frames, round(hit["t"] * fps), hit.get("track_id")) if frames else None
    if nxt is not None:
        flight = nxt["t"] - hit["t"]
        f["flight_s"] = round(flight, 3)
        f["apex_est_m"] = round(apex_estimate_m(flight), 2)
        where = nxt.get("court")
        f["land_basis"] = "landing" if nxt["type"] == "landing" and "call" in nxt and not nxt.get("note") else "next contact"
        if where:
            f["land_zone"] = zone_by_net_distance(where[1], cfg)
        if hit.get("speed_kmh") is not None:
            f["speed_kmh"] = hit["speed_kmh"]
    return f


def _check(cond: str, want, f: dict):
    """(True | False | None, explanation) for one rule condition; None = cannot be measured here."""
    def has(*keys):
        return all(f.get(k) is not None for k in keys)

    if cond in ("first_hit_of_rally", "not_serve"):
        return f[cond] == want, ("first hit of the rally" if cond == "first_hit_of_rally" else "not the serve")
    if cond == "wrist_above_head":
        return (None, "") if f.get("wrist_above_head") is None else (f["wrist_above_head"] == want, "wrist above the head")
    if cond in ("from_zone", "land_zone"):
        zones = want if isinstance(want, list) else [want]
        label = "hit from the" if cond == "from_zone" else "landed in the"
        if f.get(cond) is None:
            return None, ""
        return f[cond] in zones, f"{label} {f[cond]} court"
    if cond in ("min_flight_s", "max_flight_s"):
        if not has("flight_s"):
            return None, ""
        ok = f["flight_s"] >= want if cond.startswith("min") else f["flight_s"] <= want
        return ok, f"{f['flight_s']:.2f} s in the air ({'at least' if cond.startswith('min') else 'at most'} {want} s)"
    if cond in ("min_speed_kmh", "max_speed_kmh"):
        if not has("speed_kmh"):
            return None, ""
        ok = f["speed_kmh"] >= want if cond.startswith("min") else f["speed_kmh"] <= want
        return ok, f"about {f['speed_kmh']} km/h on average ({'over' if cond.startswith('min') else 'under'} {want})"
    if cond in PROXY_APEX:
        if not has("apex_est_m"):
            return None, ""
        ok = f["apex_est_m"] >= want if cond.endswith("min") else f["apex_est_m"] <= want
        return ok, f"estimated apex about {f['apex_est_m']:.1f} m from the flight time ({'over' if cond.endswith('min') else 'under'} {want} m)"
    return None, ""                                  # bounces, walls, descent angle, ...: not measured


def classify_shots(events: list[dict], frames: list[dict], fps: float, cfg: dict) -> dict:
    """Fill shot / shot_conf / shot_why / shot_features on every hit event in place; returns a summary for stats."""
    rules = cfg.get("shots") or {}
    never = sorted({c for r in rules.values() for c in r if c not in MEASURED and c not in SOFT})
    labelled = unlabelled = 0
    reasons: Counter = Counter()
    by_rally: dict[int, list[dict]] = {}
    for e in events:
        by_rally.setdefault(e["rally_idx"], []).append(e)
    for evs in by_rally.values():
        evs.sort(key=lambda e: e["t"])
        hit_no = 0
        for i, hit in enumerate(evs):
            if hit["type"] != "hit":
                continue
            first = hit_no == 0
            hit_no += 1
            nxt = evs[i + 1] if i + 1 < len(evs) else None
            f = _features(hit, nxt, first, frames, fps, cfg)
            label, conf, why, unchecked = _match(rules, f)
            if label is None:
                hit.update(shot=None, shot_conf=None, shot_why=why, shot_features=f)
                unlabelled += 1
                reasons[why] += 1
                continue
            conf *= max(0.0, hit.get("confidence", 0.6)) ** 0.5
            hit.update(shot=label, shot_conf=round(min(0.9, conf), 2), shot_why=why, shot_features=f,
                       **({"shot_unchecked": unchecked} if unchecked else {}))
            labelled += 1
    return {"labelled": labelled, "unlabelled": unlabelled, "why_unlabelled": dict(reasons),
            "rules_that_need_bounce_or_wall_data": never,
            "apex": "estimated from flight time (vacuum parabola, an upper estimate), not measured"}


def _match(rules: dict, f: dict) -> tuple[str | None, float, str, list[str]]:
    blocked: list[str] = []
    for name, conds in rules.items():
        checks, hard_unknown, unchecked = [], False, []
        for cond, want in conds.items():
            if cond == "first_hit_of_rally" and want is True:
                # a serve is the first hit of the rally; its other listed refinements (underarm, ...) cannot change that
                checks = [(True, "first hit of the rally")] if f["first_hit_of_rally"] else [(False, "")]
                unchecked = [c for c in conds if c != cond]
                hard_unknown = False
                break
            ok, text = _check(cond, want, f)
            if cond in SOFT:
                unchecked.append(cond)
            elif ok is None:
                hard_unknown = True
                blocked.append(f"{name}: {cond.replace('_', ' ')} not measurable here")
            else:
                checks.append((ok, text))
        if hard_unknown or not all(ok for ok, _ in checks) or not checks:
            continue
        conf = 0.85
        if any(c in PROXY_APEX for c in conds):
            conf *= 0.75
        if "land_zone" in conds and f.get("land_basis") == "next contact":
            conf *= 0.85
        if unchecked:
            conf *= 0.9
        why = f"{name.replace('_', ' ').capitalize()}: " + "; ".join(t for _, t in checks if t) + "."
        return name, conf, why, unchecked
    if "flight_s" not in f and not f["first_hit_of_rally"]:
        return None, 0.0, "no landing or next contact to measure the flight", []
    return None, 0.0, ("no rule matched" + (f" ({'; '.join(sorted(set(blocked))[:2])})" if blocked else "")), []


def shot_mix(events: list[dict], track_id: int) -> dict[str, int]:
    return dict(Counter(e["shot"] for e in events if e["type"] == "hit" and e.get("track_id") == track_id and e.get("shot")))
