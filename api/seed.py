"""CLI:  python -m api.seed   -> writes data/seed/*.json if missing, loads them, imports the mock match."""
import json
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from api.config import settings
from api.db import create_all, engine
from api.models import CoachPlayer, Court, Credential, Player, RatingHistory, Tournament, User, Venue
from api.services import auth
from api.services.importer import import_folder

# style_vec = [attack, defence, net_play, endurance]
PLAYERS = [
    {"id": "p_anika", "name": "Anika", "rating": 1620, "rd": 80, "style_vec": [0.8, 0.5, 0.6, 0.7], "lat": 19.20, "lng": 72.97},
    {"id": "p_rohan", "name": "Rohan", "rating": 1585, "rd": 95, "style_vec": [0.6, 0.7, 0.5, 0.6], "lat": 19.07, "lng": 72.88},
    {"id": "p_meera", "name": "Meera", "rating": 1490, "rd": 120, "style_vec": [0.4, 0.8, 0.7, 0.5], "lat": 19.12, "lng": 72.85},
    {"id": "p_kabir", "name": "Kabir", "rating": 1710, "rd": 70, "style_vec": [0.9, 0.4, 0.5, 0.8], "lat": 19.03, "lng": 72.86},
    {"id": "p_isha", "name": "Isha", "rating": 1555, "rd": 110, "style_vec": [0.5, 0.6, 0.8, 0.6], "lat": 19.22, "lng": 73.0},
]
VENUES = [
    {"name": "Thane Smash Academy", "city": "Thane", "lat": 19.19, "lng": 72.97},
    {"name": "Dadar Shuttle Club", "city": "Mumbai", "lat": 19.02, "lng": 72.84},
]
TOURNAMENTS = [{"name": "Mumbai District Open", "sport": "badminton", "start_date": "2026-11-15"},
               {"name": "Thane Inter-Academy Cup", "sport": "badminton", "start_date": "2026-12-06"}]


DEMO_PASSWORD = "rallyos-demo"          # demo accounts only: change it, or register your own, before showing real data
COACHES = [{"email": "coach.vikram@rallyos.demo", "name": "Coach Vikram", "roster": ["p_anika", "p_rohan", "p_kabir"]},
           {"email": "coach.neha@rallyos.demo", "name": "Coach Neha", "roster": ["p_meera", "p_isha"]}]


def seed_accounts(s: Session) -> list[str]:
    """A login for every seed player (first-name@rallyos.demo) and two coaches with different rosters. Idempotent."""
    made = []
    for p in s.exec(select(Player)).all():
        email = f"{p.name.lower()}@rallyos.demo"
        if s.exec(select(User).where(User.email == email)).first():
            continue
        u = User(email=email, name=p.name, role="player")
        s.add(u)
        s.flush()
        s.add(Credential(user_id=u.id, password_hash=auth.hash_password(DEMO_PASSWORD)))
        p.user_id = u.id
        s.add(p)
        made.append(email)
    for c in COACHES:
        if s.exec(select(User).where(User.email == c["email"])).first():
            continue
        u = User(email=c["email"], name=c["name"], role="coach")
        s.add(u)
        s.flush()
        s.add(Credential(user_id=u.id, password_hash=auth.hash_password(DEMO_PASSWORD)))
        for pid in c["roster"]:
            s.add(CoachPlayer(coach_user_id=u.id, player_id=pid))
        made.append(c["email"])
    s.commit()
    return made


def _file(name: str, default: list) -> list:
    p = settings.seed_dir / name
    if not p.exists():
        p.write_text(json.dumps(default, indent=2), encoding="utf-8")
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> None:
    create_all()
    players, venues, tours = _file("players.json", PLAYERS), _file("venues.json", VENUES), _file("tournaments.json", TOURNAMENTS)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(engine) as s:
        if not s.exec(select(Venue)).first():
            for v in venues:
                venue = Venue(**v)
                s.add(venue)
                s.flush()
                s.add(Court(venue_id=venue.id, sport="badminton", smart_court=venue.city == "Thane"))
        for p in players:
            if not s.get(Player, p["id"]):
                s.add(Player(**p))
                for i in range(5):                       # small rating history for charts
                    s.add(RatingHistory(player_id=p["id"], rating=p["rating"] - (4 - i) * 12, rd=p["rd"],
                                        at=(now - timedelta(days=(4 - i) * 14)).isoformat(timespec="seconds")))
        if not s.exec(select(Tournament)).first():
            for t in tours:
                s.add(Tournament(**t))
        s.commit()
        made = seed_accounts(s)
        if made:
            print(f"demo accounts (password {DEMO_PASSWORD!r}):", ", ".join(made))
        if settings.mock_dir.joinpath("match.json").exists():
            print("imported mock match", import_folder(settings.mock_dir, s))
    print("seed done")


if __name__ == "__main__":
    main()
