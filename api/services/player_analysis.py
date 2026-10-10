"""A player's history and full analysis, built only from the matches that were analysed with that player assigned to a side.

Nothing here is invented: every number is read from the stored match.json / tracks.json of a real analysed match. A player with
no assigned match gets empty lists, not sample data (the rating history is the one exception: it is the seed's sample rating
curve, and is labelled that way by the caller).

  summary   totals over all the player's matches
  matches   one row per match, oldest first (the order they were analysed), with that player's own stats
  trends    each metric as a series over those matches
  compare   the latest match against the average of the earlier ones, with the direction that counts as better
  heatmap   where the player stood, summed over every match, in the player's own half (a far-side player's positions are
            turned round) so matches from either end of the court add up; plus the earlier matches and the latest one apart
  insights  plain sentences from `compare`, each naming the numbers it rests on
"""
from __future__ import annotations

import math
from typing import Optional

from sqlmodel import Session, select

from api.models import Match, Player
from api.services import store

CELL_M = 0.5
MOCK_MATCH_IDS = {"m_001"}          # the repository's sample match: made-up numbers, never part of anybody's history
# metric -> (label, unit, which direction is better, smallest relative change, smallest absolute change): a change must pass
# BOTH to count, so 0.18 s -> 0.26 s of return to base is not announced as +44%
METRICS = {
    "avg_return_to_base_s": ("Return to base", "s", "lower", 0.08, 0.15),
    "returned_pct": ("Back at base before the reply", "%", "higher", 0.08, 10),
    "split_step_pct": ("Split-step", "%", "higher", 0.10, 10),
    "fastest_shot_kmh": ("Fastest shot (at the racket)", "km/h", "higher", 0.10, 20),
    "top_speed_mps": ("Top movement speed", "m/s", "higher", 0.08, 0.5),
    "distance_per_min": ("Distance covered", "m/min", "neutral", 0.10, 5),
    "best_shot_score": ("Best-shot score", "/100", "higher", 0.08, 5),
}


def player_matches(session: Session, player_id: str) -> list[tuple[Match, int]]:
    """(match row, the track that is this player) for every match with the player on side 1 or 2, oldest first."""
    rows = session.exec(select(Match).where((Match.p1 == player_id) | (Match.p2 == player_id)).order_by(Match.created_at, Match.id)).all()
    return [(m, 1 if m.p1 == player_id else 2) for m in rows if m.id not in MOCK_MATCH_IDS]


