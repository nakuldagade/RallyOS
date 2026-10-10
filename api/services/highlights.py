"""Match highlights: list them, and cut them for matches analysed before the feature existed.

A new analysis (upload or live) cuts its own highlight at the end of the run. `backfill` does the same for stored matches: it
rates the shots from the stored events and tracks (the same rules as a fresh run), picks the best one and cuts the clip from the
match's source video, then writes the result into the stored match.json.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import Session, select

from api.config import settings
from api.models import Match
from api.services import store

MOCK_IDS = {"m_001"}


def listing(session: Session) -> dict:
    """Every analysed match that has a highlight, newest first, plus how many matches have none (and why, where it is known)."""
    items, without = [], 0
    for row in session.exec(select(Match).order_by(Match.created_at.desc())).all():
        if row.id in MOCK_IDS:
            continue
        try:
            data = store.load_match(row.id, session)
        except KeyError:
            continue
        hl = data.get("highlight")
        if not hl:
            without += 1
            continue
        side = {p["track_id"]: p for p in data.get("players", [])}
        items.append({"match_id": row.id, "date": row.created_at, "sport": data.get("sport"), "duration_s": data.get("video", {}).get("duration_s"),
                      "players": [p.get("name") for p in data.get("players", [])],
                      "best_player": (side.get(hl.get("track_id")) or {}).get("name"), "highlight": hl})
    return {"highlights": items, "matches_without": without}


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def backfill(session: Session, force: bool = False, only: str | None = None) -> list[tuple[str, str]]:
    """Cut a highlight for each stored match that lacks one. Returns [(match_id, "made" | the reason it was not)]."""
    from rallyos.analytics.bestshot import rate_shots
    from rallyos.sports import load_sport
    from rallyos.stages import make_highlight

    done: list[tuple[str, str]] = []
    for row in session.exec(select(Match).order_by(Match.created_at)).all():
        if row.id in MOCK_IDS or (only and row.id != only) or not row.json_path or not Path(row.json_path).exists():
            continue
        path = Path(row.json_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("highlight") and not force:
            done.append((row.id, "already has one"))
            continue
        video = settings.media_dir / row.id / "source.mp4"
        if not video.exists():
            done.append((row.id, "no source video"))
            continue
        try:
            tracks = store.load_tracks(row.id)
        except KeyError:
            done.append((row.id, "no tracks file"))
            continue
        frames = tracks.get("frames", [])
        fps = float(tracks.get("fps") or data["video"]["fps"])
        per_player = data.get("stats", {}).get("per_player") or {}
        if not per_player:
            done.append((row.id, "no player stats (court not calibrated)"))
            continue
        rate_shots(data["events"], data["rallies"], frames, fps, load_sport(data["sport"]), per_player)
        balls = [fr.get("ball") for fr in frames]
        hl = make_highlight(video, video.parent, row.id, per_player, data["events"], balls, fps, frames)
        if hl is None:
            done.append((row.id, "no shot could be rated" if not any(p.get("best_shot") for p in per_player.values()) else "the clip could not be written"))
            _write(path, data)                          # the ratings are still worth keeping
            continue
        data["highlight"] = hl
        _write(path, data)
        override = settings.runtime_dir / f"{row.id}.json"
        if override.exists():                           # a human-confirmed score file: keep its copy in step
            od = json.loads(override.read_text(encoding="utf-8"))
            od["highlight"], od["stats"], od["events"] = hl, data["stats"], data["events"]
            _write(override, od)
        done.append((row.id, "made"))
    return done
