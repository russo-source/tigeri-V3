"""Contain tools backend logic."""
from __future__ import annotations
import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timezone
import redis as redis_lib
from agents.base_agent import _get_client
from agents.a04_payment.prompts import PAYMENT_TOOLS_PROMPT, _PAYMENT_CONFIRMATION_PROMPT
from config.db_pool import get_conn
from config.settings import settings
logger = logging.getLogger(__name__)
_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)

def parse_payment_message(message: str) -> dict:
    """Parse payment message."""
    response = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=PAYMENT_TOOLS_PROMPT,
        messages=[{"role": "user", "content": message}],
    )
    for block in response.content:
        if block.type == "text":
            text = block.text.strip()
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text).strip()
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {}
    return {}

def validate_payment(data: dict) -> tuple[bool, str]:
    """Validate payment."""
    from agents.a04_payment.config import PAYMENT_CONFIG

    if not data.get("action"):
        return False, "I couldn't determine what you'd like to do — try: track a payment, reconcile, refund, or check status."

    if data["action"] not in PAYMENT_CONFIG["valid_actions"]:
        return False, f"Unknown action: {data['action']}"

    if data["action"] == "track_payment" and not data.get("amount"):
        return False, "Please provide the payment amount."

    if data["action"] in ("refund", "capture_payment", "cancel_payment") and not data.get("payment_ref"):
        return False, f"{data['action'].replace('_', ' ').title()} requires a payment reference."

    if data["action"] == "check_payment_status" and not data.get("payment_ref"):
        return False, "Please provide the payment reference to check status."

    if data["action"] == "handle_dispute" and not data.get("dispute_id") and not data.get("payment_ref"):
        return False, "Please provide the dispute ID or payment reference."

    return True, "ok"


