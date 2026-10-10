"""GET /v1/disputes/{id}, /clip: Fair-Play Replay evidence."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from api.db import get_session
from api.models import Dispute
from api.services import store

router = APIRouter(tags=["disputes"])


def _find(ref: str, session: Session) -> dict:
    row = session.exec(select(Dispute).where(Dispute.ref == ref)).first()
    try:
        data = store.load_match(row.match_id, session) if row else store.mock_match()
    except (KeyError, FileNotFoundError):
        raise HTTPException(404, "dispute not found") from None
    for d in data.get("disputes", []):
        if d["id"] == ref:
            ev = next((e for e in data["events"] if e["id"] == d["event_id"]), None)
            return {**d, "match_id": data["match_id"], "event": ev, "sha256": data["video"].get("sha256")}
    raise HTTPException(404, "dispute not found")


@router.get("/disputes/{dispute_id}")
def get_dispute(dispute_id: str, session: Session = Depends(get_session)):
    return _find(dispute_id, session)


@router.get("/disputes/{dispute_id}/clip")
def get_clip(dispute_id: str, session: Session = Depends(get_session)):
    d = _find(dispute_id, session)
    if not d.get("clip_url"):
        raise HTTPException(404, "no clip")
    return RedirectResponse(d["clip_url"])        # served by the /media static mount
