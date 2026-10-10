"""GET /v1/matchmaking, GET /v1/predict."""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from api.db import get_session
from api.models import Match, Player
from api.services import matchmaking, predict

router = APIRouter(tags=["network"])


@router.get("/matchmaking")
def matchmaking_(player_id: str, radius_km: float = 25.0, session: Session = Depends(get_session)):
    me = session.get(Player, player_id)
    if not me:
        raise HTTPException(404, "player not found")
    return matchmaking.suggest(me, session.exec(select(Player)).all(), radius_km)


def _head_to_head(session: Session, a: str, b: str) -> tuple[int, int]:
    rows = session.exec(select(Match).where(Match.p1.in_([a, b]), Match.p2.in_([a, b]),
                                            Match.winner_player_id.is_not(None))).all()
    return (sum(1 for m in rows if m.winner_player_id == a),
            sum(1 for m in rows if m.winner_player_id == b))


@router.get("/predict")
def predict_(a: str, b: str, session: Session = Depends(get_session)):
    pa, pb = session.get(Player, a), session.get(Player, b)
    if not pa or not pb:
        raise HTTPException(404, "player not found")
    return predict.win_probability(pa, pb, _head_to_head(session, a, b))
