"""GET /v1/courts, POST /v1/bookings (payment mocked)."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from api.db import get_session
from api.models import Booking, Court, Venue
from api.services.matchmaking import km

router = APIRouter(tags=["courts"])


class BookingIn(BaseModel):
    court_id: int
    player_id: str
    slot_start: datetime
    slot_end: datetime


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=None).isoformat(timespec="seconds")


@router.get("/courts")
def list_courts(near: str | None = None, sport: str | None = None, session: Session = Depends(get_session)):
    """near='lat,lng' sorts venues by distance."""
    q = select(Court, Venue).join(Venue, Venue.id == Court.venue_id)
    if sport:
        q = q.where(Court.sport == sport)
    rows = [{"court": c, "venue": v} for c, v in session.exec(q).all()]
    if near:
        try:
            lat, lng = (float(x) for x in near.split(","))
        except ValueError:
            raise HTTPException(400, "near must be 'lat,lng'") from None
        for r in rows:
            r["distance_km"] = round(km(lat, lng, r["venue"].lat, r["venue"].lng), 1)
        rows.sort(key=lambda r: r["distance_km"])
    return rows


@router.post("/bookings", status_code=201)
def book(body: BookingIn, session: Session = Depends(get_session)):
    if not session.get(Court, body.court_id):
        raise HTTPException(404, "court not found")
    start, end = _iso(body.slot_start), _iso(body.slot_end)
    if end <= start:
        raise HTTPException(400, "slot_end must be after slot_start")
    clash = session.exec(select(Booking).where(Booking.court_id == body.court_id,
                                               Booking.slot_start < end, Booking.slot_end > start)).first()
    if clash:
        raise HTTPException(409, "slot already booked")
    b = Booking(court_id=body.court_id, player_id=body.player_id, slot_start=start, slot_end=end)
    session.add(b)
    session.commit()
    session.refresh(b)
    return b
