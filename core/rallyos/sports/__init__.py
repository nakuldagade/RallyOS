"""Sport configs. Adding a sport means adding one YAML file here; no code changes."""

from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path

import yaml

SPORTS_DIR = Path(__file__).resolve().parent


def list_sports() -> list[str]:
    return sorted(p.stem for p in SPORTS_DIR.glob("*.yaml"))


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    path = SPORTS_DIR / f"{name}.yaml"
    if not path.is_file():
        raise KeyError(f"unknown sport {name!r}; available: {list_sports()}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_sport(name: str) -> dict:
    """Load core/rallyos/sports/<name>.yaml as a dict (a fresh copy each call)."""
    return copy.deepcopy(_load(name))
