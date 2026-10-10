"""SQLModel engine, session dependency, create_all().

SQLite (local file, the default and the offline fallback) or Postgres (Supabase, via DATABASE_URL).
"""
from typing import Iterator

from sqlalchemy.engine import make_url
from sqlmodel import Session, SQLModel, create_engine

from api.config import settings


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    kw = {"pool_pre_ping": True,           # Supabase / poolers drop idle connections: test before use
          "pool_size": 5, "max_overflow": 5, "pool_recycle": 1800,
          "connect_args": {"connect_timeout": 10}}
    if make_url(url).port == 6543:         # Supabase transaction pooler: no server-side prepared statements
        kw["connect_args"]["prepare_threshold"] = None
    return kw


engine = create_engine(settings.database_url, **_engine_kwargs(settings.database_url))


def backend() -> str:
    """'sqlite' or 'postgres' (+ host, never the password), for /health."""
    url = make_url(settings.database_url)
    return "sqlite" if url.get_backend_name() == "sqlite" else f"postgres @ {url.host}"


def create_all() -> None:
    from api import models  # noqa: F401  (register tables)
    SQLModel.metadata.create_all(engine)
    lock_down(engine)


def lock_down(eng) -> None:
    """Postgres / Supabase: turn on Row Level Security for every RallyOS table (idempotent).

    Supabase publishes the public schema through its REST API, and a table created over a database connection
    starts with RLS off, so anyone holding the project's anon key could read and write it. With RLS on and no
    policies, that REST route sees nothing, while this backend - which connects as the table owner - is unaffected.
    """
    if eng.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    with eng.begin() as conn:
        for t in SQLModel.metadata.sorted_tables:
            conn.execute(text(f'ALTER TABLE "{t.name}" ENABLE ROW LEVEL SECURITY'))


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