def match_payment_to_invoice(
    client_id: str,
    payment_amount: float,
    payment_ref: str,
    payer: str,
) -> dict | None:
    """Execute match payment to invoice."""
    if not payer or payer.strip().lower() in ("unknown", "none", ""):
        return None
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, invoice_number, amount, vendor, status, external_id
                FROM invoices
                WHERE client_id = %s
                  AND status NOT IN ('paid', 'cancelled')
                  AND (
                      (amount = %s AND LOWER(vendor) = LOWER(%s))
                      OR (amount = %s AND invoice_number = %s)
                      OR (amount = %s AND LOWER(vendor) LIKE LOWER(%s))
                  )
                ORDER BY
                    CASE
                        WHEN amount = %s AND LOWER(vendor) = LOWER(%s) THEN 1
                        WHEN amount = %s AND invoice_number = %s         THEN 2
                        ELSE 3
                    END,
                    created_at DESC
                LIMIT 1
                """,
                (
                    client_id,
                    payment_amount, payer,
                    payment_amount, payment_ref,
                    payment_amount, f"%{payer}%",
                    payment_amount, payer,
                    payment_amount, payment_ref,
                ),
            )
            row = cur.fetchone()
            cur.close()
        if not row:
            return None
        return {
            "invoice_id": row[0],
            "invoice_number": row[1],
            "invoice_amount": float(row[2]),
            "vendor": row[3],
            "status": row[4],
            "xero_invoice_id": row[5],
            "match_type": "exact" if float(row[2]) == payment_amount else "partial",
        }
    except Exception as exc:
        logger.error("match_payment_to_invoice failed client=%s: %s", client_id, exc)
        return None

def _sign_result_payload(payload: dict, secret: str) -> str:
    """Execute sign result payload."""
    return hmac.new(
        secret.encode(),
        json.dumps(payload, sort_keys=True).encode(),
        hashlib.sha256,
    ).hexdigest()


def resolve_gateway(data: dict, client_id: str):
    """Resolve gateway."""
    from integrations.payment_factory import get_payment_gateway
    method = data.get("payment_method", "unknown")
    if method == "stripe":
        return get_payment_gateway("stripe", client_id)
    if method == "paypal":
        return get_payment_gateway("paypal", client_id)
    return None

def _sign_approval_payload(payload: str, secret: str) -> str:
    """Execute sign approval payload."""
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

def send_approval_request(
    client_id: str,
    action: str,
    data: dict,
    task_id: str,
    sender_channel: str = "telegram",  
) -> bool:
    """Send approval request."""
    try:
        from agents.a04_payment.config import PAYMENT_CONFIG
 
        ttl = PAYMENT_CONFIG["approval_ttl_seconds"]
        safe_payload = {
            "action":       action,
            "task_id":      task_id,
            "client_id":    client_id,
            "amount":       data.get("amount"),
            "currency":     data.get("currency", "USD"),
            "payer":        data.get("payer"),
            "payment_ref":  data.get("payment_ref"),
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "sender_channel": sender_channel,
        }
 
        secret    = getattr(settings, "approval_hmac_secret", client_id)
        sig       = hmac.new(
            secret.encode(),
            json.dumps(safe_payload, sort_keys=True).encode(),
            hashlib.sha256,
        ).hexdigest()
        safe_payload["sig"] = sig
 
        _redis.setex(
            f"approval:pending:{client_id}:{task_id}",
            ttl,
            json.dumps(safe_payload),
        )
 
        from core.alerting import notify_approver
        return notify_approver(
            client_id=client_id,
            action=action,
            data=data,
            task_id=task_id,
            ttl_seconds=ttl,
        )
 
    except Exception as exc:
        logger.error("send_approval_request failed client=%s: %s", client_id, exc)
        return False

def check_approval_status(client_id: str, task_id: str) -> str:
    """Check approval status."""
    try:
        result_key  = f"approval:result:{client_id}:{task_id}"
        pending_key = f"approval:pending:{client_id}:{task_id}"
 
        raw = _redis.get(result_key)
        if not raw:
            return "pending" if _redis.exists(pending_key) else "expired"
 
        _redis.delete(result_key)
 
        try:
            result_data  = json.loads(raw) # type: ignore
            secret       = getattr(settings, "approval_hmac_secret", client_id)
            received_sig = result_data.pop("sig", "")
            expected_sig = _sign_result_payload(result_data, secret)
 
            if not hmac.compare_digest(received_sig, expected_sig):
                logger.error(
                    "Approval result signature mismatch client=%s task=%s — "
                    "possible tampering; treating as error",
                    client_id, task_id,
                )
                return "error"
 
            status = result_data.get("status", "error")
            if status not in ("approved", "rejected"):
                logger.error(
                    "Unexpected approval status '%s' client=%s task=%s",
                    status, client_id, task_id,
                )
                return "error"
            return status
 
        except json.JSONDecodeError:
            pass  
        value = str(raw).strip().lower()
        if value in ("approved", "rejected"):
            logger.debug(
                "check_approval_status: plain-string result client=%s task=%s "
                "(Telegram callback — no HMAC; upgrade callback to write signed JSON)",
                client_id, task_id,
            )
            return value
 
        logger.error(
            "Unrecognised approval result %r client=%s task=%s", raw, client_id, task_id
        )
        return "error"
 
    except Exception as exc:
        logger.error("check_approval_status failed client=%s: %s", client_id, exc)
        return "error"


def format_payment_confirmation_llm(action: str, data: dict, result: dict | None = None) -> str:
    """Execute format payment confirmation llm."""
    result   = result or {}
    currency = data.get("currency", "USD")
    amount   = data.get("amount")
    try:
        amount_fmt = f"{currency} {float(amount):,.2f}" if amount is not None else "unspecified"
    except (ValueError, TypeError):
        amount_fmt = f"{currency} {amount}" if amount else "unspecified"

    facts: dict = {
        "action": action,
        "payer": data.get("payer") or "unknown",
        "amount": amount_fmt,
        "payment_ref": data.get("payment_ref") or "N/A",
        "payment_method": (data.get("payment_method") or "N/A").replace("_", " "),
    }

    if action == "track_payment":
        match = result.get("match") or {}
        facts.update({
            "duplicate": result.get("status") == "duplicate",
            "matched_invoice": match.get("invoice_number"),
            "requires_review": result.get("requires_review", False),
            "overpayment": result.get("overpayment_amount"),
            "partial_remaining": (
                float(match.get("invoice_amount", 0)) - float(data.get("amount") or 0)
                if result.get("partial_amount") else None
            ),
        })
    elif action == "reconcile":
        facts.update({"invoice_ref": data.get("invoice_ref"),
                      "reconciled": result.get("reconciled", False),
                      "error": result.get("error")})
    elif action == "send_reminder":
        facts.update({"invoice_ref": data.get("invoice_ref"),
                      "sent": result.get("reminder_sent", False),
                      "recipient": result.get("recipient"),
                      "error": result.get("error")})
    elif action == "generate_report":
        report = result.get("report") or result
        facts.update({
            "report_type": report.get("type", "cash_flow"),
            "total_received": report.get("total_received"),
            "total_outstanding": report.get("total_outstanding"),
            "total_invoices": report.get("total_invoices"),
            "overdue_count": report.get("overdue_count"),
            **({"items_count": len(report.get("items", []))} if report.get("type") == "ageing" else {}),
        })
    elif action == "check_payment_status":
        facts.update({"status": result.get("status"),
                      "error": result.get("error"),
                      "last_error": result.get("last_error")})
    elif action in ("refund", "capture_payment", "cancel_payment"):
        facts.update({"success": not result.get("error"),
                      "result_id": result.get("refund_id") or result.get("id"),
                      "result_status": result.get("status"),
                      "error": result.get("error")})
    elif action == "handle_dispute":
        facts.update({"dispute_id": result.get("dispute_id"),
                      "reason": result.get("reason"),
                      "due_by": result.get("due_by"),
                      "has_evidence": result.get("has_evidence", False),
                      "error": result.get("error")})

    try:
        response = _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            system=_PAYMENT_CONFIRMATION_PROMPT,
            messages=[{"role": "user", "content": f"Action completed: {json.dumps(facts, default=str)}"}],
        )
        for block in response.content:
            if block.type == "text":
                return block.text.strip()
    except Exception as exc:
        logger.warning("format_payment_confirmation_llm fallback client: %s", exc)

    return f"Payment {action} completed for {facts['payer']} ({amount_fmt})."