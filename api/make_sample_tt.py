"""CLI:  python -m api.make_sample_tt   -> a table-tennis player (Tara) with three SAMPLE matches, her login and her coach.

THIS DATA IS GENERATED, NOT MEASURED. There is no analysed table-tennis video in this project, so each match here is a
simulated game (rally scoring to 11, serve changes every 2 points, players moving to the ball and back to their base) whose
numbers are then computed with the same analytics code as a real clip (movement, zones, return to base, fatigue, best shot).
Every match carries `"synthetic": true`, a "(sample data)" title and a watermark on its animation, and the app says so.
Tara is built to improve over the three matches (faster recovery, more points won) so a history has something to show.
The "video" is a top-down animation of the simulated game, not footage.

    python -m api.make_sample_tt            # generate, create players / logins / roster, import
    python -m api.make_sample_tt --remove   # take the sample players and matches out again
"""
import argparse
import hashlib
import json
import math
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

FPS = 30.0
W_PX, H_PX = 960, 540
SCALE, Y_OFF, OY = 150.0, 1.8, 155.0           # court metres -> animation pixels (length runs left to right)
TARA = {"id": "p_tara", "name": "Tara", "rating": 1540, "rd": 110, "style_vec": [0.7, 0.6, 0.5, 0.6], "lat": 19.1, "lng": 72.9}
OPPONENTS = [
    {"id": "p_dev", "name": "Dev", "rating": 1585, "rd": 90, "style_vec": [0.6, 0.7, 0.4, 0.6], "lat": 19.05, "lng": 72.88},
    {"id": "p_neel", "name": "Neel", "rating": 1520, "rd": 100, "style_vec": [0.5, 0.5, 0.6, 0.7], "lat": 19.15, "lng": 72.95},
]
# Tara improves from match to match: she recovers faster, moves quicker and wins more rallies.
SPECS = [
    {"id": "m_tt_001", "opp": "p_dev", "seed": 11, "p_win": 0.42, "speed": 2.3, "delay0": 0.42, "delay_slope": 0.30, "spread": 0.95, "tara_serves": True, "days_ago": 21},
    {"id": "m_tt_002", "opp": "p_neel", "seed": 23, "p_win": 0.50, "speed": 2.8, "delay0": 0.30, "delay_slope": 0.14, "spread": 1.00, "tara_serves": False, "days_ago": 12},
    {"id": "m_tt_003", "opp": "p_dev", "seed": 37, "p_win": 0.58, "speed": 3.2, "delay0": 0.22, "delay_slope": 0.05, "spread": 1.05, "tara_serves": True, "days_ago": 3},
]


def _cfg() -> dict:
    from rallyos.sports import load_sport

    return load_sport("table_tennis")


def _matrix() -> np.ndarray:
    """court (x across, y along, metres) -> animation pixel."""
    return np.array([[0.0, SCALE, SCALE * Y_OFF], [SCALE, 0.0, OY], [0.0, 0.0, 1.0]])


def to_px(x: float, y: float) -> list[float]:
    m = _matrix()
    return [round(float(m[0, 1] * y + m[0, 2]), 1), round(float(m[1, 0] * x + m[1, 2]), 1)]


# -- the simulated game --------------------------------------------------------------------------------------

