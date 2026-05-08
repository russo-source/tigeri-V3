"""Contain subscriptions backend logic."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Request

from config.db_pool import get_conn
from config.settings import settings
from security.audit import log_action

logger = logging.getLogger(__name__)
router = APIRouter()

_VALID_EVENTS = {
    "subscription.activated",
    "subscription.cancelled",
    "subscription.expired",
    "subscription.renewed",
}

def _verify_signature(payload_bytes: bytes, request: Request) -> bool:
    """Execute verify signature."""
    secret = getattr(settings, "subscription_webhook_secret", "")
    if not secret:
        return True
    sig = request.headers.get("X-Webhook-Signature", "")
    if not sig:
        return False
    try:
        expected = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


@router.post("/webhooks/subscription")
async def subscription_webhook(request: Request) -> dict:
    """Execute subscription webhook."""
    payload_bytes = await request.body()

    if not _verify_signature(payload_bytes, request):
        logger.warning("Subscription webhook invalid signature ip=%s",
                       request.client.host if request.client else "unknown")
        raise HTTPException(status_code=401, detail="Unauthorised")

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event     = payload.get("event", "").strip()
    client_id = payload.get("client_id", "").strip()

    if not event or not client_id:
        raise HTTPException(status_code=400, detail="Missing event or client_id")

    if event not in _VALID_EVENTS:
        logger.warning("Subscription webhook unknown event=%s client=%s", event, client_id)
        return {"status": "ignored", "event": event}

    active = event in ("subscription.activated", "subscription.renewed")
    try:
        _set_active(client_id, active)
    except Exception as exc:
        logger.error("Subscription _set_active failed client=%s event=%s: %s",
                     client_id, event, exc)
        raise HTTPException(status_code=500, detail="Subscription update failed")

    log_action(client_id, "subscription", event.split(".")[1],
               client_id, {"event": event}, "success")
    return {"status": "ok", "event": event, "client_id": client_id}


def _set_active(client_id: str, active: bool) -> None:
    """Set active."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE clients SET active = %s WHERE client_id = %s",
            (active, client_id),
        )
        cur.close()