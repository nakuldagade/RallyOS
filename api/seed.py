"""CLI:  python -m api.seed   -> writes data/seed/*.json if missing, loads them, imports the mock match."""
import json
import secrets
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


COACHES = [{"email": "coach.vikram@rallyos.demo", "name": "Coach Vikram", "roster": ["p_anika", "p_rohan", "p_kabir"]},
           {"email": "coach.neha@rallyos.demo", "name": "Coach Neha", "roster": ["p_meera", "p_isha"]}]


def _new_password() -> str:
    return secrets.token_urlsafe(9)                        # 12 random characters: there is no fixed demo password


def _save_passwords(passwords: dict[str, str]) -> None:
    """The passwords are shown once and kept only in the git-ignored runtime folder, so a person can read them from there."""
    path = settings.runtime_dir / "demo_accounts.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    known: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "\t" in line:
                e, pw = line.split("\t", 1)
                known[e] = pw
    known.update(passwords)
    path.write_text("".join(f"{e}\t{pw}\n" for e, pw in sorted(known.items())), encoding="utf-8")


def seed_accounts(s: Session, reset: bool = False) -> dict[str, str]:
    """A login for every seed player (first-name@rallyos.demo) and two coaches with different rosters, each with its own random
    password. Returns {email: password} for the accounts created (or, with reset=True, for every demo account: new passwords)."""
    out: dict[str, str] = {}

    def credential(user: User) -> None:
        pw = _new_password()
        row = s.get(Credential, user.id)
        if row is None:
            s.add(Credential(user_id=user.id, password_hash=auth.hash_password(pw)))
        else:
            row.password_hash = auth.hash_password(pw)
            s.add(row)
        out[user.email] = pw

    for p in s.exec(select(Player)).all():
        email = f"{p.name.lower()}@rallyos.demo"
        u = s.exec(select(User).where(User.email == email)).first()
        if u is None:
            u = User(email=email, name=p.name, role="player")
            s.add(u)
            s.flush()
            p.user_id = u.id
            s.add(p)
        elif not reset:
            continue
        credential(u)
    for c in COACHES:
        u = s.exec(select(User).where(User.email == c["email"])).first()
        if u is None:
            u = User(email=c["email"], name=c["name"], role="coach")
            s.add(u)
            s.flush()
            for pid in c["roster"]:
                s.add(CoachPlayer(coach_user_id=u.id, player_id=pid))
        elif not reset:
            continue
        credential(u)
    s.commit()
    if out:
        _save_passwords(out)
    return out


def _file(name: str, default: list) -> list:
    p = settings.seed_dir / name
    if not p.exists():
        p.write_text(json.dumps(default, indent=2), encoding="utf-8")
    return json.loads(p.read_text(encoding="utf-8"))


def main(reset_passwords: bool = False) -> None:
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
        made = seed_accounts(s, reset=reset_passwords)
        if made:
            print("demo accounts (random passwords, also saved in data/runtime/demo_accounts.txt):")
            for e, pw in made.items():
                print(f"  {e}  {pw}")
        if settings.mock_dir.joinpath("match.json").exists():
            print("imported mock match", import_folder(settings.mock_dir, s))
    print("seed done")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Seed the database; creates demo accounts with random passwords.")
    ap.add_argument("--reset-passwords", action="store_true", help="give every demo account a new random password")
    main(reset_passwords=ap.parse_args().reset_passwords)
