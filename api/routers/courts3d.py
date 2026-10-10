"""Smart Courts (3D viewer): GET /v1/courts3d/matches and /v1/courts3d/matches/{id}. Logged-in coaches and players only."""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from api.db import get_session
from api.models import User
from api.services import court3d
from api.services.access import current_user

router = APIRouter(tags=["courts3d"])


@router.get("/courts3d/matches")
def matches(user: User = Depends(current_user), session: Session = Depends(get_session)):
    """The matches this user may open in 3D: a coach's are those with a rostered player in them, a player's their own."""
    return court3d.visible_matches(user, session)


@router.get("/courts3d/matches/{match_id}")
def match_scene(match_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    try:
        data = court3d.scene(user, match_id, session)
    except KeyError:
        raise HTTPException(404, "match not found") from None
    if data is None:
        raise HTTPException(403, "you can only open your own matches, or matches with a player on your roster")
    return data
