"""Contain approval backend logic."""
from __future__ import annotations

import json
import logging

import redis as redis_lib
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from config.settings import settings
from security.approval_token import verify_approval_token

logger = logging.getLogger(__name__)
router = APIRouter()
_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)

_RESULT_TTL = 300


def _html(title: str, message: str, color: str) -> HTMLResponse:
    """Execute html."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh; margin: 0;
      background: #f5f5f5;
    }}
    .card {{
      background: white; border-radius: 12px; padding: 48px 40px;
      text-align: center; max-width: 400px; width: 90%;
      box-shadow: 0 4px 24px rgba(0,0,0,0.08);
    }}
    h1 {{ color: {color}; font-size: 24px; margin: 0 0 12px; }}
    p  {{ color: #666; font-size: 15px; margin: 0; line-height: 1.5; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{title}</h1>
    <p>{message}</p>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/webhooks/approve")
def handle_email_approval(token: str, result: str) -> HTMLResponse:
    """Handle email approval."""
    if result not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid result value")

    try:
        payload = verify_approval_token(token)
    except ValueError as exc:
        logger.warning("Approval token verification failed: %s", exc)
        return _html(
            title="Link Invalid or Expired",
            message="This approval link is invalid or has expired. "
                    "Please ask for a new approval request to be sent.",
            color="#e67e22",
        )

    client_id = payload["client_id"]
    task_id   = payload["task_id"]
    action    = payload.get("action", "")

    pending_key = f"approval:pending:{client_id}:{task_id}"
    result_key  = f"approval:result:{client_id}:{task_id}"

    if _redis.exists(result_key):
        return _html(
            title="Already Decided",
            message="This request has already been approved or rejected.",
            color="#3498db",
        )

    if not _redis.exists(pending_key):
        return _html(
            title="Request Expired",
            message="This approval request has expired. "
                    "The original action will need to be retried.",
            color="#e67e22",
        )

    import hashlib
    import hmac
    import time
    from config.settings import settings as _settings

    result_payload = {
        "status":    result,
        "client_id": client_id,
        "task_id":   task_id,
        "action":    action,
        "decided_at": int(time.time()),
    }
    secret = getattr(_settings, "approval_hmac_secret", client_id)
    sig = hmac.new(
        secret.encode(),
        json.dumps(result_payload, sort_keys=True).encode(),
        hashlib.sha256,
    ).hexdigest()
    result_payload["sig"] = sig

    _redis.setex(result_key, _RESULT_TTL, json.dumps(result_payload))
    _redis.delete(pending_key)

    logger.info(
        "Email approval: client=%s task=%s action=%s result=%s",
        client_id, task_id, action, result,
    )

    if result == "approved":
        return _html(
            title="Approved",
            message=f"The {action.replace('_', ' ')} has been approved successfully. "
                    "The action will complete shortly.",
            color="#27ae60",
        )
    return _html(
        title="Rejected",
        message=f"The {action.replace('_', ' ')} has been rejected.",
        color="#e74c3c",
    )