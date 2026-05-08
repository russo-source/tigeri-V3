"""Contain telegram backend logic."""
from __future__ import annotations
import hashlib
import hmac
import json
import logging
import re
import time
import redis as redis_lib
from fastapi import APIRouter, HTTPException, Request

from channels.document_router import route as doc_route
from channels.telegram import TelegramChannel
from config.channel_registry import resolve_client_id
from config.settings import settings
from core.conversation import pre_route, save_agent_reply, clear_context
from core.orchestrator import route
from security.audit import log_webhook
from security.rate_limiter import check_rate_limit
from security.sanitiser import is_prompt_injection, is_sql_injection, sanitise_input
from security.validator import validate_client_id, validate_webhook_payload

logger = logging.getLogger(__name__)
router = APIRouter()
_redis= redis_lib.from_url(settings.redis_url, decode_responses=True)
_TASK_RE = re.compile(r"^[a-f0-9][a-f0-9\-]{6,62}[a-f0-9]$")
MAX_MSG = 1000
_RESULT_TTL = 300


def _apply_media_group_caption(payload: dict, message_content: str, sender: str, client_id: str) -> str:
    """Apply first caption of a Telegram media group to later files in the same group."""
    msg = payload.get("message") or {}
    media_group_id = str(msg.get("media_group_id") or "").strip()
    if not media_group_id:
        return message_content

    key = f"tg:media_group:caption:{client_id}:{sender}:{media_group_id}"
    caption = (msg.get("caption") or "").strip()

    if caption:
        try:
            _redis.setex(key, 600, caption)
        except Exception:
            pass
        return message_content

    try:
        stored_caption = str(_redis.get(key) or "").strip()
    except Exception:
        stored_caption = ""

    if not stored_caption:
        return message_content

    content = (message_content or "").strip()
    if not content:
        return stored_caption

    if stored_caption in content:
        return content

    return f"{stored_caption}\n\n[Grouped document content]\n{content[:4000]}"


def _resolve_client(request: Request, channel: str) -> str:
    client_ip = request.client.host if request.client else "unknown"

    token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "").strip()
    if token:
        client_id = resolve_client_id(channel, token)
        if client_id:
            return client_id

    bot_token = request.headers.get("X-Bot-Token", "").strip()
    if bot_token:
        client_id = resolve_client_id(channel, bot_token)
        if client_id:
            return client_id

    logger.warning("Telegram unauthorised probe ip=%s", client_ip)
    log_webhook("unknown", "telegram", "/_auth", 401, "no_valid_token")
    raise HTTPException(status_code=401, detail="Unauthorised")


def _store_task_sender(
    task_id: str,
    sender: str,
    client_id: str,
) -> None:
    pipe = _redis.pipeline(transaction=False)
    pipe.setex(f"task:sender:{task_id}", 300, sender)
    pipe.setex(f"telegram:last_sender:{client_id}", 3600, sender)
    pipe.setex(f"task:channel:{task_id}", 300, "telegram")
    pipe.execute()

def _sign_result(payload: dict, secret: str) -> str:
    return hmac.new(
        secret.encode(),
        json.dumps(payload, sort_keys=True).encode(),
        hashlib.sha256,
    ).hexdigest()

def _extract_task_id(data: str, prefix: str) -> str | None:
    if not data.startswith(f"{prefix}:"):
        return None
    parts = data.split(":", 1)
    if len(parts) != 2:
        return None
    task_id = parts[1].strip()
    return task_id if _TASK_RE.match(task_id) else None


