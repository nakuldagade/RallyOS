"""SQLModel engine, session dependency, create_all().

SQLite (local file, the default and the offline fallback) or Postgres (Supabase, via DATABASE_URL).
"""
import logging
import os
from typing import Iterator

from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine

from api.config import _db_url, settings

log = logging.getLogger(__name__)


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    kw = {"pool_pre_ping": True,           # Supabase / poolers drop idle connections: test before use
          "pool_size": 5, "max_overflow": 5, "pool_recycle": 1800,
          "connect_args": {"connect_timeout": 10}}
    if make_url(url).port == 6543:         # Supabase transaction pooler: no server-side prepared statements
        kw["connect_args"]["prepare_threshold"] = None
    return kw


FALLBACK_NOTE: str | None = None        # set when the configured database could not be reached and SQLite is used instead


def _reachable(url: str, timeout: int = 5) -> bool:
    """Can a connection to this (Postgres) database be opened within `timeout` seconds?"""
    try:
        probe = create_engine(url, connect_args={"connect_timeout": timeout}, poolclass=NullPool)
        with probe.connect():
            return True
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        return False


def _choose_url() -> str:
    """The configured database; if it is a remote one that cannot be reached (offline, a network that blocks port 5432, a
    paused Supabase project), the local SQLite file instead, loudly, so the app and the demo still start. Set
    RALLYOS_DB_FALLBACK=0 to fail instead (e.g. in production, where silently using another database would be wrong)."""
    global FALLBACK_NOTE
    url = settings.database_url
    if url.startswith("sqlite") or os.getenv("RALLYOS_DB_FALLBACK", "1") == "0" or _reachable(url):
        return url
    host = make_url(url).host
    FALLBACK_NOTE = f"{host} is not reachable: using the local SQLite file (data/rallyos.db). Matches stored in Supabase are not shown."
    log.warning("DATABASE FALLBACK: %s", FALLBACK_NOTE)
    settings.database_url = _db_url("")
    return settings.database_url


engine = create_engine(_choose_url(), **_engine_kwargs(settings.database_url))


def backend() -> str:
    """'sqlite' or 'postgres' (+ host, never the password), for /health."""
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite":
        return "sqlite (fallback: Supabase unreachable)" if FALLBACK_NOTE else "sqlite"
    return f"postgres @ {url.host}"


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
