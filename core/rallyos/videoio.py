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


def sample_frames(path: str | Path, n: int = 9, start_s: float = 0.0, span_s: float = 3.0, max_width: int = 1920) -> list:
    """n evenly spaced BGR frames from [start_s, start_s + span_s] (clipped to the clip), for calibration."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise IOError(f"cannot open video {path}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        a = min(int(start_s * fps), total - 1)
        b = min(total - 1, a + max(1, int(span_s * fps)))
        out = []
        for i in sorted({int(x) for x in np_linspace(a, b, n)}):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ok, frame = cap.read()
            if ok:
                if frame.shape[1] > max_width:
                    s = max_width / frame.shape[1]
                    frame = cv2.resize(frame, (max_width, round(frame.shape[0] * s)), interpolation=cv2.INTER_AREA)
                out.append(frame)
        return out
    finally:
        cap.release()


def np_linspace(a: float, b: float, n: int) -> list[float]:
    return [a + (b - a) * k / max(1, n - 1) for k in range(n)]