@router.post("/webhooks/telegram")
async def telegram_webhook(request: Request) -> dict:
    client_id = "unknown"
    try:
        payload = await request.json()

        if "message" not in payload:
            return {"status": "ignored"}

        client_id = _resolve_client(request, "telegram")
        client_ip = request.client.host if request.client else "unknown"

        allowed, _ = check_rate_limit(
            f"ip:{client_ip}", "/webhooks/telegram", limit=60, window=60
        )
        if not allowed:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        allowed, _ = check_rate_limit(client_id, "/webhooks/telegram")
        if not allowed:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        valid, _ = validate_client_id(client_id)
        if not valid:
            raise HTTPException(status_code=403, detail="Unauthorised")
        valid, reason = validate_webhook_payload(payload, ["message"])
        if not valid:
            raise HTTPException(status_code=400, detail=reason)

        channel = TelegramChannel(client_id=client_id)
        message = channel.parse(payload)

        if message.content.startswith("/"):
            cmd = message.content.split()[0].lower()
            if cmd == "/cancel":
                clear_context(message.sender, client_id)
                channel.send(message.sender, "Understood. Starting fresh.")
            elif cmd in ("/start", "/help"):
                from core.orchestrator import _handle_general
                result = _handle_general(message.content, client_id)
                channel.send(message.sender, result.get("message", ""))
            elif cmd == "/menu":
                channel.send(
                    message.sender,
                    "Send me a command or upload a PDF invoice to get started.",
                )
            else:
                channel.send(message.sender, "Unknown command. Type /help for options.")
            log_webhook(client_id, "telegram", "/webhooks/telegram", 200)
            return {"status": "ok", "intent": "command"}

        raw_content = _apply_media_group_caption(
            payload=payload,
            message_content=message.content,
            sender=message.sender,
            client_id=client_id,
        )
        message.content = raw_content
        routed = doc_route(
            message,
            mime_type=message.mime_type,
            filename=message.filename,
        )

        # Enforce text-length limits only for plain text messages.
        # For documents/images, message.content may include extracted file text.
        if not routed.is_document and len(raw_content) > MAX_MSG:
            log_webhook(client_id, "telegram", "/webhooks/telegram", 400, "oversized_input")
            channel.send(message.sender, f"Message too long. Keep it under {MAX_MSG} characters.")
            return {"status": "blocked"}

        if is_sql_injection(raw_content) or is_prompt_injection(raw_content):
            log_webhook(client_id, "telegram", "/webhooks/telegram", 400, "injection_block")
            channel.send(message.sender, "I can't process that request.")
            return {"status": "blocked"}

        outcome = pre_route(client_id, message.sender, raw_content, "telegram")
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
            log_webhook(client_id, "telegram", "/webhooks/telegram", 200)
            return {"status": "ok", "intent": outcome.intent}

        message.content = sanitise_input(outcome.enriched_message or raw_content)

        if routed.is_document and routed.is_admin:
            result = route(
                client_id=client_id,
                message=message.content,
                sender=message.sender,
                channel="telegram",
                mime_type=message.mime_type,
                filename=message.filename,
                file_bytes=message.file_bytes,
            )
            if result.get("task_id"):
                _store_task_sender(result["task_id"], message.sender, client_id)
            channel.send(message.sender, "Your document is being processed.")
            log_webhook(client_id, "telegram", "/webhooks/telegram", 200)
            return {"status": "ok", "task_id": result.get("task_id"), "intent": "admin"}

        if routed.is_document:
            result = route(
                client_id=client_id,
                message=message.content,
                sender=message.sender,
                channel="telegram",
                mime_type=message.mime_type,
                filename=message.filename,
                file_bytes=message.file_bytes,
            )
            if result.get("task_id"):
                _store_task_sender(result["task_id"], message.sender, client_id)
            channel.send(message.sender, "Your document is being processed.")
            log_webhook(client_id, "telegram", "/webhooks/telegram", 200)
            return {"status": "ok", "task_id": result.get("task_id"), "intent": "inbound_bill"}

        result = route(
            client_id=message.client_id,
            message=message.content,
            sender=message.sender,
            channel="telegram",
            file_bytes=message.file_bytes,
        )

        if result.get("task_id"):
            _store_task_sender(result["task_id"], message.sender, client_id)

        log_webhook(client_id, "telegram", "/webhooks/telegram", 200)

        _REPLIES = {
            "queued":      "Processing...",
            "escalate":    "Our team will follow up shortly.",
            "maintenance": "System is under maintenance. Please try again later.",
            "paused":      "This service is temporarily unavailable.",
        }
        reply = _REPLIES.get(result.get("status", ""))
        if not reply and result.get("message"):
            reply = result["message"]
        if reply:
            channel.send(message.sender, reply)
            save_agent_reply(message.sender, client_id, reply)
        elif result.get("status") == "error":
            err_reply = result.get("message", "Something went wrong. Please try again.")
            channel.send(message.sender, err_reply)
            save_agent_reply(message.sender, client_id, err_reply)

        agent_result = result.get("result") or {}
        file_bytes = agent_result.get("file_bytes")
        filename = agent_result.get("filename", "document")
        if file_bytes and isinstance(file_bytes, bytes) and len(file_bytes) > 0:
            try:
                channel.send_document(
                    recipient=message.sender,
                    document=file_bytes,
                    filename=filename,
                    caption=f" {filename}",
                )
            except Exception as e:
                logger.warning(
                    "send_document failed client=%s filename=%s: %s",
                    client_id, filename, e,
                )

        return {
            "status":  "ok",
            "task_id": result.get("task_id"),
            "intent":  result.get("intent"),
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "telegram_webhook error client=%s: %s",
            client_id, exc, exc_info=True,
        )
        log_webhook(client_id, "telegram", "/webhooks/telegram", 500)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/webhooks/telegram/callback")
