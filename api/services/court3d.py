"""Data for the 3D court viewer (Smart Courts): a match as flights, player positions and heat grids in court metres.

Who may see what is decided here, on the server:
  * a coach sees both sides of a match in which at least one assigned player is on their roster (to compare the players);
  * a player sees both sides (themselves and the opponent they faced) of the matches THEY played, and nothing at all of any
    other match: a match they were not in is refused, and is not even listed.
Every number comes from an analysed match (events, tracks.json). The 3D heights of a flight are reconstructed (see
core/rallyos/analytics/flights3d.py) and every flight says whether it is a physics solution or an estimate.
"""
from __future__ import annotations

from sqlmodel import Session, select

from api.models import Match, Player, User
from api.services import store
from api.services.access import player_of, roster_ids

MOCK_IDS = {"m_001"}
CELL_M = 0.5
POSITION_HZ = 10
PALETTE = ["#22c55e", "#3b82f6", "#f59e0b", "#ef4444", "#a855f7", "#14b8a6", "#ec4899", "#eab308"]
SEEDED = ["p_anika", "p_rohan", "p_meera", "p_kabir", "p_isha"]


def color_for(player_id: str | None, track_id: int) -> str:
    """One colour per person, the same everywhere: a seed player has their own; anyone else is coloured by a hash of the id;
    a side nobody was assigned to is blue (near) or red (far)."""
    if player_id is None:
        return "#3b82f6" if track_id == 1 else "#ef4444"
    if player_id in SEEDED:
        return PALETTE[SEEDED.index(player_id)]
    return PALETTE[sum(ord(c) for c in player_id) % len(PALETTE)]


def _allowed_tracks(user: User, row: Match, session: Session) -> dict[int, str | None] | None:
    """{track_id: player_id} this user may see in the match, or None when the match is not theirs at all."""
    sides = {1: row.p1, 2: row.p2}
    if user.role == "player":
        me = player_of(user, session)
        return sides if me and me.id in (row.p1, row.p2) else None
    if user.role == "coach":
        ids = set(roster_ids(user, session))
        return sides if any(p in ids for p in sides.values() if p) else None
    return None


def visible_matches(user: User, session: Session) -> list[dict]:
    out = []
    for row in session.exec(select(Match).order_by(Match.created_at.desc())).all():
        if row.id in MOCK_IDS or not (row.p1 or row.p2):
            continue
        tracks = _allowed_tracks(user, row, session)
        if not tracks:
            continue
        try:
            data = store.load_match(row.id, session)
        except KeyError:
            continue
        names = {p["track_id"]: p.get("name") for p in data.get("players", [])}
        out.append({"match_id": row.id, "date": row.created_at, "sport": data.get("sport"), "duration_s": data.get("video", {}).get("duration_s"),
                    "players": [{"track_id": t, "player_id": p, "name": names.get(t), "color": color_for(p, t)} for t, p in tracks.items()]})
    return out


def _heat(frames: list[dict], track_id: int, length: float, width: float, clamp: bool = False) -> dict | None:
    import math

    rows, cols = math.ceil(length / CELL_M), math.ceil(width / CELL_M)
    grid = [[0.0] * cols for _ in range(rows)]
    n = 0
    for fr in frames:
        p = next((q for q in fr["players"] if q["track_id"] == track_id), None)
        if not p or not p.get("court"):
            continue
        x, y = p["court"]
        if clamp:                                             # a table sport: players stand beside / behind the table, drawn on its edge
            x, y = min(max(x, 0.0), width - 1e-6), min(max(y, 0.0), length - 1e-6)
        r, c = int(y // CELL_M), int(x // CELL_M)
        if 0 <= r < rows and 0 <= c < cols:
            grid[r][c] += 1
            n += 1
    if not n:
        return None
    top = max(max(r) for r in grid)
    return {"cell": CELL_M, "grid": [[round(v / top, 3) for v in r] for r in grid], "frames": n}


def _positions(frames: list[dict], fps: float, track_id: int) -> list[list[float]]:
    step = max(1, round(fps / POSITION_HZ))
    out = []
    for fr in frames[::step]:
        p = next((q for q in fr["players"] if q["track_id"] == track_id), None)
        if p and p.get("court"):
            out.append([round(fr["f"] / fps, 3), round(p["court"][0], 2), round(p["court"][1], 2)])
    return out


def scene(user: User | None, match_id: str, session: Session, open_if_unassigned: bool = False) -> dict | None:
    """The viewer payload for one match, or None if this user may not see it (the router answers 403).

    open_if_unassigned (the 3D view on a match's own page): a match nobody was assigned to has no owner to protect, so anyone who
    can open the match can open its 3D view; once players are assigned, the rules above apply again."""
    from rallyos.analytics.flights3d import reconstruct
    from rallyos.sports import load_sport

    row = session.get(Match, match_id)
    if row is None or match_id in MOCK_IDS:
        raise KeyError(match_id)
    if open_if_unassigned and not (row.p1 or row.p2):
        allowed = {1: None, 2: None}
    else:
        allowed = _allowed_tracks(user, row, session) if user is not None else None
    if not allowed:
        return None
    data = store.load_match(match_id, session)
    try:
        tracks = store.load_tracks(match_id)
    except KeyError:
        tracks = {"fps": data["video"]["fps"], "frames": []}
    fps = float(tracks.get("fps") or data["video"]["fps"])
    return build_payload(data, tracks.get("frames", []), fps, allowed, match_id, row.created_at, data.get("video", {}).get("duration_s"))


def live_scene(data: dict, frames: list[dict], fps: float, session_id: str) -> dict:
    """The same payload for a live session, from what has been analysed so far (both sides: the session has no assigned players)."""
    from datetime import datetime, timezone

    duration = round(len(frames) / fps, 2) if fps else None
    return build_payload(data, frames, fps, {1: None, 2: None}, f"live:{session_id}", datetime.now(timezone.utc).isoformat(timespec="seconds"), duration)


def build_payload(data: dict, frames: list[dict], fps: float, allowed: dict, match_id: str, date: str, duration_s) -> dict:
    from rallyos.analytics.flights3d import reconstruct
    from rallyos.sports import load_sport

    cfg = load_sport(data["sport"])
    court = cfg["court"]
    meta = {p["track_id"]: p for p in data.get("players", [])}
    flights = [f for f in reconstruct(data["events"], fps, cfg, frames) if f["track_id"] in allowed]
    length, width = float(court["length"]), float(court["width"])
    return {
        "match_id": match_id, "date": date, "sport": data["sport"], "fps": fps, "duration_s": duration_s,
        "court": {"length": length, "width": width, "lines": court["lines"], "net": cfg.get("net") or {}, "walls": cfg.get("walls") or [],
                  "view3d": cfg.get("view3d") or {}},
        "players": [{"track_id": t, "player_id": pid, "name": (meta.get(t) or {}).get("name") or f"Player {t}", "side": (meta.get(t) or {}).get("side"),
                     "color": color_for(pid, t)} for t, pid in allowed.items()],
        "object_size_m": (cfg.get("projectile") or {}).get("size_m"),
        "flights": flights,
        "positions": {str(t): _positions(frames, fps, t) for t in allowed},
        "heat": {str(t): _heat(frames, t, length, width, clamp="surface_height_m" in court) for t in allowed},
        "notes": {"heights": "Shot heights are reconstructed from the measured end points, the measured time and a drag law (solid paths) or a gravity-only arc (dashed paths): one camera does not measure height.",
                  "positions": "Player positions are the feet on the court plane from the homography."},
    }