def _game(spec: dict, rng: np.random.Generator, length: float, width: float) -> dict:
    """Rallies of one game to 11 (win by 2). Track 1 = Tara (near end), track 2 = the opponent (far end)."""
    score = [0, 0]
    server = 1 if spec["tara_serves"] else 2
    since = 0
    t = 2.0
    rallies, events = [], []
    own: dict[int, list] = {1: [], 2: []}          # per player: (t, (x, y)) of each of their hits
    flights = []                                    # ball path pieces: (t0, p0, tb, pb, t1, p1)
    while not (max(score) >= 11 and abs(score[0] - score[1]) >= 2):
        p_tara = min(0.9, max(0.1, spec["p_win"] + (0.03 if server == 1 else -0.03)))
        winner = 1 if rng.random() < p_tara else 2
        loser = 3 - winner
        in_end = rng.random() < 0.62                 # the winner's shot is not returned (else the loser's shot goes out / into the net)
        last_hitter = winner if in_end else loser
        n = int(min(14, 1 + rng.geometric(0.30)))
        n_serve_side = n % 2 == 1                    # hit 0 is the server; the last hit is the server's when n is odd
        if (last_hitter == server) != n_serve_side:
            n += 1
        hitters = [server if i % 2 == 0 else 3 - server for i in range(n)]
        t0 = t
        times = [t0]
        for i in range(1, n):
            times.append(times[-1] + (rng.uniform(0.85, 1.15) if i == 1 else rng.uniform(0.55, 0.95)))
        ridx = len(rallies)
        hits = []
        for i, (ti, who) in enumerate(zip(times, hitters)):
            x = float(np.clip(rng.normal(width / 2, spec["spread"] * (0.6 if i == 0 else 1.0)), -1.0, width + 1.0))
            d = float(np.clip(rng.normal(0.95, 0.6), 0.2, 2.2))
            y = -d if who == 1 else length + d
            hits.append({"t": ti, "who": who, "pos": (x, y)})
            own[who].append((ti, (x, y)))
        # where each ball lands: on the receiver's half
        for i, h in enumerate(hits):
            recv_far = h["who"] == 1
            by = length / 2 + rng.uniform(0.3, 1.25) if recv_far else length / 2 - rng.uniform(0.3, 1.25)
            h["bounce"] = (float(rng.uniform(0.15, width - 0.15)), float(by))
        last = hits[-1]
        out_land = None
        if in_end:
            land = last["bounce"]
            call, p_in, margin = "IN", 0.97, round(float(min(land[0], width - land[0], abs(land[1] - length / 2))), 3)
        else:
            if rng.random() < 0.5:                    # long
                land = (float(rng.uniform(0.2, width - 0.2)), length + rng.uniform(0.15, 0.5) if last["who"] == 1 else -rng.uniform(0.15, 0.5))
            else:                                     # wide
                land = (width + rng.uniform(0.1, 0.4) if rng.random() < 0.5 else -rng.uniform(0.1, 0.4), float(last["bounce"][1]))
            call, p_in, margin = "OUT", 0.02, -round(float(rng.uniform(0.1, 0.4)), 3)
            out_land = land
        t_end = times[-1] + 0.7
        for i, h in enumerate(hits):
            nxt = hits[i + 1] if i + 1 < len(hits) else None
            t1 = nxt["t"] if nxt else times[-1] + 0.45
            p1 = nxt["pos"] if nxt else land
            bounce = h["bounce"] if nxt or in_end else land
            flights.append((h["t"], h["pos"], h["t"] + 0.55 * (t1 - h["t"]), bounce, t1, p1))
        score[winner - 1] += 1
        rallies.append({"idx": ridx, "t_start": round(t0, 2), "t_end": round(t_end, 2), "hits": n, "winner_track_id": winner,
                        "end_reason": "landing_in" if in_end else "landing_out", "score_after": f"{score[0]}-{score[1]}",
                        "confidence": round(float(rng.uniform(0.78, 0.92)), 2), "winner_confidence": round(float(rng.uniform(0.8, 0.93)), 2),
                        "hitter_conflict": False})
        for i, h in enumerate(hits):
            events.append({"rally_idx": ridx, "t": round(h["t"], 3), "type": "hit", "track_id": h["who"], "court": [round(h["pos"][0], 2), round(h["pos"][1], 2)],
                           "px": to_px(*h["pos"]), "shot_idx": i, "n_in_rally": n})
        events.append({"rally_idx": ridx, "t": round(times[-1] + 0.45, 3), "type": "landing", "track_id": None,
                       "court": [round(land[0], 3), round(land[1], 3)], "px": to_px(*land), "call": call, "call_prob": 1 - p_in if call == "OUT" else p_in,
                       "p_in": p_in, "ellipse_m": [0.03, 0.02, 0.0], "margin_m": margin, "confidence": 0.8, "source": ["vision"], "interpolated": False})
        since += 1
        if since >= (1 if min(score) >= 10 else 2):
            server, since = 3 - server, 0
        t = t_end + float(rng.uniform(2.5, 4.0))
    duration = round(t + 1.0, 2)
    return {"score": score, "rallies": rallies, "events": events, "own": own, "flights": flights, "duration": duration}


