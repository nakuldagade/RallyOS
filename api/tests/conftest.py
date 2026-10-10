"""Isolate API tests: temp DB, media and runtime dirs, and no network coach. Must run before api.* imports."""
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="rallyos_test_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["MEDIA_DIR"] = str(_tmp / "media")
os.environ["RUNTIME_DIR"] = str(_tmp / "runtime")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["MOCK_FALLBACK"] = "true"
