"""Accounts without extra packages: PBKDF2 password hashes and HMAC-signed bearer tokens (standard library only).

Two roles: `player` (sees their own analysis) and `coach` (sees the players on their roster). The token carries the user id,
the role and an expiry, signed with RALLYOS_AUTH_SECRET (a random secret is created once under the runtime folder if the
variable is not set, so tokens survive a restart on this machine). This is real authentication for a single-server demo:
no email verification, no password reset, no rate limiting.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time

from api.config import settings

ITERATIONS = 200_000
TOKEN_TTL_S = 7 * 24 * 3600


def _secret() -> bytes:
    env = os.getenv("RALLYOS_AUTH_SECRET")
    if env:
        return env.encode()
    path = settings.runtime_dir / "auth_secret"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip().encode()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(check.hex(), digest)
    except (ValueError, TypeError):
        return False


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def make_token(user_id: int, role: str, ttl: int = TOKEN_TTL_S) -> str:
    body = _b64(json.dumps({"uid": user_id, "role": role, "exp": int(time.time()) + ttl}, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token: str | None) -> dict | None:
    """The token's payload when the signature is genuine and it has not expired, else None."""
    if not token or token.count(".") != 1:
        return None
    body, sig = token.split(".")
    good = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, good):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (ValueError, json.JSONDecodeError):
        return None
    return payload if payload.get("exp", 0) > time.time() else None


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "player"
