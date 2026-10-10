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
    """Database URL. Empty -> local SQLite (the offline fallback). Relative sqlite paths resolve against the repo
    root. Postgres / Supabase URLs as copied from the dashboard ("postgresql://..." or "postgres://...") get the
    psycopg 3 driver, and Supabase hosts get sslmode=require if the URL doesn't say otherwise."""
    if not value:
        return f"sqlite:///{(ROOT / 'data' / 'rallyos.db').as_posix()}"
    prefix = "sqlite:///"
    if value.startswith(prefix) and value[len(prefix):] != ":memory:":
        return prefix + _path(value[len(prefix):]).as_posix()
    for scheme in ("postgresql://", "postgres://"):
        if value.startswith(scheme):
            value = "postgresql+psycopg://" + value[len(scheme):]
    if value.startswith("postgresql+psycopg://") and "supabase." in value and "sslmode=" not in value:
        value += ("&" if "?" in value else "?") + "sslmode=require"
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
    # live mode (continuous capture, analysed in chunks)
    chunk_seconds = float(os.getenv("RALLYOS_CHUNK_SECONDS", "5"))
    storage = os.getenv("RALLYOS_STORAGE", "local").strip().lower()          # local | cloudinary
    live_dir = ROOT / "demo" / "out" / "live"
    live_missing_wait_s = float(os.getenv("RALLYOS_LIVE_MISSING_WAIT_S", "15"))   # how long to wait for a chunk that skipped ahead
    chunk_url_hosts = [h.strip() for h in os.getenv("RALLYOS_CHUNK_URL_HOSTS", "res.cloudinary.com").split(",") if h.strip()]
    cloudinary_cloud = os.getenv("CLOUDINARY_CLOUD_NAME", "")
    cloudinary_key = os.getenv("CLOUDINARY_API_KEY", "")
    cloudinary_secret = os.getenv("CLOUDINARY_API_SECRET", "")
    cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]


settings = Settings()
for _d in (settings.media_dir, settings.runtime_dir, settings.seed_dir):
    _d.mkdir(parents=True, exist_ok=True)
