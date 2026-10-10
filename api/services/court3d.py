"""Data for the 3D court viewer (Smart Courts): a match as flights, player positions and heat grids in court metres.

Who may see what is decided here, on the server:
  * a coach sees both sides of a match in which at least one assigned player is on their roster (to compare the players);
  * a player sees ONLY their own side of a match they played: the other player's flights, positions and heatmap are never sent.
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
        mine = {t: p for t, p in sides.items() if me and p == me.id}
        return mine or None
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


def _heat(frames: list[dict], track_id: int, length: float, width: float) -> dict | None:
    import math

    rows, cols = math.ceil(length / CELL_M), math.ceil(width / CELL_M)
    grid = [[0.0] * cols for _ in range(rows)]
    n = 0
    for fr in frames:
        p = next((q for q in fr["players"] if q["track_id"] == track_id), None)
        if not p or not p.get("court"):
            continue
        r, c = int(p["court"][1] // CELL_M), int(p["court"][0] // CELL_M)
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


def scene(user: User, match_id: str, session: Session) -> dict | None:
    """The viewer payload for one match, or None if this user may not see it (the router answers 403)."""
    from rallyos.analytics.flights3d import reconstruct
    from rallyos.sports import load_sport

    row = session.get(Match, match_id)
    if row is None or match_id in MOCK_IDS:
        raise KeyError(match_id)
    allowed = _allowed_tracks(user, row, session)
    if not allowed:
        return None
    data = store.load_match(match_id, session)
    cfg = load_sport(data["sport"])
    court = cfg["court"]
    try:
        tracks = store.load_tracks(match_id)
    except KeyError:
        tracks = {"fps": data["video"]["fps"], "frames": []}
    fps = float(tracks.get("fps") or data["video"]["fps"])
    frames = tracks.get("frames", [])
    meta = {p["track_id"]: p for p in data.get("players", [])}
    flights = [f for f in reconstruct(data["events"], fps, cfg, frames) if f["track_id"] in allowed]
    length, width = float(court["length"]), float(court["width"])
    return {
        "match_id": match_id, "date": row.created_at, "sport": data["sport"], "fps": fps, "duration_s": data.get("video", {}).get("duration_s"),
        "court": {"length": length, "width": width, "lines": court["lines"], "net": cfg.get("net") or {}},
        "players": [{"track_id": t, "player_id": pid, "name": (meta.get(t) or {}).get("name") or f"Player {t}", "side": (meta.get(t) or {}).get("side"),
                     "color": color_for(pid, t)} for t, pid in allowed.items()],
        "flights": flights,
        "positions": {str(t): _positions(frames, fps, t) for t in allowed},
        "heat": {str(t): _heat(frames, t, length, width) for t in allowed},
        "notes": {"heights": "Shot heights are reconstructed from the measured end points, the measured time and a drag law (solid paths) or a gravity-only arc (dashed paths): one camera does not measure height.",
                  "positions": "Player positions are the feet on the court plane from the homography."},
    }
