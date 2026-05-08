"""Contain stripe backend logic."""
import hmac
import hashlib
import json
import time
import logging
import redis as redis_lib
from fastapi import APIRouter, Request
from fastapi.responses import Response
from config.settings import settings
from security.audit import log_action
from security.validator import validate_client_id

logger= logging.getLogger(__name__)
router = APIRouter()

_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)

# Constant for stripe replay window.
STRIPE_REPLAY_WINDOW = 300
# Constant for event dedup time-to-live.
EVENT_DEDUP_TTL = 86400
# Minimum secret len used by this module.
MIN_SECRET_LEN = 20

def _verify_stripe_signature(
    payload_bytes: bytes,
    signature: str,
    secret: str,
) -> bool:
    """Execute verify stripe signature."""
    if not signature or not secret or len(secret) < MIN_SECRET_LEN:
        return False
    try:
        parts:dict[str, str] = {}
        for part in signature.split(","):
            k, _, v = part.partition("=")
            parts[k.strip()] = v.strip()
 
        timestamp = parts.get("t", "")
        sig       = parts.get("v1", "")
        if not timestamp or not sig:
            return False
 
        try:
            ts = int(timestamp)
        except ValueError:
            return False
        if abs(time.time() - ts) > STRIPE_REPLAY_WINDOW:
            logger.warning("Stripe signature replay attempt — ts=%s", timestamp)
            return False
 
        signed_payload = f"{timestamp}.{payload_bytes.decode('utf-8')}"
        expected = hmac.new(
            secret.encode(),
            signed_payload.encode(),
            hashlib.sha256,
        ).hexdigest()
 
        return hmac.compare_digest(sig, expected)
 
    except Exception as e:
        logger.error("Stripe signature verification error: %s", e)
        return False

@router.post("/webhooks/stripe/{client_id}")
async def stripe_webhook(client_id: str, request: Request):
    """Execute stripe webhook."""
    from webhooks.integrations import get_provider_meta
    from security.encryption import decrypt_secret
 
    valid, _ = validate_client_id(client_id)
    if not valid:
        return Response(status_code=404)
 
    payload_bytes = await request.body()
    signature     = request.headers.get("stripe-signature", "")
 
    meta = get_provider_meta(client_id, "stripe")
    encrypted_secret = meta.get("webhook_secret", "")
    if not encrypted_secret:
        logger.warning("Stripe webhook: no secret configured for client=%s", client_id)
        return Response(status_code=400)
 
    try:
        webhook_secret = decrypt_secret(encrypted_secret)
    except Exception:
        logger.error("Stripe webhook: secret decryption failed for client=%s", client_id)
        return Response(status_code=400)
 
    if not _verify_stripe_signature(payload_bytes, signature, webhook_secret):
        logger.warning("Stripe invalid signature client=%s", client_id)
        return Response(status_code=401)
 
    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        return Response(status_code=400)
 
    event_id = payload.get("id", "")
    event_type = payload.get("type","")
    data = payload.get("data", {}).get("object", {})
 
    if event_id:
        dedup_key = f"stripe:event:{client_id}:{event_id}"
        if _redis.get(dedup_key):
            logger.info("Stripe duplicate event skipped: %s", event_id)
            return Response(status_code=200)
        _redis.setex(dedup_key, EVENT_DEDUP_TTL, "1")
 
    _HANDLERS = {
        "payment_intent.succeeded":  _handle_payment_succeeded,
        "invoice.paid": _handle_invoice_paid,
        "invoice.payment_failed": _handle_payment_failed,
        "charge.dispute.created": _handle_dispute_created,
        "charge.dispute.updated":_handle_dispute_updated,
        "charge.dispute.closed":_handle_dispute_closed,
    }
 
    handler = _HANDLERS.get(event_type)
    if handler:
        try:
            handler(client_id, data)
        except Exception as e:
            logger.error(
                "Stripe handler %s failed client=%s: %s",
                event_type, client_id, e, exc_info=True,
            )
            return Response(status_code=200)
 
    return Response(status_code=200)

def _handle_payment_succeeded(client_id: str, data: dict) -> None:
    """Handle payment succeeded."""
    from core.tasks import run_agent_task
 
    amount = data.get("amount", 0) / 100
    currency = data.get("currency", "usd").upper()
    payment_ref = data.get("id", "")
    payer = data.get("billing_details", {}).get("name") or "Stripe Payment"
 
    message = (
        f"Payment received {currency} {amount} "
        f"from {payer} reference {payment_ref}"
    )
    run_agent_task.apply_async( # type: ignore
        args=[client_id, "payment", message], queue="high"
    )
    log_action(
        client_id, "stripe_sync", "payment_succeeded",
        payment_ref, {"amount": amount, "currency": currency}, "success",
    )


