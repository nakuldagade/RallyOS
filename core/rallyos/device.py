"""Device selection. Every model call goes through get_device(); never hard-code "cuda"."""

from __future__ import annotations

import os
import warnings

_VALID = ("auto", "cpu", "cuda")


def _cuda_available() -> bool:
    try:
        import torch
    except ImportError:
        return False
    return bool(torch.cuda.is_available())


def get_device(preferred: str | None = None) -> str:
    """Return "cuda" or "cpu".

    Priority: the `preferred` argument (e.g. a --device CLI flag), then the
    RALLYOS_DEVICE env var, then "auto". "auto" picks CUDA when torch can see a
    GPU. Asking for "cuda" on a machine without one warns and falls back to CPU,
    so the same code runs on CPU by default and on a GPU if one is available.
    """
    choice = (preferred or os.environ.get("RALLYOS_DEVICE") or "auto").strip().lower()
    if choice not in _VALID:
        raise ValueError(f"device must be one of {_VALID}, got {choice!r}")
    if choice == "cpu":
        return "cpu"
    if _cuda_available():
        return "cuda"
    if choice == "cuda":
        warnings.warn("CUDA requested but not available; falling back to CPU.", RuntimeWarning, stacklevel=2)
    return "cpu"
