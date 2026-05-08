"""Contain approval token backend logic."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

from config.settings import settings

logger = logging.getLogger(__name__)

_TTL_SECONDS = 3600 


def _secret(client_id: str) -> bytes:
    """Execute secret."""
    base = getattr(settings, "approval_hmac_secret", None) or client_id
    return f"{base}:{client_id}".encode()


def generate_approval_token(
    client_id: str,
    task_id: str,
    action: str,
    expires_in: int = _TTL_SECONDS,
) -> str:
    """Execute generate approval token."""
    payload = json.dumps(
        {
            "client_id": client_id,
            "task_id": task_id,
            "action": action,
            "exp": int(time.time()) + expires_in,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    payload_hex = payload.encode().hex()
    sig = hmac.new(_secret(client_id), payload_hex.encode(), hashlib.sha256).hexdigest()
    return f"{payload_hex}.{sig}"


def verify_approval_token(token: str) -> dict:
    """Execute verify approval token."""
    try:
        payload_hex, received_sig = token.split(".", 1)
    except ValueError:
        raise ValueError("Malformed token")

    try:
        payload_str = bytes.fromhex(payload_hex).decode()
        payload = json.loads(payload_str)
    except Exception:
        raise ValueError("Malformed token")

    client_id = payload.get("client_id", "")
    expected_sig = hmac.new(
        _secret(client_id), payload_hex.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(received_sig, expected_sig):
        logger.error(
            "Approval token signature mismatch client=%s task=%s",
            client_id,
            payload.get("task_id"),
        )
        raise ValueError("Invalid token")

    if time.time() > payload.get("exp", 0):
        raise ValueError("Token expired")

    return payload