"""CLI:  python -m api.link_demo   -> assign the already-analysed clips to the seed players, so their history has real data.

The numbers in every player's history are the measurements of real analysed clips (nothing is generated). What is a choice is
WHO the two people in a clip are: the clips show other people, so this script only labels side 1 and side 2 with seed players,
a different pairing for each clip, so each player ends up with a different set of matches. It touches only matches that have no
players assigned yet, and `--clear` removes the assignments again.
"""
import argparse

from sqlmodel import Session, select

from api.db import create_all, engine
from api.models import Match, Player
from api.services import store

PAIRS = [("p_anika", "p_rohan"), ("p_kabir", "p_anika"), ("p_rohan", "p_meera"), ("p_isha", "p_kabir"), ("p_meera", "p_isha"),
         ("p_anika", "p_meera"), ("p_kabir", "p_rohan"), ("p_isha", "p_anika")]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clear", action="store_true")
    a = ap.parse_args()
    create_all()
    with Session(engine) as s:
        rows = [m for m in s.exec(select(Match).order_by(Match.created_at, Match.id)).all() if m.id != "m_001"]
        if a.clear:
            for m in rows:
                m.p1 = m.p2 = None
                s.add(m)
            s.commit()
            print("cleared", len(rows), "matches")
            return
        have = {p.id for p in s.exec(select(Player)).all()}
        k = 0
        for m in rows:
            if m.p1 or m.p2:
                continue
            try:
                data = store.load_match(m.id, s)
            except KeyError:
                continue
            per = (data.get("stats") or {}).get("per_player") or {}
            if not per or data.get("sport") != "badminton":                      # only matches that have per-player stats
                continue
            p1, p2 = PAIRS[k % len(PAIRS)]
            k += 1
            if p1 in have and p2 in have:
                m.p1, m.p2 = p1, p2
                s.add(m)
                print(f"{m.id}: {p1} (side 1) vs {p2} (side 2)")
        s.commit()
        print("linked", k, "matches")


if __name__ == "__main__":
    main()
