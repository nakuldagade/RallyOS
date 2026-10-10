"""GET /v1/matches/{id}/report: evidence-linked coach report."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from api.db import get_session
from api.schemas import CoachReport
from api.services import coach, store

router = APIRouter(tags=["coach"])


@router.get("/matches/{match_id}/report", response_model=CoachReport)
def report(match_id: str, source: Literal["auto", "claude", "template"] = "auto",
           session: Session = Depends(get_session)):
    try:
        data = store.load_match(match_id, session)
    except KeyError:
        raise HTTPException(404, "match not found") from None
    return coach.build_report(data, prefer=source)
