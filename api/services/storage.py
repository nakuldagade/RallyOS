"""Where live chunks (and later the final video) are kept: local disk by default, Cloudinary when configured.

Heavy video analysis always runs on this laptop, so every chunk ends up as a local file before it is analysed; Cloudinary
only adds durable storage and CDN delivery on top (phase E). Local mode works fully offline.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from api.config import settings

log = logging.getLogger(__name__)
ALLOWED_EXT = {".webm", ".mp4", ".avi", ".mkv", ".mov"}


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


class LocalStorage:
    name = "local"

    def chunk_dir(self, session_id: str) -> Path:
        d = settings.live_dir / _safe(session_id) / "chunks"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def chunk_path(self, session_id: str, seq: int, ext: str) -> Path:
        ext = ext.lower() if ext.lower() in ALLOWED_EXT else ".webm"
        return self.chunk_dir(session_id) / f"chunk_{seq:04d}{ext}"

    def save_chunk(self, session_id: str, seq: int, data: bytes, ext: str) -> Path:
        path = self.chunk_path(session_id, seq, ext)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)                                  # a chunk file appears whole or not at all
        return path

    def sign(self, session_id: str, seq: int | None = None) -> dict:
        """Where the browser sends a chunk: this API, as multipart form data."""
        return {"mode": "local", "upload_url": f"/v1/live/sessions/{session_id}/chunks", "method": "POST",
                "fields": {}, "file_field": "chunk"}


def get_storage():
    """The configured storage. Cloudinary arrives in phase E; until then a request for it falls back to local, loudly."""
    if settings.storage == "cloudinary":
        try:
            from api.services.storage_cloudinary import CloudinaryStorage  # noqa: WPS433

            return CloudinaryStorage()
        except ImportError:
            log.warning("RALLYOS_STORAGE=cloudinary but Cloudinary storage is not available yet: using local storage")
    return LocalStorage()
