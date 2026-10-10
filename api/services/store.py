"""Single place that answers 'give me match.json for id X'.
Order: human-confirmed override -> imported match in DB -> data/mock/match.json (if MOCK_FALLBACK)."""
import json
from pathlib import Path
from typing import Optional

from sqlmodel import Session

from api.config import settings
from api.models import Match


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def mock_match() -> dict:
    return _read(settings.mock_dir / "match.json")


def _assigned(data: dict, row: Optional[Match], session: Optional[Session]) -> dict:
    """The players chosen for side 1 and side 2 (Match.p1 / p2) replace the generic names in the players list."""
    if row is None or session is None:
        return data
    from api.models import Player

    for tid, pid in ((1, row.p1), (2, row.p2)):
        pl = session.get(Player, pid) if pid else None
        meta = next((p for p in data.get("players", []) if p["track_id"] == tid), None)
        if pl and meta is not None:
            meta["player_id"], meta["name"] = pl.id, pl.name
    return data


def load_match(match_id: str, session: Optional[Session] = None) -> dict:
    row = session.get(Match, match_id) if session is not None else None
    override = settings.runtime_dir / f"{match_id}.json"
    if override.exists():
        return _assigned(_read(override), row, session)
    if session is not None:
        if row and row.json_path and Path(row.json_path).exists():
            return _assigned(_read(Path(row.json_path)), row, session)
    if settings.mock_fallback:
        data = mock_match()
        if data["match_id"] == match_id:
            return data
    raise KeyError(match_id)


def save_override(match_id: str, data: dict) -> None:
    (settings.runtime_dir / f"{match_id}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_tracks(match_id: str) -> dict:
    for p in (settings.media_dir / match_id / "tracks.json", settings.mock_dir / "tracks.json"):
        if p.exists():
            return _read(p)
    raise KeyError(match_id)


def player_for_track(data: dict, track_id: Optional[int]) -> Optional[str]:
    return next((p.get("player_id") for p in data.get("players", []) if p["track_id"] == track_id), None)


def summarise(data: dict, status: str = "processed", evidence: str = "assisted") -> dict:
    names = [p.get("name") or f"Player {p['track_id']}" for p in data.get("players", [])]
    score = data.get("score", {})
    return {
        "match_id": data["match_id"], "title": data.get("title"), "sport": data["sport"], "status": status, "players": names,
        "games": score.get("games", []), "winner_track_id": score.get("winner_track_id"),
        "confirmed_by_human": score.get("confirmed_by_human", False), "evidence_level": evidence,
        "duration_s": data.get("video", {}).get("duration_s"), "rallies": len(data.get("rallies", [])),
        "sha256": data.get("video", {}).get("sha256"),
        "ball_tracker": data.get("stats", {}).get("ball", {}).get("tracker"),
    }
