"""Contain Twilio WhatsApp webhook backend logic."""
from __future__ import annotations

import logging

import redis as redis_lib
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from channels.document_router import route as doc_route
from channels.twilio_whatsapp import TwilioWhatsAppChannel, validate_twilio_signature
from config.settings import settings
from core.conversation import pre_route, save_agent_reply
from core.orchestrator import route
from security.audit import log_webhook
from security.rate_limiter import check_rate_limit
from security.sanitiser import is_prompt_injection, is_sql_injection, sanitise_input
from security.validator import validate_client_id, validate_webhook_payload

logger = logging.getLogger(__name__)
router = APIRouter()
_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)

# Minimal TwiML response — Twilio requires an XML reply; an empty <Response/>
# tells Twilio "do nothing further". We deliver replies via the REST API instead.
_TWIML_EMPTY = "<?xml version='1.0' encoding='UTF-8'?><Response/>"
_XML = "application/xml"


def _store_task_sender(task_id: str, sender: str, client_id: str) -> None:
    pipe = _redis.pipeline(transaction=False)
    pipe.setex(f"task:sender:twilio_whatsapp:{task_id}", 300, sender)
    pipe.setex(f"twilio_whatsapp:last_sender:{client_id}", 3600, sender)
    pipe.setex(f"task:channel:{task_id}", 300, "twilio_whatsapp")
    pipe.execute()


def _validate_twilio_request(
    request: Request, client_id: str, params: dict
) -> None:
    """Validate X-Twilio-Signature. Skipped in development mode."""
    if settings.env == "development":
        return

    signature = request.headers.get("X-Twilio-Signature", "").strip()
    if not signature:
        raise HTTPException(status_code=403, detail="Missing Twilio signature")

    from integrations.token_manager import _get_stored
    stored = _get_stored(f"twilio_whatsapp:{client_id}") or {}
    auth_token = stored.get("access_token", "")
    if not auth_token:
        raise HTTPException(
            status_code=403, detail="Twilio not configured for this client"
        )

    # Behind AWS ALB, str(request.url) returns the internal container URL
    # (e.g. http://10.x.x.x:8000/...) not the public URL Twilio signed against.
    # Reconstruct the canonical public URL from settings.backend_url so the
    # HMAC matches what Twilio computed.
    path = request.url.path
    query = str(request.url.query)
    url = f"{settings.backend_url}{path}"
    if query:
        url += f"?{query}"
    if not validate_twilio_signature(auth_token, signature, url, params):
        logger.warning(
            "Twilio signature mismatch client=%s url=%s", client_id, url
        )
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


