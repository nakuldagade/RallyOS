"""Cloudinary as durable storage and CDN for live chunks and the final video. No Cloudinary SDK: signing is a SHA-1 and the
upload is one multipart POST, so the secret stays on the server and nothing extra is installed.

Heavy video analysis still runs on this laptop. The flow is:
  1. browser  -> POST /v1/live/sessions/{id}/sign?seq=N   (this API signs the upload parameters; the secret never leaves here)
  2. browser  -> POST https://api.cloudinary.com/v1_1/<cloud>/video/upload   (the chunk goes straight to Cloudinary)
  3. browser  -> POST /v1/live/sessions/{id}/chunks/register {url}   (this API downloads the chunk to analyse it)
  4. on Stop, the stitched match video is uploaded here (server side) and its URL is written to match.json (`video.cdn_src`).
"""
from __future__ import annotations

import hashlib
import logging
import time
import uuid
from pathlib import Path

import httpx

from api.config import settings
from api.services.storage import LocalStorage

log = logging.getLogger(__name__)

NOT_SIGNED = {"file", "cloud_name", "resource_type", "api_key"}        # Cloudinary's rule: these are never part of the signature
LARGE_FILE = 20 * 1024 * 1024
PART = 6 * 1024 * 1024


def sign_params(params: dict, secret: str) -> str:
    """Cloudinary's signature: the parameters sorted by name as `k=v&k=v`, the API secret appended, SHA-1 in hex."""
    body = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k not in NOT_SIGNED and v not in (None, ""))
    return hashlib.sha1((body + secret).encode("utf-8")).hexdigest()


class CloudinaryStorage(LocalStorage):
    name = "cloudinary"

    def __init__(self, cloud: str | None = None, key: str | None = None, secret: str | None = None, api_base: str | None = None):
        self.cloud = cloud or settings.cloudinary_cloud
        self.key = key or settings.cloudinary_key
        self.secret = secret or settings.cloudinary_secret
        self.api_base = (api_base or settings.cloudinary_api_base).rstrip("/")
        if not (self.cloud and self.key and self.secret):
            raise ValueError("Cloudinary needs CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET")

    def upload_url(self) -> str:
        return f"{self.api_base}/v1_1/{self.cloud}/video/upload"

    def _signed(self, public_id: str) -> dict:
        params = {"public_id": public_id, "timestamp": int(time.time()), "overwrite": "true"}
        return {**params, "api_key": self.key, "signature": sign_params(params, self.secret)}

    def sign(self, session_id: str, seq: int | None = None) -> dict:
        """What the browser needs to upload one chunk straight to Cloudinary. Only a signature leaves this machine."""
        if seq is None or seq < 0:
            raise ValueError("seq is required to sign a chunk upload")
        public_id = f"rallyos/{session_id}/chunk_{seq:04d}"
        return {"mode": "cloudinary", "upload_url": self.upload_url(), "method": "POST", "file_field": "file",
                "fields": {k: str(v) for k, v in self._signed(public_id).items()}, "public_id": public_id}

    def upload_file(self, path: str | Path, public_id: str, timeout: float = 300.0) -> str:
        """Upload a local video from the server (the stitched match). Files over 20 MB go in 6 MB parts. Returns its https URL."""
        path = Path(path)
        size = path.stat().st_size
        fields = self._signed(public_id)
        if size <= LARGE_FILE:
            r = httpx.post(self.upload_url(), data={k: str(v) for k, v in fields.items()},
                           files={"file": (path.name, path.read_bytes(), "video/mp4")}, timeout=timeout)
            return self._url(r)
        upload_id = uuid.uuid4().hex
        url = ""
        with open(path, "rb") as fh:
            start = 0
            while start < size:
                chunk = fh.read(PART)
                end = start + len(chunk) - 1
                r = httpx.post(self.upload_url(), data={k: str(v) for k, v in fields.items()},
                               files={"file": (path.name, chunk, "video/mp4")}, timeout=timeout,
                               headers={"X-Unique-Upload-Id": upload_id, "Content-Range": f"bytes {start}-{end}/{size}"})
                url = self._url(r) if end + 1 >= size else url
                if end + 1 < size and r.status_code >= 400:
                    self._url(r)                                         # raises with Cloudinary's message
                start = end + 1
        return url

    @staticmethod
    def _url(r: httpx.Response) -> str:
        if r.status_code != 200:
            try:
                msg = r.json().get("error", {}).get("message", r.text)
            except ValueError:
                msg = r.text
            raise RuntimeError(f"Cloudinary upload failed ({r.status_code}): {msg}")
        return r.json()["secure_url"]
