"""Copy every table from one database to another, e.g. the local SQLite file into Supabase Postgres.

    python -m api.migrate_db --to "postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"
    python -m api.migrate_db --to "$DATABASE_URL" --replace          # empty the target tables first

--from defaults to the local SQLite file (data/rallyos.db). Tables are created on the target if missing, copied in
foreign-key order (parents first), and on Postgres the id sequences are moved past the copied ids so new rows
don't collide. Match files and media stay on disk; only the database rows move.
"""
from __future__ import annotations

import argparse

from sqlalchemy import func, select, text
from sqlmodel import SQLModel, create_engine

from api.config import ROOT, _db_url
from api.db import _engine_kwargs, lock_down


def migrate(src_url: str, dst_url: str, replace: bool = False) -> dict[str, int]:
    from api import models  # noqa: F401  (register tables)

    src_url, dst_url = _db_url(src_url), _db_url(dst_url)
    src = create_engine(src_url, **_engine_kwargs(src_url))
    dst = create_engine(dst_url, **_engine_kwargs(dst_url))
    SQLModel.metadata.create_all(dst)
    lock_down(dst)
    tables = SQLModel.metadata.sorted_tables                 # parents before children
    counts: dict[str, int] = {}
    with src.connect() as s, dst.begin() as d:
        if replace:
            for t in reversed(tables):
                d.execute(t.delete())
        for t in tables:
            rows = [dict(r) for r in s.execute(select(t)).mappings()]
            if rows:
                d.execute(t.insert(), rows)
            counts[t.name] = len(rows)
        if dst.dialect.name == "postgresql":
            for t in tables:
                col = t.c.get("id")
                if col is None or not col.autoincrement or col.type.python_type is not int:
                    continue
                top = d.execute(select(func.max(col))).scalar()
                if top is not None:
                    d.execute(text("SELECT setval(pg_get_serial_sequence(:t, 'id'), :v)"), {"t": f'"{t.name}"', "v": top})
    return counts


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="api.migrate_db")
    ap.add_argument("--from", dest="src", default=f"sqlite:///{(ROOT / 'data' / 'rallyos.db').as_posix()}")
    ap.add_argument("--to", dest="dst", required=True, help="target URL, e.g. the Supabase session-pooler URL")
    ap.add_argument("--replace", action="store_true", help="delete the target tables' rows first")
    args = ap.parse_args(argv)
    counts = migrate(args.src, args.dst, args.replace)
    for name, n in counts.items():
        print(f"{name:16} {n:6d} rows")
    print("done")


if __name__ == "__main__":
    main()
