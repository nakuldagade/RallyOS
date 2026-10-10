"""Isolate API tests: temp DB, media and runtime dirs, and no network coach. Must run before api.* imports.

By default the tests use a throwaway SQLite file. Set RALLYOS_TEST_DATABASE_URL to a Postgres database whose name
contains "test" (e.g. a local Postgres, or a separate Supabase project) to run the same tests on Postgres: its public
schema is wiped first, so never point it at real data.
"""
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="rallyos_test_"))
_pg = os.environ.get("RALLYOS_TEST_DATABASE_URL", "")
if _pg:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    _url = _pg.replace("postgresql://", "postgresql+psycopg://", 1) if _pg.startswith("postgresql://") else _pg
    if "test" not in (make_url(_url).database or ""):
        raise RuntimeError("RALLYOS_TEST_DATABASE_URL must name a database containing 'test' (it is wiped)")
    with create_engine(_url).begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    os.environ["DATABASE_URL"] = _pg
else:
    os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["MEDIA_DIR"] = str(_tmp / "media")
os.environ["RUNTIME_DIR"] = str(_tmp / "runtime")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["MOCK_FALLBACK"] = "true"