SHOT_AFTER_SERVE = (["push", "flick", "loop"], [0.55, 0.15, 0.30])


def _label(events: list[dict], rng: np.random.Generator, smash_rate: float) -> None:
    """Shot names from the table-tennis YAML's vocabulary (serve / push / loop / flick / smash), chosen by position in the rally."""
    for e in events:
        if e["type"] != "hit":
            continue
        i, n = e.pop("shot_idx"), e.pop("n_in_rally")
        if i == 0:
            shot = "serve"
        elif i == 1:
            shot = str(rng.choice(SHOT_AFTER_SERVE[0], p=SHOT_AFTER_SERVE[1]))
        else:
            r = rng.random()
            shot = "smash" if (r < smash_rate and i >= 3) else ("loop" if r < 0.62 else "push" if r < 0.85 else "flick")
        e["shot"] = shot
        e["shot_conf"] = round(float(rng.uniform(0.6, 0.85)), 2)
        e["shot_why"] = f"Sample data: the {shot} label is generated for this simulated rally, not read from video."
        e["shot_features"] = {"first_hit_of_rally": i == 0, "wrist_above_head": None}
        e["speed_kmh"] = None
        e["speed_err_pct"] = None
        e["confidence"] = round(float(rng.uniform(0.82, 0.95)), 2)
        e["source"] = ["audio", "vision"]


