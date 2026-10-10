"""GET /v1/tournaments, POST /register, POST /draw."""
import random

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from api.db import get_session
from api.models import DrawMatch, Player, Registration, Tournament

router = APIRouter(tags=["tournaments"])


class RegisterIn(BaseModel):
    player_id: str


@router.get("/tournaments")
def list_tournaments(session: Session = Depends(get_session)):
    return session.exec(select(Tournament)).all()


@router.post("/tournaments/{tid}/register", status_code=201)
def register(tid: int, body: RegisterIn, session: Session = Depends(get_session)):
    if not session.get(Tournament, tid):
        raise HTTPException(404, "tournament not found")
    if not session.get(Player, body.player_id):
        raise HTTPException(404, "player not found")
    if session.exec(select(Registration).where(Registration.tournament_id == tid,
                                                Registration.player_id == body.player_id)).first():
        raise HTTPException(409, "already registered")
    r = Registration(tournament_id=tid, player_id=body.player_id)
    session.add(r)
    session.commit()
    session.refresh(r)
    return r


@router.post("/tournaments/{tid}/draw")
def draw(tid: int, session: Session = Depends(get_session)):
    """Seeded single-elimination round 1: top half by rating meets the (shuffled) bottom half; byes if odd."""
    regs = session.exec(select(Registration).where(Registration.tournament_id == tid)).all()
    players = sorted((p for p in (session.get(Player, r.player_id) for r in regs) if p), key=lambda p: -p.rating)
    if len(players) < 2:
        raise HTTPException(400, "need at least 2 registrations")
    for old in session.exec(select(DrawMatch).where(DrawMatch.tournament_id == tid)).all():
        session.delete(old)
    ids = [p.id for p in players]
    half = len(ids) // 2
    top, bottom = ids[:half], ids[half:][::-1]
    random.Random(tid).shuffle(bottom)
    out = []
    for i in range(max(len(top), len(bottom))):
        dm = DrawMatch(tournament_id=tid, round=1, slot=i,
                       p1=top[i] if i < len(top) else None, p2=bottom[i] if i < len(bottom) else None)
        session.add(dm)
        out.append(dm)
    session.commit()
    for dm in out:
        session.refresh(dm)
    return out