def _mean(xs: list[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _metrics(stats: dict, duration_s: float) -> dict:
    best = stats.get("best_shot") or {}
    out = {
        "avg_return_to_base_s": stats.get("avg_return_to_base_s"),
        "returned_pct": None if stats.get("returned_pct") is None else round(stats["returned_pct"] * (100 if stats["returned_pct"] <= 1 else 1)),
        "split_step_pct": None if stats.get("split_step_pct") is None else round(stats["split_step_pct"] * 100),
        "fastest_shot_kmh": stats.get("fastest_shot_kmh") if stats.get("fastest_shot_err_pct") is not None else None,   # launch speeds only: an older average is not comparable
        "top_speed_mps": stats.get("top_speed_mps"),
        "distance_per_min": round(stats["distance_m"] / (duration_s / 60.0), 1) if stats.get("distance_m") and duration_s >= 5 else None,
        "best_shot_score": best.get("score"),
    }
    return out


def _grid(rows: int, cols: int) -> list[list[float]]:
    return [[0.0] * cols for _ in range(rows)]


def _add_track(grid: list[list[float]], tracks: dict, track_id: int, side: str, length: float, width: float) -> int:
    n = 0
    rows, cols = len(grid), len(grid[0])
    for fr in tracks.get("frames", []):
        p = next((q for q in fr["players"] if q["track_id"] == track_id), None)
        if not p or not p.get("court"):
            continue
        x, y = p["court"]
        if side == "far":                                     # the player's own half is always the near half
            x, y = width - x, length - y
        r, c = int(y // CELL_M), int(x // CELL_M)
        if 0 <= r < rows and 0 <= c < cols:
            grid[r][c] += 1
            n += 1
    return n


def _normalise(grid: list[list[float]]) -> list[list[float]]:
    top = max((v for row in grid for v in row), default=0.0)
    return [[round(v / top, 3) if top else 0.0 for v in row] for row in grid]


def _compare(rows: list[dict]) -> list[dict]:
    out = []
    if len(rows) < 2:
        return out
    for key, (label, unit, better, tol, min_abs) in METRICS.items():
        latest = rows[-1]["metrics"].get(key)
        earlier_vals = [r["metrics"].get(key) for r in rows[:-1] if r["metrics"].get(key) is not None]
        earlier = _mean(earlier_vals)
        if latest is None or earlier is None:
            continue
        delta = latest - earlier
        share = delta / abs(earlier) if earlier else 0.0
        if better == "neutral" or abs(share) < tol or abs(delta) < min_abs:
            verdict = "steady" if better != "neutral" else "changed"
        else:
            good = (delta < 0) if better == "lower" else (delta > 0)
            verdict = "better" if good else "worse"
        out.append({"metric": key, "label": label, "unit": unit, "better": better, "earlier": round(earlier, 2), "latest": round(latest, 2),
                    "delta": round(delta, 2), "change_pct": round(100 * share), "verdict": verdict, "n_earlier": len(earlier_vals)})
    return out


def _fmt(v: float, unit: str) -> str:
    return f"{round(v)}%" if unit == "%" else f"{v:g} {unit}"


def _insights(compare: list[dict]) -> list[dict]:
    out = []
    for c in compare:
        if c["verdict"] in ("better", "worse"):
            word = "improved" if c["verdict"] == "better" else "got worse"
            out.append({"metric": c["metric"], "verdict": c["verdict"],
                        "text": f"{c['label']} {word}: {_fmt(c['earlier'], c['unit'])} on average over {c['n_earlier']} earlier match"
                                f"{'es' if c['n_earlier'] != 1 else ''}, {_fmt(c['latest'], c['unit'])} in the latest ({c['change_pct']:+d}%)."})
    return out


def analysis(session: Session, player_id: str) -> dict:
    player = session.get(Player, player_id)
    if player is None:
        raise KeyError(player_id)
    sport = player.sport
    from rallyos.sports import load_sport

    court = load_sport(sport)["court"]
    length, width = float(court["length"]), float(court["width"])
    rows_n, cols_n = math.ceil(length / CELL_M), math.ceil(width / CELL_M)
    heat_all, heat_early, heat_last = (_grid(rows_n, cols_n) for _ in range(3))
    rows: list[dict] = []
    best_shots: list[dict] = []
    shot_mix: dict[str, int] = {}
    zones: dict[str, float] = {}
    zone_w = 0.0
    frames_total = 0
    matched = player_matches(session, player_id)
    for k, (m, tid) in enumerate(matched):
        try:
            data = store.load_match(m.id, session)
        except KeyError:
            continue
        stats = (data.get("stats", {}).get("per_player") or {}).get(str(tid)) or {}
        meta = next((p for p in data.get("players", []) if p["track_id"] == tid), {})
        other = next((p for p in data.get("players", []) if p["track_id"] != tid), {})
        opp_id = m.p2 if tid == 1 else m.p1
        opp = session.get(Player, opp_id) if opp_id else None
        duration = float(data.get("video", {}).get("duration_s") or 0)
        winner = (data.get("score") or {}).get("winner_track_id")
        row = {"match_id": m.id, "date": m.created_at, "sport": data.get("sport"), "duration_s": duration, "side": meta.get("side"),
               "opponent": opp.name if opp else (other.get("name") or "opponent"), "opponent_id": opp_id,
               "result": None if winner is None else ("won" if winner == tid else "lost"),
               "hits": stats.get("hits"), "distance_m": stats.get("distance_m"), "metrics": _metrics(stats, duration),
               "shot_mix": stats.get("shot_mix") or {}, "best_shot": stats.get("best_shot")}
        rows.append(row)
        for shot, n in (stats.get("shot_mix") or {}).items():
            shot_mix[shot] = shot_mix.get(shot, 0) + n
        for b in stats.get("best_shots") or []:
            best_shots.append({**b, "match_id": m.id, "date": m.created_at})
        for z, frac in (stats.get("zone_pct") or {}).items():
            zones[z] = zones.get(z, 0.0) + frac * max(duration, 1.0)
        zone_w += max(duration, 1.0) if stats.get("zone_pct") else 0.0
        try:
            tracks = store.load_tracks(m.id)
        except KeyError:
            continue
        side = meta.get("side") or ("near" if tid == 1 else "far")
        last = k == len(matched) - 1
        n = _add_track(heat_last if last else heat_early, tracks, tid, side, length, width)
        frames_total += n
    # the whole-history heatmap is the earlier matches plus the latest one
    for r in range(rows_n):
        for c in range(cols_n):
            heat_all[r][c] = heat_early[r][c] + heat_last[r][c]
    n_matches = len(rows)
    compare = _compare(rows)
    best_shots.sort(key=lambda b: (b["score"], b.get("confidence", 0)), reverse=True)
    trends = {key: [{"match_id": r["match_id"], "i": i + 1, "value": r["metrics"].get(key)} for i, r in enumerate(rows)] for key in METRICS}
    total_dur = sum(r["duration_s"] for r in rows)
    return {
        "player": {"id": player.id, "name": player.name, "sport": sport, "rating": player.rating, "rd": player.rd},
        "summary": {"matches": n_matches, "analysed_minutes": round(total_dur / 60.0, 1), "hits": sum(r["hits"] or 0 for r in rows),
                    "distance_m": round(sum(r["distance_m"] or 0 for r in rows)), "wins": sum(1 for r in rows if r["result"] == "won"),
                    "losses": sum(1 for r in rows if r["result"] == "lost"), "frames_tracked": frames_total},
        "matches": rows, "trends": trends, "compare": compare, "insights": _insights(compare),
        "heatmap": {"cell": CELL_M, "sport": sport, "court": {"length": length, "width": width}, "frames": frames_total,
                    "all": _normalise(heat_all) if frames_total else None,
                    "earlier": _normalise(heat_early) if n_matches >= 2 and any(any(r) for r in heat_early) else None,
                    "latest": _normalise(heat_last) if any(any(r) for r in heat_last) else None},
        "zones": {z: round(v / zone_w, 3) for z, v in zones.items()} if zone_w else {},
        "shot_mix": shot_mix, "best_shots": best_shots[:5],
        "data_note": ("Built from the matches analysed with this player assigned to a side, oldest first (the order they were analysed). "
                      "Nothing is estimated beyond what each match's analysis measured; a metric is missing where a match could not measure it."),
    }
