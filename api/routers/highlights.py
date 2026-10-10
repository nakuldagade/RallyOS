"""GET /v1/highlights: the best-shot clip (about 8 s) of every analysed match that has one."""
from fastapi import APIRouter, Depends
from sqlmodel import Session

from api.db import get_session
from api.services import highlights

router = APIRouter(tags=["highlights"])


@router.get("/highlights")
def list_highlights(session: Session = Depends(get_session)):
    return highlights.listing(session)
