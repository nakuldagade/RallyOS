"""GET /v1/players, /v1/players/{id}, /trends."""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from api.db import get_session
from api.models import Player, RatingHistory, User
from api.services import player_analysis
from api.services.access import can_view_player, current_user

router = APIRouter(tags=["players"])


@router.get("/players")
def list_players(sport: str | None = None, session: Session = Depends(get_session)):
    q = select(Player)
    if sport:
        q = q.where(Player.sport == sport)
    return session.exec(q.order_by(Player.rating.desc())).all()


@router.get("/players/{player_id}")
def get_player(player_id: str, session: Session = Depends(get_session)):
    p = session.get(Player, player_id)
    if not p:
        raise HTTPException(404, "player not found")
    return p


@router.get("/players/{player_id}/trends")
def trends(player_id: str, session: Session = Depends(get_session)):
    rows = session.exec(select(RatingHistory).where(RatingHistory.player_id == player_id)
                        .order_by(RatingHistory.at, RatingHistory.id)).all()
    return {"player_id": player_id, "rating_history": rows}


@router.get("/players/{player_id}/analysis")
def player_analysis_view(player_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    """History and full analysis of one player over all their analysed matches. A player sees their own, a coach sees the
    players on their roster; anyone else gets 403."""
    if not can_view_player(user, player_id, session):
        raise HTTPException(403, "you can only open your own analysis, or a player on your roster")
    try:
        return player_analysis.analysis(session, player_id)
    except KeyError:
        raise HTTPException(404, "player not found") from None
