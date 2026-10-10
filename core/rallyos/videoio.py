"""Video file helpers: metadata and the SHA-256 fingerprint for verified match records (§4.7)."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def video_info(path: str | Path) -> dict:
    """{"fps", "frames", "width", "height", "duration_s"} read with OpenCV."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise IOError(f"cannot open video {path}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        return {"fps": fps, "frames": frames, "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), "duration_s": round(frames / fps, 3)}
    finally:
        cap.release()
