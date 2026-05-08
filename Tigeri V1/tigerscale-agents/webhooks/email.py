"""Contain email backend logic."""
import hashlib
import logging
import redis as redis_lib
from fastapi import APIRouter, HTTPException, Request
from channels.email import EmailChannel
from core.orchestrator import route
from core.conversation import pre_route
from security.sanitiser import is_sql_injection, is_prompt_injection, sanitise_input
from security.validator import validate_client_id, validate_webhook_payload
from security.rate_limiter import check_rate_limit
from security.audit import log_webhook
from config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter()
_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)
# Constant for email dedup time-to-live.
EMAIL_DEDUP_TTL = 3600


@router.post("/webhooks/email")
async def email_webhook(request: Request):
    """Execute email webhook."""
    client_id = "unknown"
    try:
        payload = await request.json()

        if "from" not in payload:
            return {"status": "ignored"}

        client_id = request.headers.get("X-Client-ID", "").strip()
        if not client_id:
            raise HTTPException(status_code=401, detail="Missing X-Client-ID header")

        client_ip = request.client.host if request.client else "unknown"
        allowed, _ = check_rate_limit(f"ip:{client_ip}", "/webhooks/email", limit=20, window=60)
        if not allowed:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        allowed, _ = check_rate_limit(client_id, "/webhooks/email")
        if not allowed:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        valid, reason = validate_client_id(client_id)
        if not valid:
            raise HTTPException(status_code=403, detail="Unauthorised")

        valid, reason = validate_webhook_payload(payload, ["from", "body"])
        if not valid:
            raise HTTPException(status_code=400, detail=reason)

        channel   = EmailChannel(client_id=client_id)
        message   = channel.parse(payload)
        raw_content = message.content
        if is_sql_injection(raw_content):
            log_webhook(client_id, "email", "/webhooks/email", 400, "sql_block")
            raise HTTPException(status_code=400, detail="Invalid request")

        if is_prompt_injection(raw_content):
            log_webhook(client_id, "email", "/webhooks/email", 400, "injection_block")
            raise HTTPException(status_code=400, detail="Invalid request")

        outcome = pre_route(client_id, message.sender, raw_content, "email")
        if outcome.handled:
            log_webhook(client_id, "email", "/webhooks/email", 200)
            return {"status": "ok", "intent": outcome.intent}

        message.content = sanitise_input(outcome.enriched_message or raw_content)
        content_hash = hashlib.sha256(raw_content.encode()).hexdigest()
        dedup_key    = f"dedup:email:{client_id}:{content_hash}"
        if _redis.get(dedup_key):
            return {"status": "duplicate", "task_id": None, "intent": None}
        _redis.setex(dedup_key, EMAIL_DEDUP_TTL, "1")

        result = route(client_id=message.client_id, message=message.content)
        log_webhook(client_id, "email", "/webhooks/email", 200)

        _replies = {
            "queued":   "Processing...",
            "escalate": "Our team will review and get back to you shortly.",
        }
        reply = _replies.get(result.get("status", ""))
        if reply:
            try:
                channel.send(recipient=message.sender, message=reply)
            except Exception as e:
                logger.warning("Email reply failed: %s", e)

        return {"status": "ok", "task_id": result.get("task_id"), "intent": result.get("intent")}

    except HTTPException:
        raise
    except ValueError:
        log_webhook(client_id, "email", "/webhooks/email", 400)
        raise HTTPException(status_code=400, detail="Bad request")
    except Exception as e:
        logger.error("Email webhook error client=%s: %s", client_id, e, exc_info=True)
        log_webhook(client_id, "email", "/webhooks/email", 500)
        raise HTTPException(status_code=500, detail="Internal server error")