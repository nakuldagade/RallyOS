"""Coach side: GET /v1/coach/dashboard, GET/POST/DELETE /v1/coach/roster."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from api.db import get_session
from api.models import CoachPlayer, Player, RatingHistory, User
from api.services import player_analysis
from api.services.access import coach_user, roster_ids

router = APIRouter(tags=["coach"])


class RosterAdd(BaseModel):
    player_id: str


@router.get("/coach/roster")
def roster(coach: User = Depends(coach_user), session: Session = Depends(get_session)):
    ids = roster_ids(coach, session)
    return [p for p in (session.get(Player, i) for i in ids) if p]


@router.post("/coach/roster", status_code=201)
def add_to_roster(body: RosterAdd, coach: User = Depends(coach_user), session: Session = Depends(get_session)):
    if not session.get(Player, body.player_id):
        raise HTTPException(404, "player not found")
    if body.player_id not in roster_ids(coach, session):
        session.add(CoachPlayer(coach_user_id=coach.id, player_id=body.player_id))
        session.commit()
    return {"player_id": body.player_id}


@router.delete("/coach/roster/{player_id}")
def remove_from_roster(player_id: str, coach: User = Depends(coach_user), session: Session = Depends(get_session)):
    for r in session.exec(select(CoachPlayer).where(CoachPlayer.coach_user_id == coach.id, CoachPlayer.player_id == player_id)).all():
        session.delete(r)
    session.commit()
    return {"removed": player_id}


@router.get("/coach/dashboard")
def dashboard(coach: User = Depends(coach_user), session: Session = Depends(get_session)):
    """One row per rostered player: rating, how many matches were analysed, what changed in the latest one, and what to look at."""
    rows = []
    for pid in roster_ids(coach, session):
        p = session.get(Player, pid)
        if not p:
            continue
        a = player_analysis.analysis(session, pid)
        hist = session.exec(select(RatingHistory).where(RatingHistory.player_id == pid).order_by(RatingHistory.at, RatingHistory.id)).all()
        worse = [c for c in a["compare"] if c["verdict"] == "worse"]
        better = [c for c in a["compare"] if c["verdict"] == "better"]
        latest = a["matches"][-1] if a["matches"] else None
        rows.append({"player_id": pid, "name": p.name, "rating": p.rating, "rd": p.rd,
                     "rating_change": round(p.rating - hist[0].rating) if hist else None,
                     "rating_is_sample": not any(h.match_id for h in hist),
                     "matches": a["summary"]["matches"], "analysed_minutes": a["summary"]["analysed_minutes"],
                     "latest": ({"match_id": latest["match_id"], "opponent": latest["opponent"], "result": latest["result"],
                                 "date": latest["date"], "metrics": latest["metrics"]} if latest else None),
                     "attention": [{"metric": c["metric"], "text": i["text"]} for c in worse for i in a["insights"] if i["metric"] == c["metric"]],
                     "improving": [{"metric": c["metric"], "text": i["text"]} for c in better for i in a["insights"] if i["metric"] == c["metric"]]})
    return {"coach": {"id": coach.id, "name": coach.name}, "players": rows,
            "totals": {"players": len(rows), "matches": sum(r["matches"] for r in rows),
                       "need_attention": sum(1 for r in rows if r["attention"])}}