async def _process_twilio_message(
    client_id: str,
    request: Request,
    payload: dict,
) -> Response:
    client_ip = request.client.host if request.client else "unknown"

    allowed, _ = check_rate_limit(
        f"ip:{client_ip}", "/webhooks/twilio", limit=60, window=60
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    allowed, _ = check_rate_limit(client_id, "/webhooks/twilio")
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    valid, reason = validate_client_id(client_id)
    if not valid:
        logger.warning(
            "Twilio WhatsApp invalid client_id=%s reason=%s ip=%s",
            client_id, reason, client_ip,
        )
        raise HTTPException(status_code=403, detail="Unauthorised")

    valid, reason = validate_webhook_payload(payload, ["From", "AccountSid"])
    if not valid:
        raise HTTPException(status_code=400, detail=reason)

    channel = TwilioWhatsAppChannel(client_id=client_id)
    message = channel.parse(payload)
    raw_content = message.content

    if is_sql_injection(raw_content) or is_prompt_injection(raw_content):
        log_webhook(
            client_id, "twilio_whatsapp",
            "/webhooks/twilio", 400, "injection_block",
        )
        raise HTTPException(status_code=400, detail="Invalid request")

    outcome = pre_route(
        client_id, message.sender, raw_content, "twilio_whatsapp"
    )
    if outcome.handled:
        if outcome.reply:
            channel.send(message.sender, outcome.reply)
        if outcome.pdf_bytes:
            channel.send_document(
                recipient=message.sender,
                document=outcome.pdf_bytes,
                filename=outcome.pdf_filename,
                caption=outcome.pdf_caption,
            )
        log_webhook(client_id, "twilio_whatsapp", "/webhooks/twilio", 200)
        return Response(content=_TWIML_EMPTY, media_type=_XML)

    message.content = sanitise_input(outcome.enriched_message or raw_content)

    routed = doc_route(
        message,
        mime_type=message.mime_type,
        filename=message.filename,
    )

    if routed.is_document:
        result = route(
            client_id=client_id,
            message=message.content,
            sender=message.sender,
            channel="twilio_whatsapp",
            mime_type=message.mime_type,
            filename=message.filename,
            file_bytes=message.file_bytes,
        )
        if result.get("task_id"):
            _store_task_sender(result["task_id"], message.sender, client_id)
        channel.send(message.sender, "Your document is being processed.")
        log_webhook(client_id, "twilio_whatsapp", "/webhooks/twilio", 200)
        return Response(content=_TWIML_EMPTY, media_type=_XML)

    result = route(
        client_id=message.client_id,
        message=message.content,
        sender=message.sender,
        channel="twilio_whatsapp",
        file_bytes=message.file_bytes,
    )
    status = result.get("status", "")

    if result.get("task_id"):
        _store_task_sender(result["task_id"], message.sender, client_id)

    log_webhook(client_id, "twilio_whatsapp", "/webhooks/twilio", 200)

    _REPLIES = {
        "queued":      "Processing...",
        "escalate":    "Our team will review and get back to you shortly.",
        "maintenance": "System is under maintenance. Please try again later.",
        "paused":      "This service is temporarily unavailable.",
    }
    reply = _REPLIES.get(status)
    if not reply and result.get("message"):
        reply = result["message"]
    if reply:
        channel.send(message.sender, reply)
        save_agent_reply(message.sender, client_id, reply)
    elif status == "error":
        err_reply = result.get("message", "Something went wrong. Please try again.")
        channel.send(message.sender, err_reply)
        save_agent_reply(message.sender, client_id, err_reply)

    return Response(content=_TWIML_EMPTY, media_type=_XML)


@router.post("/webhooks/twilio/{client_id}")
async def twilio_whatsapp_webhook_client(
    client_id: str,
    request: Request,
) -> Response:
    try:
        form = await request.form()
        payload = dict(form)

        # Only handle WhatsApp messages (Twilio also handles SMS on same endpoint).
        if not payload.get("From", "").startswith("whatsapp:"):
            return Response(content=_TWIML_EMPTY, media_type=_XML)

        _validate_twilio_request(request, client_id, payload)

        logger.debug(
            "Twilio WhatsApp inbound per-client client=%s", client_id
        )
        return await _process_twilio_message(client_id, request, payload)

    except HTTPException:
        raise
    except ValueError:
        log_webhook(
            client_id, "twilio_whatsapp",
            f"/webhooks/twilio/{client_id}", 400,
        )
        raise HTTPException(status_code=400, detail="Bad request")
    except Exception as exc:
        logger.error(
            "Twilio WhatsApp webhook error client=%s: %s",
            client_id, exc, exc_info=True,
        )
        log_webhook(
            client_id, "twilio_whatsapp",
            f"/webhooks/twilio/{client_id}", 500,
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/webhooks/twilio")
async def twilio_whatsapp_webhook_legacy(request: Request) -> Response:
    """Handle Twilio WhatsApp webhook without explicit client_id in the URL path.

    Client resolution order:
      1. X-Client-ID request header (explicit override).
      2. Redis lookup on the Twilio WhatsApp "To" number (registered at connect time).
    """
    client_id = "unknown"
    try:
        form = await request.form()
        payload = dict(form)

        if not payload.get("From", "").startswith("whatsapp:"):
            return Response(content=_TWIML_EMPTY, media_type=_XML)

        client_ip = request.client.host if request.client else "unknown"

        client_id = request.headers.get("X-Client-ID", "").strip()
        if not client_id:
            # "To" is the client's Twilio number, e.g. "whatsapp:+14155238886"
            raw_to = (
                payload.get("To", "")
                .replace("whatsapp:", "")
                .replace("+", "")
                .strip()
            )
            if raw_to:
                resolved = _redis.get(f"twilio_whatsapp:phone:{raw_to}")
                if resolved:
                    client_id = str(resolved)

        if not client_id or client_id == "unknown":
            logger.warning(
                "Twilio legacy could not resolve client ip=%s", client_ip
            )
            raise HTTPException(status_code=401, detail="Unauthorised")

        _validate_twilio_request(request, client_id, payload)

        logger.debug(
            "Twilio WhatsApp inbound legacy client=%s", client_id
        )
        return await _process_twilio_message(client_id, request, payload)

    except HTTPException:
        raise
    except ValueError:
        log_webhook(client_id, "twilio_whatsapp", "/webhooks/twilio", 400)
        raise HTTPException(status_code=400, detail="Bad request")
    except Exception as exc:
        logger.error(
            "Twilio WhatsApp webhook error client=%s: %s",
            client_id, exc, exc_info=True,
        )
        log_webhook(client_id, "twilio_whatsapp", "/webhooks/twilio", 500)
        raise HTTPException(status_code=500, detail="Internal server error")
