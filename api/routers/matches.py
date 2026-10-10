"""GET /v1/matches, /v1/matches/{id}, /rallies, /events, /tracks, POST /score/confirm."""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from api.config import settings
from api.db import get_session
from api.models import Match
from api.schemas import MatchJSON, MatchSummary, ScoreConfirm
from api.services import rating, store

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