async def telegram_callback_handler(request: Request) -> dict:
    client_id = "unknown"
    try:
        payload = await request.json()
        callback = payload.get("callback_query")
        if not callback or not isinstance(callback, dict):
            return {"status": "ignored"}

        from_data = callback.get("from", {})
        chat_id = str(from_data.get("id", "")).strip()
        if not chat_id or not chat_id.isdigit():
            raise HTTPException(status_code=400, detail="Invalid callback sender")

        callback_data = callback.get("data", "").strip()
        if not callback_data:
            return {"status": "ignored"}

        client_id = _resolve_client(request, "telegram")
        client_ip = request.client.host if request.client else "unknown"

        allowed, _ = check_rate_limit(
            f"ip:{client_ip}", "/webhooks/telegram/callback", limit=20, window=60,
        )
        if not allowed:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        allowed, _ = check_rate_limit(
            client_id, "/webhooks/telegram/callback", limit=20, window=60,
        )
        if not allowed:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        valid, _ = validate_client_id(client_id)
        if not valid:
            raise HTTPException(status_code=403, detail="Unauthorised")

        channel = TelegramChannel(client_id=client_id)

        _ACTIONS = {
            "payment_approve": ("Approved", "approved"),
            "payment_reject":  ("Rejected", "rejected"),
        }

        for prefix, (label, status_value) in _ACTIONS.items():
            if callback_data.startswith(f"{prefix}:"):
                task_id = _extract_task_id(callback_data, prefix)
                if not task_id:
                    raise HTTPException(status_code=400, detail="Invalid callback data")

                task_client = _redis.get(f"task:client:{task_id}")
                if task_client and task_client != client_id:
                    raise HTTPException(status_code=403, detail="Unauthorised")

                result_payload = {
                    "status":     status_value,
                    "client_id":  client_id,
                    "task_id":    task_id,
                    "decided_at": int(time.time()),
                    "channel":    "telegram",
                    "approver":   chat_id,
                }
                secret = getattr(settings, "approval_hmac_secret", client_id)
                result_payload["sig"] = _sign_result(result_payload, secret)
                result_key  = f"approval:result:{client_id}:{task_id}"
                pending_key = f"approval:pending:{client_id}:{task_id}"

                _redis.setex(result_key, _RESULT_TTL, json.dumps(result_payload))
                _redis.delete(pending_key)

                channel.send(chat_id, f"{label}.")
                log_webhook(client_id, "telegram", "/webhooks/telegram/callback", 200)
                return {"status": "ok"}

        logger.warning("Unknown callback action: %r client=%s", callback_data, client_id)
        return {"status": "ignored"}

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "telegram_callback error client=%s: %s",
            client_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")