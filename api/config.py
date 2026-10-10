"""Settings read from .env (see .env.example). All paths are Windows-safe (pathlib)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def _db_url(value: str | None) -> str:
    """Relative sqlite paths resolve against the repo root, so the CWD doesn't matter."""
    if not value:
        return f"sqlite:///{(ROOT / 'data' / 'rallyos.db').as_posix()}"
    prefix = "sqlite:///"
    if value.startswith(prefix) and value[len(prefix):] != ":memory:":
        return prefix + _path(value[len(prefix):]).as_posix()
    return value


class Settings:
    root = ROOT
    database_url = _db_url(os.getenv("DATABASE_URL"))
    media_dir = _path(os.getenv("MEDIA_DIR", "media"))
    runtime_dir = _path(os.getenv("RUNTIME_DIR", "data/runtime"))   # human-confirmed overrides, report cache
    mock_dir = ROOT / "data" / "mock"
    seed_dir = ROOT / "data" / "seed"
    out_dir = ROOT / "demo" / "out"
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    coach_model = os.getenv("RALLYOS_COACH_MODEL", "claude-sonnet-5-5")
    mock_fallback = os.getenv("MOCK_FALLBACK", "true").lower() == "true"
    cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]


settings = Settings()
for _d in (settings.media_dir, settings.runtime_dir, settings.seed_dir):
    _d.mkdir(parents=True, exist_ok=True)
