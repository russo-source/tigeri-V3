from __future__ import annotations

import logging
import re

import redis as redis_lib
from fastapi import APIRouter, HTTPException, Request

from channels.document_router import route as doc_route
from channels.whatsapp import WhatsAppChannel
from config.channel_registry import resolve_client_id
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
_SENDER_RE = re.compile(r"^\d{7,15}$")
MAX_MSG = 1000


def _normalize_payload(payload: dict) -> dict:
    """Normalize Meta Cloud API format to 360dialog flat format."""
    if "entry" in payload:
        try:
            value = payload["entry"][0]["changes"][0]["value"]
            if "messages" not in value:
                return {}
            return {
                "contacts": value.get("contacts", []),
                "messages": value.get("messages", []),
            }
        except (KeyError, IndexError):
            return {}
    return payload


def _store_task_sender(
    task_id: str,
    sender: str,
    client_id: str,
) -> None:
    pipe = _redis.pipeline(transaction=False)
    pipe.setex(f"task:sender:whatsapp:{task_id}", 300, sender)
    pipe.setex(f"whatsapp:last_sender:{client_id}", 3600, sender)
    pipe.setex(f"task:channel:{task_id}", 300, "whatsapp")
    pipe.execute()


def _resolve_client_legacy(request: Request, payload: dict) -> str:
    client_ip = request.client.host if request.client else "unknown"

    client_id = request.headers.get("X-Client-ID", "").strip()
    if client_id:
        logger.debug(
            "WhatsApp legacy resolved via X-Client-ID client=%s", client_id
        )
        return client_id

    api_key = request.headers.get("D360-API-KEY", "").strip()
    if api_key:
        resolved = resolve_client_id("whatsapp", api_key)
        if resolved:
            logger.debug(
                "WhatsApp legacy resolved via D360-API-KEY client=%s", resolved
            )
            return resolved
        logger.warning(
            "WhatsApp invalid API key probe ip=%s", client_ip
        )
        raise HTTPException(status_code=401, detail="Unauthorised")

    try:
        phone = (
            payload.get("contacts", [{}])[0]
            .get("wa_id", "")
            .strip()
        )
    except Exception:
        phone = ""

    if phone and _SENDER_RE.match(phone):
        resolved = _redis.get(f"whatsapp:phone:{phone}")
        if resolved:
            logger.debug(
                "WhatsApp legacy resolved via phone phone=%s client=%s",
                phone, resolved,
            )
            return str(resolved)
        logger.warning(
            "WhatsApp phone %s not mapped to any client ip=%s",
            phone, client_ip,
        )

    logger.warning(
        "WhatsApp legacy could not resolve client ip=%s phone=%s",
        client_ip, phone,
    )
    raise HTTPException(status_code=401, detail="Unauthorised")


async def _process_whatsapp_message(
    client_id: str,
    request: Request,
    payload: dict,
) -> dict:
    client_ip = request.client.host if request.client else "unknown"

    allowed, _ = check_rate_limit(
        f"ip:{client_ip}", "/webhooks/whatsapp", limit=60, window=60
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    allowed, _ = check_rate_limit(client_id, "/webhooks/whatsapp")
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    valid, reason = validate_client_id(client_id)
    if not valid:
        logger.warning(
            "WhatsApp invalid client_id=%s reason=%s ip=%s",
            client_id, reason, client_ip,
        )
        raise HTTPException(status_code=403, detail="Unauthorised")

    valid, reason = validate_webhook_payload(
        payload, ["messages", "contacts"]
    )
    if not valid:
        raise HTTPException(status_code=400, detail=reason)

    channel = WhatsAppChannel(client_id=client_id)
    message = channel.parse(payload)
    raw_content = message.content

    if is_sql_injection(raw_content) or is_prompt_injection(raw_content):
        log_webhook(
            client_id, "whatsapp",
            "/webhooks/whatsapp", 400, "injection_block",
        )
        raise HTTPException(status_code=400, detail="Invalid request")

    outcome = pre_route(
        client_id, message.sender, raw_content, "whatsapp"
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
        log_webhook(client_id, "whatsapp", "/webhooks/whatsapp", 200)
        return {"status": "ok", "intent": outcome.intent}

    message.content = sanitise_input(
        outcome.enriched_message or raw_content
    )

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
            channel="whatsapp",
            mime_type=message.mime_type,
            filename=message.filename,
            file_bytes=message.file_bytes,
        )
        if result.get("task_id"):
            _store_task_sender(result["task_id"], message.sender, client_id)
        channel.send(message.sender, "Your document is being processed.")
        log_webhook(client_id, "whatsapp", "/webhooks/whatsapp", 200)
        return {"status": "ok", "task_id": result.get("task_id"), "intent": "inbound_bill"}

    result = route(
        client_id=message.client_id,
        message=message.content,
        sender=message.sender,
        channel="whatsapp",
        file_bytes=message.file_bytes,
    )
    status = result.get("status", "")

    if result.get("task_id"):
        _store_task_sender(result["task_id"], message.sender, client_id)

    log_webhook(client_id, "whatsapp", "/webhooks/whatsapp", 200)

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

    return {
        "status":  "ok",
        "task_id": result.get("task_id"),
        "intent":  result.get("intent"),
    }

@router.post("/webhooks/whatsapp/{client_id}")
async def whatsapp_webhook_client(
    client_id: str,
    request: Request,
) -> dict:
    try:
        raw_payload = await request.json()
        payload = _normalize_payload(raw_payload)

        if not payload or "messages" not in payload:
            return {"status": "ignored"}

        logger.debug(
            "WhatsApp inbound per-client client=%s", client_id
        )

        return await _process_whatsapp_message(client_id, request, payload)

    except HTTPException:
        raise
    except ValueError:
        log_webhook(
            client_id, "whatsapp",
            f"/webhooks/whatsapp/{client_id}", 400,
        )
        raise HTTPException(status_code=400, detail="Bad request")
    except Exception as exc:
        logger.error(
            "WhatsApp webhook error client=%s: %s",
            client_id, exc, exc_info=True,
        )
        log_webhook(
            client_id, "whatsapp",
            f"/webhooks/whatsapp/{client_id}", 500,
        )
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/webhooks/whatsapp")
async def whatsapp_webhook_legacy(request: Request) -> dict:
    client_id = "unknown"
    try:
        raw_payload = await request.json()
        payload = _normalize_payload(raw_payload)

        if not payload or "messages" not in payload:
            return {"status": "ignored"}

        client_id = _resolve_client_legacy(request, payload)

        logger.debug(
            "WhatsApp inbound legacy client=%s", client_id
        )

        return await _process_whatsapp_message(client_id, request, payload)

    except HTTPException:
        raise
    except ValueError:
        log_webhook(client_id, "whatsapp", "/webhooks/whatsapp", 400)
        raise HTTPException(status_code=400, detail="Bad request")
    except Exception as exc:
        logger.error(
            "WhatsApp webhook error client=%s: %s",
            client_id, exc, exc_info=True,
        )
        log_webhook(client_id, "whatsapp", "/webhooks/whatsapp", 500)
        raise HTTPException(
            status_code=500, detail="Internal server error"
        )