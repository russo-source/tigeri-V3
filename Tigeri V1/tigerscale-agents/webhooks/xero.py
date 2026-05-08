"""Contain xero backend logic."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import Response
from config.settings import settings
from security.audit import log_action
from webhooks._notify import notify_client

logger = logging.getLogger(__name__)
router = APIRouter()


def _verify_signature(payload_bytes: bytes, signature: str) -> bool:
    """Execute verify signature."""
    if not signature:
        return False
    try:
        expected = base64.b64encode(
            hmac.new(settings.xero_webhook_key.encode(), payload_bytes, hashlib.sha256).digest()
        ).decode()
        return hmac.compare_digest(signature, expected)
    except Exception as exc:
        logger.error("Xero signature verification error: %s", exc)
        return False

def _resolve_client(tenant_id: str) -> str | None:
    """Resolve client."""
    from config.db_pool import get_conn
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT client_id FROM client_integrations "
                "WHERE provider = 'xero' AND meta->>'tenant_id' = %s",
                (tenant_id,),
            )
            row = cur.fetchone()
            cur.close()
        return row[0] if row else None
    except Exception as exc:
        logger.error("Xero _resolve_client failed tenant=%s: %s", tenant_id, exc)
        return None


@router.post("/webhooks/xero")
async def xero_webhook(request: Request) -> Response:
    """Execute xero webhook."""
    payload_bytes = await request.body()
    signature = request.headers.get("x-xero-signature", "")

    if not _verify_signature(payload_bytes, signature):
        logger.warning("Xero invalid signature")
        return Response(status_code=401)
    
    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        return Response(status_code=400)

    for event in payload.get("events", []):
        _handle_event(
            event_type=event.get("eventType", ""),
            category=event.get("eventCategory", ""),
            tenant_id=event.get("tenantId", ""),
            resource_id=event.get("resourceId", ""),
        )
    return Response(status_code=200)

def _handle_event(event_type: str, category: str, tenant_id: str, resource_id: str) -> None:
    """Handle event."""
    client_id = _resolve_client(tenant_id)
    if not client_id:
        logger.debug("Xero event ignored — unknown tenant_id=%s", tenant_id)
        return
    try:
        if category == "INVOICE" and event_type in ("CREATE", "UPDATE"):
            _sync_invoice(client_id, resource_id)
        elif category == "PAYMENT" and event_type == "CREATE":
            _sync_payment(client_id, resource_id)
        elif category == "RECEIPT" and event_type in ("CREATE", "UPDATE"):
            _sync_expense(client_id, resource_id)
    except Exception as exc:
        logger.error("Xero _handle_event failed client=%s type=%s cat=%s: %s",
                     client_id, event_type, category, exc)


def _sync_invoice(client_id: str, xero_invoice_id: str) -> None:
    """Synchronize invoice."""
    from integrations.xero import XeroIntegration
    from config.db_pool import get_conn
    try:
        xero    = XeroIntegration(client_id=client_id)
        invoice = xero.get_invoice(xero_invoice_id)
        status  = {
            "PAID": "paid", "VOIDED": "cancelled",
            "AUTHORISED": "pending", "DRAFT": "pending",
        }.get(invoice.get("Status", ""), "pending")

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE invoices SET status = %s
                WHERE client_id = %s AND external_id = %s
                RETURNING invoice_number, vendor, amount
                """,
                (status, client_id, xero_invoice_id),
            )
            row = cur.fetchone()
            cur.close()

        log_action(client_id, "xero_sync", "invoice_sync", xero_invoice_id,
                   {"status": status}, "success")
        if row:
            notify_client(
                client_id,
                f"Invoice Update: {row[0] or xero_invoice_id} for {row[1] or 'Unknown'} "
                f"is now {status.upper()}" + (f" — Amount: {row[2]}" if row[2] else ""),
            )
    except Exception as exc:
        logger.error("xero _sync_invoice failed client=%s id=%s: %s", client_id, xero_invoice_id, exc)


def _sync_payment(client_id: str, xero_payment_id: str) -> None:
    """Synchronize payment."""
    from config.db_pool import get_conn
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE invoices SET status = 'paid'
                WHERE client_id = %s AND external_id IN (
                    SELECT meta->>'xero_invoice_id' FROM payments
                    WHERE client_id = %s AND external_ref = %s
                )
                RETURNING invoice_number, vendor
                """,
                (client_id, client_id, xero_payment_id),
            )
            row = cur.fetchone()
            cur.close()

        log_action(client_id, "xero_sync", "payment_sync", xero_payment_id, {}, "success")
        if row:
            notify_client(
                client_id,
                f"Payment Received: Invoice {row[0] or ''} from {row[1] or 'Unknown'} "
                f"marked PAID on Xero.",
            )
    except Exception as exc:
        logger.error("xero _sync_payment failed client=%s id=%s: %s", client_id, xero_payment_id, exc)


def _sync_expense(client_id: str, xero_receipt_id: str) -> None:
    """Synchronize expense."""
    from integrations.xero import XeroIntegration
    from config.db_pool import get_conn
    import httpx
    try:
        xero = XeroIntegration(client_id=client_id)
        resp = httpx.get(f"{xero.BASE_URL}/Receipts/{xero_receipt_id}",
                         headers=xero.headers, timeout=10)
        resp.raise_for_status()
        receipts = resp.json().get("Receipts", [])
        if not receipts:
            return
        receipt         = receipts[0]
        approval_status = "approved" if receipt.get("Status") == "AUTHORISED" else "pending"

        with get_conn() as conn:
            cur = conn.cursor()
            # Safe update: match by external_id OR by most-recent unlinked record for this client
            cur.execute(
                """
                UPDATE expenses
                SET external_id      = %s,
                    approval_status  = %s,
                    approved_at      = CASE WHEN %s = 'approved' THEN NOW() ELSE approved_at END
                WHERE client_id = %s
                  AND id = (
                      SELECT id FROM expenses
                      WHERE client_id = %s
                        AND (external_id = %s OR external_id IS NULL)
                      ORDER BY
                        CASE WHEN external_id = %s THEN 0 ELSE 1 END,
                        created_at DESC
                      LIMIT 1
                  )
                RETURNING id, vendor, amount, currency
                """,
                (
                    xero_receipt_id, approval_status, approval_status,
                    client_id,
                    client_id, xero_receipt_id, xero_receipt_id,
                ),
            )
            row = cur.fetchone()
            cur.close()

        log_action(client_id, "xero_sync", "expense_sync", xero_receipt_id,
                   {"approval_status": approval_status}, "success")
        if row:
            notify_client(
                client_id,
                f"Expense Synced: {row[1] or 'Unknown'} "
                f"{row[3] or 'USD'} {row[2] or ''} is {approval_status.upper()} in Xero.",
            )
    except Exception as exc:
        logger.error("xero _sync_expense failed client=%s id=%s: %s", client_id, xero_receipt_id, exc)