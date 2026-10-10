"""GET /v1/matches, /v1/matches/{id}, /rallies, /events, /tracks, POST /score/confirm."""
import shutil
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from api.config import settings
from api.db import get_session
from api.models import Match, Player, User
from api.schemas import MatchJSON, MatchSummary, Recalibrate, ScoreConfirm
from api.services import jobs, matches_admin, rating, store
from api.services.access import current_user

router = APIRouter(tags=["matches"])


def _load(match_id: str, session: Session) -> dict:
    try:
        return store.load_match(match_id, session)
    except KeyError:
        raise HTTPException(404, f"match {match_id} not found") from None


@router.get("/matches", response_model=list[MatchSummary])
def list_matches(session: Session = Depends(get_session)):
    rows = session.exec(select(Match).order_by(Match.created_at.desc())).all()
    out = []
    for r in rows:
        try:
            out.append(store.summarise(store.load_match(r.id, session), r.status, r.evidence_level))
        except KeyError:
            continue
    if not out and settings.mock_fallback and (settings.mock_dir / "match.json").exists():
        out.append(store.summarise(store.mock_match()))
    return out


@router.get("/matches/{match_id}", response_model=MatchJSON)
def get_match(match_id: str, session: Session = Depends(get_session)):
    return _load(match_id, session)


@router.get("/matches/{match_id}/rallies")
def get_rallies(match_id: str, session: Session = Depends(get_session)):
    return _load(match_id, session)["rallies"]


@router.get("/matches/{match_id}/events")
def get_events(match_id: str, type: str | None = None, rally_idx: int | None = None,
               session: Session = Depends(get_session)):
    events = _load(match_id, session)["events"]
    if type:
        events = [e for e in events if e["type"] == type]
    if rally_idx is not None:
        events = [e for e in events if e["rally_idx"] == rally_idx]
    return events


@router.get("/matches/{match_id}/tracks")
def get_tracks(match_id: str):
    try:
        return store.load_tracks(match_id)
    except KeyError:
        raise HTTPException(404, "tracks not available for this match") from None


@router.post("/matches/{match_id}/score/confirm")
def confirm_score(match_id: str, body: ScoreConfirm, session: Session = Depends(get_session)):
    """Human-in-the-loop correction. Stored as an override file; the match becomes video_verified
    and (once per match) updates both players' Glicko-2 ratings at full evidence weight."""
    data = _load(match_id, session)
    data["score"].update(games=body.games, confirmed_by_human=True)
    if body.winner_track_id is not None:
        data["score"]["winner_track_id"] = body.winner_track_id
    store.save_override(match_id, data)
    changes = []
    row = session.get(Match, match_id)
    if row:
        row.score_json, row.evidence_level = data["score"], "video_verified"
        row.winner_player_id = store.player_for_track(data, data["score"].get("winner_track_id"))
        session.add(row)
        session.commit()
        changes = rating.apply_match(session, row)
    return {**data["score"], "rating_update": changes}


@router.post("/matches/{match_id}/recalibrate", status_code=202)
def recalibrate(match_id: str, body: Recalibrate, session: Session = Depends(get_session)):
    """Calibrate an already-uploaded match with 4 taps and re-run the pipeline on its video in place.
    Returns a job id (progress at GET /v1/jobs/{id}). A human-confirmed score is kept as a .bak file."""
    from rallyos.calibration.template_fit import homography_from_taps
    from rallyos.sports import load_sport

    data = _load(match_id, session)
    src = settings.media_dir / match_id / "source.mp4"
    if not src.is_file():
        raise HTTPException(404, "this match has no stored source video to re-process")
    sport = body.sport or data["sport"]
    try:
        homography_from_taps(body.taps, load_sport(sport))
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from None
    up = settings.media_dir / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    video = up / f"{match_id}_recal_{int(time.time())}.mp4"
    shutil.copyfile(src, video)                     # the run rewrites media/<id>/source.mp4
    override = settings.runtime_dir / f"{match_id}.json"
    if override.exists():
        override.rename(override.with_suffix(f".json.bak-{int(time.time())}"))
    names = {p["track_id"]: p["name"] for p in data.get("players", []) if p.get("name")}
    return {"job_id": jobs.submit(video, sport, body.taps, names, match_id=match_id)}


class DeleteMatches(BaseModel):
    ids: list[str]


@router.delete("/matches/{match_id}")
def delete_one(match_id: str, session: Session = Depends(get_session)):
    """Remove an analysed match and its files (the original upload and the ratings are kept; the demo match is protected)."""
    try:
        return matches_admin.delete_match(session, match_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from None
    except KeyError:
        raise HTTPException(404, f"match {match_id} not found") from None


@router.post("/matches/delete")
def delete_many(body: DeleteMatches, session: Session = Depends(get_session)):
    """Remove several matches at once; reports which were deleted and which were skipped (and why)."""
    if not body.ids:
        raise HTTPException(400, "no match ids given")
    return matches_admin.delete_matches(session, body.ids)


class AssignPlayers(BaseModel):
    side1: str | None = None          # the player who is track 1 (the near side when the camera is behind a baseline)
    side2: str | None = None          # the player who is track 2


@router.post("/matches/{match_id}/players")
def assign_players(match_id: str, body: AssignPlayers, user: User = Depends(current_user), session: Session = Depends(get_session)):
    """Say who played: the analysis only knows a near and a far player. Once assigned, the match joins those players' history
    and analysis. Any logged-in user can do it (the demo has no match ownership yet)."""
    row = session.get(Match, match_id)
    if row is None:
        raise HTTPException(404, f"match {match_id} not found")
    for pid in (body.side1, body.side2):
        if pid and not session.get(Player, pid):
            raise HTTPException(404, f"player {pid} not found")
    if body.side1 and body.side1 == body.side2:
        raise HTTPException(400, "one player cannot be on both sides")
    row.p1, row.p2 = body.side1, body.side2
    session.add(row)
    session.commit()
    return {"match_id": match_id, "side1": row.p1, "side2": row.p2}