def _handle_invoice_paid(client_id: str, data: dict) -> None:
    """Handle invoice paid."""
    from core.tasks import run_agent_task
    amount = data.get("amount_paid", 0) / 100
    currency = data.get("currency", "usd").upper()
    payment_ref = data.get("id", "")
    customer_name = data.get("customer_name") or "Stripe Customer"
 
    message = (f"Payment received {currency} {amount} " f"from {customer_name} reference {payment_ref}")

    run_agent_task.apply_async( # type: ignore
        args=[client_id, "payment", message], queue="high"
    )
    log_action(client_id, "stripe_sync", "invoice_paid",payment_ref, {}, "success",)


def _handle_payment_failed(client_id: str, data: dict) -> None:
    """Handle payment failed."""
    from config.db_pool import get_conn
 
    invoice_id = data.get("id", "")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE invoices SET status = 'overdue'
            WHERE client_id = %s AND external_id = %s
            RETURNING invoice_number
            """,
            (client_id, invoice_id),
        )
        row = cur.fetchone()
        cur.close()
 
    log_action(client_id, "stripe_sync", "payment_failed", invoice_id, {}, "error")
    if row:
        _notify_client(client_id,f"Payment failed for invoice {row[0] or invoice_id}. Please review.", )
        
def _handle_dispute_created(client_id: str, data: dict) -> None:
    """Handle dispute created."""
    from config.db_pool import get_conn
    from core.tasks import run_agent_task
 
    dispute_id = data.get("id", "")
    payment_intent = data.get("payment_intent", "")
    amount = data.get("amount", 0) / 100
    currency = data.get("currency", "usd").upper()
    reason = data.get("reason", "unknown")
    due_by = data.get("evidence_details", {}).get("due_by")
 
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO disputes
              (client_id, dispute_id, payment_ref, gateway,
               amount, currency, reason, status, due_by)
            VALUES (%s, %s, %s, 'stripe', %s, %s, %s, 'needs_response', to_timestamp(%s))
            ON CONFLICT (dispute_id) DO UPDATE
              SET status = 'needs_response', updated_at = NOW()
            """,
            (client_id, dispute_id, payment_intent,
             amount, currency, reason, due_by),
        )
        cur.close()
 
    message = (
        f"Dispute opened on payment {payment_intent} "
        f"amount {currency} {amount} dispute_id {dispute_id} reason {reason}"
    )
    run_agent_task.apply_async(args=[client_id, "payment", message], queue="high") # type: ignore
    _notify_client(
        client_id,
        f"Dispute alert — {currency} {amount} disputed\n"
        f"Reason: {reason}\nPayment: {payment_intent}\n"
        f"Dispute ID: {dispute_id}\n"
        f"Evidence due: {due_by or 'check Stripe dashboard'}",
    )
    log_action(
        client_id, "stripe_sync", "dispute_created",
        dispute_id, {"amount": amount, "reason": reason}, "escalate",
    )


def _handle_dispute_updated(client_id: str, data: dict) -> None:
    """Handle dispute updated."""
    from config.db_pool import get_conn
 
    dispute_id = data.get("id","")
    status = data.get("status", "unknown")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE disputes SET status = %s, updated_at = NOW()
            WHERE client_id = %s AND dispute_id = %s
            """,
            (status, client_id, dispute_id),
        )
        cur.close()

    log_action(client_id, "stripe_sync", "dispute_updated",dispute_id, {"status": status}, "success",)


def _handle_dispute_closed(client_id: str, data: dict) -> None:
    """Handle dispute closed."""
    from config.db_pool import get_conn
 
    dispute_id = data.get("id","")
    status = data.get("status", "lost")
    amount = data.get("amount", 0) / 100
    currency = data.get("currency", "usd").upper()
 
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE disputes SET status = %s, updated_at = NOW()
            WHERE client_id = %s AND dispute_id = %s
            """,
            (status, client_id, dispute_id),
        )
        cur.close()
 
    outcome = "won" if status == "won" else "lost"
    _notify_client(
        client_id,
        f"Dispute {outcome} — {currency} {amount}\n"
        f"Dispute ID: {dispute_id}\nFinal status: {status}",
    )
    log_action(
        client_id, "stripe_sync", "dispute_closed",
        dispute_id, {"status": status, "amount": amount}, "success",
    )

def _notify_client(client_id: str, message: str) -> None:
    """Execute notify client."""
    try:
        from core.alerting import send_client_telegram_alert
        send_client_telegram_alert(client_id, message)
    except Exception as e:
        logger.error("_notify_client failed client=%s: %s", client_id, e)