"""Loads a finished pipeline output folder (match.json, tracks.json, overlay.mp4, clips) into the DB.
Used by `python -m api.import_match demo/out/<clip>/` and by the upload jobs. Idempotent."""
import json
import shutil
from pathlib import Path

from sqlmodel import Session, delete, select

from api.config import settings
from api.models import Dispute, Event, Insight, Match, Rally
from api.services.store import player_for_track


def import_folder(folder: Path, session: Session) -> str:
    folder = Path(folder)
    data = json.loads((folder / "match.json").read_text(encoding="utf-8"))
    mid = data["match_id"]

    dest = settings.media_dir / mid
    if folder.resolve() != dest.resolve():                    # served at /media/<id>/...
        shutil.copytree(folder, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    json_path = (dest / "match.json").resolve()

    pid = {p["track_id"]: p.get("player_id") for p in data["players"]}
    ordered = [p.get("player_id") for p in data["players"]] + [None] * 4
    score = data.get("score", {})

    # replace old rows for this match, children before parents (Postgres enforces the foreign keys:
    # disputes point at events, events at rallies, rallies at the match)
    for model in (Dispute, Insight):
        session.exec(delete(model).where(model.match_id == mid))
    old = session.exec(select(Rally.id).where(Rally.match_id == mid)).all()
    if old:
        session.exec(delete(Event).where(Event.rally_id.in_(old)))
    session.exec(delete(Rally).where(Rally.match_id == mid))
    existing = session.get(Match, mid)
    if existing:
        session.delete(existing)
    session.flush()

    session.add(Match(
        id=mid, sport=data["sport"], p1=ordered[0], p2=ordered[1], p3=ordered[2], p4=ordered[3],
        status="processed", score_json=score,
        winner_player_id=player_for_track(data, score.get("winner_track_id")),
        evidence_level="video_verified" if score.get("confirmed_by_human") else "assisted",
        video_url=data["video"]["src"], sha256=data["video"].get("sha256"), json_path=str(json_path)))
    session.flush()

    rally_ids = {}
    for r in data["rallies"]:
        row = Rally(match_id=mid, idx=r["idx"], t_start=r["t_start"], t_end=r["t_end"], hits=r["hits"],
                    winner=r.get("winner_track_id"), end_reason=r.get("end_reason"), confidence=r["confidence"])
        session.add(row)
        session.flush()
        rally_ids[r["idx"]] = row.id

    event_ids = {}
    for e in data["events"]:
        court = e.get("court") or [None, None]
        row = Event(ref=e["id"], rally_id=rally_ids[e["rally_idx"]], t=e["t"], type=e["type"],
                    track_id=e.get("track_id"), player_id=pid.get(e.get("track_id")),
                    court_x=court[0], court_y=court[1], speed_kmh=e.get("speed_kmh"),
                    speed_err=e.get("speed_err_pct"), confidence=e["confidence"],
                    interpolated=bool(e.get("interpolated", False)))
        session.add(row)
        session.flush()
        event_ids[e["id"]] = row.id

    for d in data.get("disputes", []):
        session.add(Dispute(ref=d["id"], match_id=mid, event_id=event_ids.get(d["event_id"]),
                            clip_url=d.get("clip_url"), call=d["call"], prob=d["prob"], status=d.get("status", "open")))
    for i in data.get("insights", []):
        session.add(Insight(match_id=mid, player_id=pid.get(i.get("player_track_id")), text=i["text"],
                            stat_ids=i.get("stat_ids", []), clip_ts=i.get("clip_t", [])))
    session.commit()
    return mid
