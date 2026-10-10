"""CLI:  python -m api.make_highlights [--force] [--match m_xxx]   -> cut the best-shot highlight for matches analysed before the feature.

New analyses (upload or live) cut their own highlight; this is only for the ones already stored. Safe to run again: matches that
have a highlight are skipped unless --force.
"""
import argparse

from sqlmodel import Session

from api.db import create_all, engine
from api.services import highlights


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="cut again even when a highlight exists")
    ap.add_argument("--match", default=None)
    a = ap.parse_args()
    create_all()
    with Session(engine) as s:
        res = highlights.backfill(s, force=a.force, only=a.match)
    for mid, what in res:
        print(f"{mid}: {what}")
    print(f"{sum(1 for _, w in res if w == 'made')} highlight(s) made")


if __name__ == "__main__":
    main()