def _keyframes(hits: list[tuple], base: tuple, spec_speed: float, delay0: float, slope: float, duration: float,
               rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Times and (x, y) of a player: stand at base, move to each hit, react, then go back to base."""
    ts, ps = [0.0], [base]
    prev_t, prev_p = 0.0, base
    for t_j, p_j in hits:
        d = max(0.05, delay0 + slope * (prev_t / duration) + float(rng.normal(0, 0.04))) if prev_t > 0 else 0.0
        t_leave = prev_t + d
        arrive = t_leave + math.dist(prev_p, base) / spec_speed
        depart = t_j - math.dist(base, p_j) / spec_speed
        if prev_t > 0 and arrive <= depart:
            ts += [t_leave, arrive, depart, t_j]
            ps += [prev_p, base, base, p_j]
        elif prev_t > 0:
            t_leave = min(t_leave, t_j - 0.15)
            ts += [t_leave, t_j]
            ps += [prev_p, p_j]
        else:
            ts += [max(t_j - math.dist(base, p_j) / spec_speed, 0.1), t_j]
            ps += [base, p_j]
        prev_t, prev_p = t_j, p_j
    ts.append(duration)
    ps.append(base)
    ts = np.maximum.accumulate(np.array(ts, dtype=float))
    ts += np.arange(len(ts)) * 1e-6
    return ts, np.array(ps, dtype=float)


def _frames(game: dict, spec: dict, rng: np.random.Generator, cfg: dict, base_for) -> list[dict]:
    n = int(game["duration"] * FPS)
    times = np.arange(n) / FPS
    pos = {}
    for tid, speed_mult, delay_mult in ((1, 1.0, 1.0), (2, 0.92, 1.0)):
        side = "near" if tid == 1 else "far"
        spd = (spec["speed"] if tid == 1 else 2.6) * speed_mult
        d0 = spec["delay0"] if tid == 1 else 0.30
        slope = spec["delay_slope"] if tid == 1 else 0.12
        ts, ps = _keyframes(game["own"][tid], base_for(cfg, side), spd, d0 * delay_mult, slope, game["duration"], rng)
        xy = np.stack([np.interp(times, ts, ps[:, 0]), np.interp(times, ts, ps[:, 1])], axis=1)
        pos[tid] = xy + rng.normal(0, 0.008, xy.shape)
    flights = game["flights"]
    frames = []
    for f in range(n):
        t = f / FPS
        ball = None
        for t0, p0, tb, pb, t1, p1 in flights:
            if t0 <= t <= t1:
                a, b, u = (p0, pb, (t - t0) / (tb - t0)) if t <= tb else (pb, p1, (t - tb) / (t1 - tb))
                bx, by = a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u
                ball = {"px": to_px(bx, by), "court": [round(bx, 3), round(by, 3)], "conf": 0.9, "interp": False}
                break
        players = []
        for tid in (1, 2):
            x, y = float(pos[tid][f, 0]), float(pos[tid][f, 1])
            px, py = to_px(x, y)
            players.append({"track_id": tid, "bbox": [round(px - 16, 1), round(py - 46, 1), round(px + 16, 1), round(py + 6, 1)],
                            "court": [round(x, 3), round(y, 3)], "kp": []})
        frames.append({"f": f, "players": players, "ball": ball})
    return frames


# -- the match record ----------------------------------------------------------------------------------------

def build_match(spec: dict, out_dir: Path, opponent_name: str, render_video: bool = True) -> dict:
    """Simulate one game, compute its stats with the real analytics code, write match.json / tracks.json (+ animation)."""
    from rallyos.analytics.bestshot import rate_shots
    from rallyos.analytics.movement import (base_for, fatigue_trend, movement_speed_between, movement_stats, return_stats,
                                            return_to_base, zone_time)
    from rallyos.analytics.shots import shot_mix

    cfg = _cfg()
    length, width = float(cfg["court"]["length"]), float(cfg["court"]["width"])
    rng = np.random.default_rng(spec["seed"])
    game = _game(spec, rng, length, width)
    _label(game["events"], rng, smash_rate=0.04 + 0.05 * (spec["p_win"] - 0.42) / 0.16)
    events = sorted(game["events"], key=lambda e: e["t"])
    for i, e in enumerate(events):
        e["id"] = f"e_{i + 1:04d}"
    frames = _frames(game, spec, rng, cfg, base_for)
    stride = 3
    pts = {tid: [(fr["f"] / FPS, tuple(p["court"])) for fr in frames[::stride] for p in fr["players"] if p["track_id"] == tid] for tid in (1, 2)}
    hit_events = [e for e in events if e["type"] == "hit"]
    per_player: dict[str, dict] = {}
    for tid in (1, 2):
        mine = [e for e in hit_events if e["track_id"] == tid]
        nxt = {}
        for e in mine:
            reply = next((o for o in hit_events if o["rally_idx"] == e["rally_idx"] and o["t"] > e["t"] and o["track_id"] != tid), None)
            nxt[e["t"]] = reply["t"] if reply else None
        side = "near" if tid == 1 else "far"
        res = return_to_base(pts[tid], [e["t"] for e in mine], nxt, base_for(cfg, side))
        for e in mine:
            r = res.get(e["t"])
            if r:
                e["return_to_base_s"], e["returned_to_base"] = r["return_s"], r["returned"]
        stats = {"tracked_pct": 1.0, "hits": len(mine)}
        stats.update(movement_stats(pts[tid]))
        stats.update(zone_time([c for _, c in pts[tid]], cfg, side))
        stats["shot_mix"] = shot_mix(events, tid)
        stats.update(return_stats(res))
        stats["fatigue"] = fatigue_trend([{"t": t, "return_s": None if r.get("was_at_base") else r["return_s"],
                                           "speed_mps": movement_speed_between(pts[tid], t, t + (r["return_s"] or 1.0) + 0.5)} for t, r in res.items()])
        per_player[str(tid)] = stats
    rate_shots(events, game["rallies"], frames, FPS, cfg, per_player)

    mid = spec["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    balls = [fr["ball"] for fr in frames]
    (out_dir / "tracks.json").write_text(json.dumps({"fps": FPS, "frames": frames}), encoding="utf-8")
    sha = None
    if render_video:
        from api.sample_animation import render
        render(out_dir / "source.mp4", frames, game["rallies"], opponent_name)
        sha = hashlib.sha256((out_dir / "source.mp4").read_bytes()).hexdigest()
    a, b = game["score"]
    corners = [to_px(0, 0), to_px(0, length), to_px(width, length), to_px(width, 0)]
    data = {
        "schema_version": "1.1", "match_id": mid, "title": f"Tara vs {opponent_name} (sample data)", "synthetic": True, "sport": "table_tennis",
        "sport_confidence": None, "sport_source": "sample data (generated)",
        "video": {"src": f"/media/{mid}/source.mp4", "overlay": None, "fps": FPS, "width": W_PX, "height": H_PX, "duration_s": game["duration"], "sha256": sha},
        "calibration": {"method": "4-tap", "homography": np.linalg.inv(_matrix()).round(8).tolist(), "focal_px": None, "reprojection_error_px": None,
                        "taps_px": corners, "camera_position_m": None, "note": "Sample data: the picture is a generated top-down animation, not a camera view."},
        "players": [{"track_id": 1, "player_id": TARA["id"], "name": "Tara", "side": "near", "color": "#3b82f6"},
                    {"track_id": 2, "player_id": spec["opp"], "name": opponent_name, "side": "far", "color": "#ef4444"}],
        "tracks_url": f"/media/{mid}/tracks.json", "rallies": game["rallies"], "events": events,
        "score": {"games": [[a, b]], "winner_track_id": 1 if a > b else 2, "confirmed_by_human": False, "score_str": f"{a}-{b}",
                  "source": "sample data (simulated game)", "unresolved_rallies": 0, "from_clip_start": True},
        "stats": {"per_player": per_player,
                  "match": {"rallies": len(game["rallies"]), "avg_rally_hits": round(sum(r["hits"] for r in game["rallies"]) / len(game["rallies"]), 1),
                            "longest_rally_hits": max(r["hits"] for r in game["rallies"])},
                  "pipeline": {"synthetic": True, "note": "Generated game: positions, hits and calls are simulated; the statistics are computed from them with the real analytics code."}},
        "disputes": [], "insights": [],
    }
    if render_video:
        from rallyos.stages import make_highlight
        hl = make_highlight(out_dir / "source.mp4", out_dir, mid, per_player, events, balls, FPS, frames)
        if hl:
            data["highlight"] = hl
    (out_dir / "match.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


# -- database ------------------------------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--no-video", action="store_true")
    a = ap.parse_args()
    from sqlmodel import Session, select

    from api.config import settings
    from api.db import create_all, engine
    from api.models import CoachPlayer, Credential, Match, Player, RatingHistory, User
    from api.seed import seed_accounts
    from api.services.importer import import_folder

    create_all()
    ids = [s["id"] for s in SPECS]
    people = [TARA] + OPPONENTS
    with Session(engine) as s:
        if a.remove:
            from api.services.matches_admin import delete_matches
            delete_matches(s, [i for i in ids if s.get(Match, i)])
            for p in people:
                for r in s.exec(select(CoachPlayer).where(CoachPlayer.player_id == p["id"])).all():
                    s.delete(r)
                for r in s.exec(select(RatingHistory).where(RatingHistory.player_id == p["id"])).all():
                    s.delete(r)
                row = s.get(Player, p["id"])
                if row:
                    user = s.get(User, row.user_id) if row.user_id else None
                    s.delete(row)
                    s.flush()
                    if user:
                        cred = s.get(Credential, user.id)
                        if cred:
                            s.delete(cred)
                        s.delete(user)
            s.commit()
            print("sample table-tennis players and matches removed")
            return
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for p in people:
            if not s.get(Player, p["id"]):
                s.add(Player(sport="table_tennis", **p))
                for i in range(5):
                    s.add(RatingHistory(player_id=p["id"], rating=p["rating"] - (4 - i) * 10, rd=p["rd"], at=(now - timedelta(days=(4 - i) * 14)).isoformat(timespec="seconds")))
        s.commit()
        print("accounts:", seed_accounts(s) or "already there")
        names = {p["id"]: p["name"] for p in people}
        for spec in SPECS:
            out = settings.out_dir / spec["id"]
            build_match(spec, out, names[spec["opp"]], render_video=not a.no_video)
            import_folder(out, s)
            m = s.get(Match, spec["id"])
            m.created_at = (now - timedelta(days=spec["days_ago"])).isoformat(timespec="seconds")
            s.add(m)
            s.commit()
            print("imported", spec["id"])


if __name__ == "__main__":
    main()
