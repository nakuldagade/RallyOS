"""Opponent suggestions: rating window + distance + style complement ("someone who will test your defence")."""
import math


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def km(lat1, lng1, lat2, lng2) -> float:
    if None in (lat1, lng1, lat2, lng2):
        return 0.0
    p = math.pi / 180
    h = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lng2 - lng1) * p)) / 2
    return 12742 * math.asin(math.sqrt(h))


def complement(a: list[float], b: list[float]) -> float:
    """0..1: how differently two players play (mean absolute style gap). Different styles test each other."""
    if not a or not b:
        return 0.0
    return sum(abs(x - y) for x, y in zip(a, b)) / min(len(a), len(b))


def suggest(me, others, radius_km: float = 25.0, rating_window: float = 250.0) -> list[dict]:
    out = []
    for o in others:
        if o.id == me.id or o.sport != me.sport:
            continue
        gap, dist = abs(o.rating - me.rating), km(me.lat, me.lng, o.lat, o.lng)
        if gap > rating_window or dist > radius_km:
            continue
        comp = complement(me.style_vec or [], o.style_vec or [])
        score = 0.5 * (1 - gap / rating_window) + 0.3 * (1 - dist / radius_km) + 0.2 * min(comp * 2, 1.0)
        out.append({"player_id": o.id, "name": o.name, "rating": round(o.rating, 1), "distance_km": round(dist, 1),
                    "style_similarity": round(cosine(me.style_vec or [], o.style_vec or []), 2),
                    "style_complement": round(comp, 2), "score": round(score, 3)})
    return sorted(out, key=lambda r: -r["score"])
