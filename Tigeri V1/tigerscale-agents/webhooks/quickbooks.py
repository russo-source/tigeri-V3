"""Contain quickbooks backend logic."""
from __future__ import annotations
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


def _verify_signature(payload_bytes:bytes, signature: str) -> bool:
    """Execute verify signature."""
    if not signature:
        return False
    try:
        expected = hmac.new(
            settings.quickbooks_webhook_verifier_token.encode(),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(signature, expected)
    except Exception as exc:
        logger.error("QuickBooks signature verification error: %s", exc)
        return False


def _resolve_client(realm_id: str) -> str | None:
    """Resolve client."""
    from config.db_pool import get_conn
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT client_id FROM client_integrations "
                "WHERE provider = 'quickbooks' AND meta->>'realm_id' = %s",
                (realm_id,),
            )
            row = cur.fetchone()
            cur.close()
        return row[0] if row else None
    except Exception as exc:
        logger.error("QB _resolve_client failed realm=%s: %s", realm_id, exc)
        return None


@router.post("/webhooks/quickbooks")
async def quickbooks_webhook(request: Request) -> Response:
    """Execute quickbooks webhook."""
    payload_bytes = await request.body()
    signature     = request.headers.get("intuit-signature", "")

    if not _verify_signature(payload_bytes, signature):
        logger.warning("QuickBooks invalid signature")
        return Response(status_code=401)

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        return Response(status_code=400)

    for notification in payload.get("eventNotifications", []):
        realm_id  = notification.get("realmId", "")
        client_id = _resolve_client(realm_id)
        if not client_id:
            logger.debug("QB event ignored — unknown realm_id=%s", realm_id)
            continue
        for entity in notification.get("dataChangeEvent", {}).get("entities", []):
            _handle_entity(
                client_id=client_id,
                entity_name=entity.get("name", ""),
                operation=entity.get("operation", ""),
                entity_id=entity.get("id", ""),
            )

    return Response(status_code=200)


def _handle_entity(client_id: str, entity_name: str, operation: str, entity_id: str) -> None:
    """Handle entity."""
    try:
        if entity_name == "Invoice" and operation in ("Create", "Update"):
            _sync_invoice(client_id, entity_id)
        elif entity_name == "Payment" and operation == "Create":
            _sync_payment(client_id, entity_id)
        elif entity_name == "Purchase" and operation in ("Create", "Update"):
            _sync_expense(client_id, entity_id)
    except Exception as exc:
        logger.error("QB _handle_entity failed client=%s entity=%s op=%s: %s",
                     client_id, entity_name, operation, exc)


def _sync_invoice(client_id: str, qb_invoice_id: str) -> None:
    """Synchronize invoice."""
    from integrations.quickbooks import QuickBooksIntegration
    from config.db_pool import get_conn
    try:
        qb = QuickBooksIntegration(client_id=client_id)
        invoice = qb.get_invoice(qb_invoice_id)
        balance = float(invoice.get("Balance", 1))
        status = "paid" if balance == 0 else (
            "cancelled" if invoice.get("Status") == "Voided" else "pending"
        )
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE invoices SET status = %s
                WHERE client_id = %s AND external_id = %s
                RETURNING invoice_number, vendor, amount
                """,
                (status, client_id, qb_invoice_id),
            )
            row = cur.fetchone()
            cur.close()
        log_action(client_id, "qb_sync", "invoice_sync", qb_invoice_id,
                   {"status": status}, "success")
        if row:
            notify_client(
                client_id,
                f"Invoice Update: {row[0] or qb_invoice_id} for {row[1] or 'Unknown'} "
                f"is now {status.upper()}" + (f" — Amount: {row[2]}" if row[2] else ""),
            )
    except Exception as exc:
        logger.error("QB _sync_invoice failed client=%s id=%s: %s", client_id, qb_invoice_id, exc)


def _sync_payment(client_id: str, qb_payment_id: str) -> None:
    """Synchronize payment."""
    from config.db_pool import get_conn
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE invoices SET status = 'paid'
                WHERE client_id = %s AND external_id IN (
                    SELECT external_ref FROM payments
                    WHERE client_id = %s AND external_ref = %s
                )
                RETURNING invoice_number, vendor
                """,
                (client_id, client_id, qb_payment_id),
            )
            row = cur.fetchone()
            cur.close()
        log_action(client_id, "qb_sync", "payment_sync", qb_payment_id, {}, "success")
        if row:
            notify_client(
                client_id,
                f"Payment Received: Invoice {row[0] or ''} from {row[1] or 'Unknown'} "
                f"marked PAID on QuickBooks.",
            )
    except Exception as exc:
        logger.error("QB _sync_payment failed client=%s id=%s: %s", client_id, qb_payment_id, exc)


def _sync_expense(client_id: str, qb_purchase_id: str) -> None:
    """Synchronize expense."""
    from integrations.quickbooks import QuickBooksIntegration
    from config.db_pool import get_conn
    import httpx
    try:
        qb   = QuickBooksIntegration(client_id=client_id)
        resp = httpx.get(f"{qb.base}/purchase/{qb_purchase_id}",
                         headers=qb.headers, timeout=10)
        resp.raise_for_status()
        purchase = resp.json().get("Purchase", {})
        if not purchase:
            return

        vendor_name = purchase.get("EntityRef", {}).get("name", "")
        total       = purchase.get("TotalAmt", 0)
        doc_number  = purchase.get("DocNumber", "")

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE expenses
                SET external_id      = %s,
                    approval_status  = 'approved',
                    approved_at      = NOW()
                WHERE client_id = %s
                  AND id = (
                      SELECT id FROM expenses
                      WHERE client_id = %s
                        AND (external_id = %s OR (external_id IS NULL AND reference = %s))
                      ORDER BY
                        CASE WHEN external_id = %s THEN 0 ELSE 1 END,
                        created_at DESC
                      LIMIT 1
                  )
                RETURNING id, vendor, amount, currency
                """,
                (
                    qb_purchase_id,
                    client_id,
                    client_id, qb_purchase_id, doc_number, qb_purchase_id,
                ),
            )
            row = cur.fetchone()
            cur.close()

        log_action(client_id, "qb_sync", "expense_sync", qb_purchase_id,
                   {"vendor": vendor_name, "total": total}, "success")
        if row:
            notify_client(
                client_id,
                f"Expense Synced: {row[1] or vendor_name or 'Unknown'} "
                f"{row[3] or 'USD'} {row[2] or total} confirmed in QuickBooks.",
            )
    except Exception as exc:
        logger.error("QB _sync_expense failed client=%s id=%s: %s", client_id, qb_purchase_id, exc)