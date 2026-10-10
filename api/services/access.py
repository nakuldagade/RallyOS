"""Who is asking, and what may they see: FastAPI dependencies shared by the routers."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session, select

from api.db import get_session
from api.models import CoachPlayer, Player, User
from api.services import auth


def optional_user(authorization: str | None = Header(None), session: Session = Depends(get_session)) -> User | None:
    token = authorization.split(" ", 1)[1] if authorization and authorization.lower().startswith("bearer ") else None
    payload = auth.read_token(token)
    return session.get(User, payload["uid"]) if payload else None


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(401, "log in first")
    return user


def coach_user(user: User = Depends(current_user)) -> User:
    if user.role != "coach":
        raise HTTPException(403, "this needs a coach account")
    return user


def player_of(user: User, session: Session) -> Player | None:
    return session.exec(select(Player).where(Player.user_id == user.id)).first()


def roster_ids(coach: User, session: Session) -> list[str]:
    return [r.player_id for r in session.exec(select(CoachPlayer).where(CoachPlayer.coach_user_id == coach.id)).all()]


def can_view_player(user: User, player_id: str, session: Session) -> bool:
    """A player sees their own analysis; a coach sees the players on their roster."""
    if user.role == "player":
        p = player_of(user, session)
        return p is not None and p.id == player_id
    if user.role == "coach":
        return player_id in roster_ids(user, session)
    return False
