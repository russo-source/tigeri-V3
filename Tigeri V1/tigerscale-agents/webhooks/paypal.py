"""Contain paypal backend logic."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import Response

from security.audit import log_action
from webhooks._notify import notify_client

logger = logging.getLogger(__name__)
router = APIRouter()


def _verify_signature(headers: dict, webhook_id: str) -> bool:
    """Execute verify signature."""
    transmission_id  = headers.get("paypal-transmission-id", "")
    transmission_sig = headers.get("paypal-transmission-sig", "")
    return bool(transmission_id and transmission_sig and webhook_id)


@router.post("/webhooks/paypal/{client_id}")
async def paypal_webhook(client_id: str, request: Request) -> Response:
    """Execute paypal webhook."""
    from webhooks.integrations import get_provider_meta
    from security.validator import validate_client_id

    valid, _ = validate_client_id(client_id)
    if not valid:
        return Response(status_code=404)

    payload_bytes = await request.body()
    headers       = dict(request.headers)
    meta          = get_provider_meta(client_id, "paypal")
    webhook_id    = meta.get("webhook_id", "")

    if not _verify_signature(headers, webhook_id):
        logger.warning("PayPal invalid signature client=%s", client_id)
        return Response(status_code=401)

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        return Response(status_code=400)

    event_type = payload.get("event_type", "")
    resource   = payload.get("resource", {})

    _HANDLERS = {
        "PAYMENT.CAPTURE.COMPLETED":  _handle_payment_completed,
        "INVOICING.INVOICE.PAID":     _handle_invoice_paid,
        "PAYMENT.CAPTURE.DENIED":     _handle_payment_denied,
    }
    handler = _HANDLERS.get(event_type)
    if handler:
        try:
            handler(client_id, resource)
        except Exception as exc:
            logger.error("PayPal handler %s failed client=%s: %s",
                         event_type, client_id, exc, exc_info=True)

    return Response(status_code=200)


def _handle_payment_completed(client_id: str, resource: dict) -> None:
    """Handle payment completed."""
    from core.tasks import run_agent_task
    amount      = resource.get("amount", {}).get("value", 0)
    currency    = resource.get("amount", {}).get("currency_code", "USD")
    payment_ref = resource.get("id", "")
    payer       = resource.get("payer", {}).get("name", {})
    payer_name  = f"{payer.get('given_name', '')} {payer.get('surname', '')}".strip() or "PayPal Payment"

    run_agent_task.apply_async(  # type: ignore
        args=[client_id, "payment",
              f"Payment received {currency} {amount} from {payer_name} reference {payment_ref}"],
        queue="high",
    )
    log_action(client_id, "paypal_sync", "payment_completed", payment_ref,
               {"amount": amount, "currency": currency}, "success")


def _handle_invoice_paid(client_id: str, resource: dict) -> None:
    """Handle invoice paid."""
    from core.tasks import run_agent_task
    invoice_id  = resource.get("id", "")
    amount      = resource.get("amount", {}).get("value", 0)
    currency    = resource.get("amount", {}).get("currency_code", "USD")
    recipients  = resource.get("primary_recipients", [{}])
    billing     = recipients[0].get("billing_info", {}).get("name", {}) if recipients else {}
    name        = f"{billing.get('given_name', '')} {billing.get('surname', '')}".strip() or "PayPal Customer"

    run_agent_task.apply_async(  # type: ignore
        args=[client_id, "payment",
              f"Payment received {currency} {amount} from {name} reference {invoice_id}"],
        queue="high",
    )
    log_action(client_id, "paypal_sync", "invoice_paid", invoice_id, {}, "success")


def _handle_payment_denied(client_id: str, resource: dict) -> None:
    """Handle payment denied."""
    from config.db_pool import get_conn
    payment_id = resource.get("id", "")
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE invoices SET status = 'overdue'
                WHERE client_id = %s AND external_id IN (
                    SELECT payment_ref FROM payments
                    WHERE client_id = %s AND payment_ref = %s
                )
                RETURNING invoice_number
                """,
                (client_id, client_id, payment_id),
            )
            row = cur.fetchone()
            cur.close()

        log_action(client_id, "paypal_sync", "payment_denied", payment_id, {}, "error")
        if row:
            notify_client(client_id, f"PayPal payment denied for Invoice {row[0]}. Please review.")
    except Exception as exc:
        logger.error("PayPal _handle_payment_denied failed client=%s id=%s: %s",
                     client_id, payment_id, exc)