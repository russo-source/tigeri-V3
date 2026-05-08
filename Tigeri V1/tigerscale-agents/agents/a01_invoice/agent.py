"""Contain agent backend logic."""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import date, timezone, datetime

from agents.a01_invoice.config import INVOICE_CONFIG
from agents.a01_invoice.prompts import (
    BILL_AGENT_PROMPT,
    INVOICE_AGENT_PROMPT,
    INVOICE_PDF_EXTRACTION_PROMPT,
    PO_AGENT_PROMPT,
)
from agents.a01_invoice.tools import (
    format_email_body,
    format_invoice_confirmation,
    parse_invoice_message,
    parse_po_message,
    parse_bill_message,
    validate_invoice,
    _parse_json,
    _sanitise_amount,
)

from agents.base_tools import INVOICE_TOOLS
from integrations.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    QuickBooksValidationError,
    XeroValidationError,
    _is_non_retryable,
)
from agents.base_agent import BaseAgent
from config.client_config import get_net_amount
from config.db_pool import get_conn
from core.context_builder import build_context, format_for_llm
from integrations.accounting_factory import get_system_from_config
from memory.agent_memory import recall_memory, save_memory
from memory.rag import retrieve_knowledge
from security.audit import log_action

logger = logging.getLogger(__name__)

# Fallback currency used when invoice payload does not provide one.
_DEFAULT_CURRENCY     = INVOICE_CONFIG["default_currency"]
# Fields that are allowed to be updated on existing invoice records.
_VALID_INVOICE_FIELDS = {"invoice_number", "external_id", "sent_at", "status", "description", "amount"}
# Allowed status filter values for invoice list/query operations.
_VALID_STATUS_FILTERS = {"paid", "pending", "overdue", "partial", "sent", "cancelled", "authorized"}
# Minimum line-item fields required before creating an invoice.
_REQUIRED_LINE_ITEM_FIELDS = {"description"}

# Supported document MIME types for bill image/PDF uploads
_ALLOWED_BILL_DOC_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"
}


def _lookup_po_db(client_id: str, po_number: str = "", vendor: str = "") -> dict:
    """Execute lookup po db."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if po_number:
                cur.execute(
                    "SELECT po_number, external_id, vendor, amount, currency, status "
                    "FROM purchase_orders WHERE client_id=%s AND po_number=%s "
                    "AND status NOT IN ('closed','cancelled') LIMIT 1",
                    (client_id, po_number),
                )
            else:
                cur.execute(
                    "SELECT po_number, external_id, vendor, amount, currency, status "
                    "FROM purchase_orders WHERE client_id=%s AND vendor ILIKE %s "
                    "AND status NOT IN ('closed','cancelled') ORDER BY created_at DESC LIMIT 1",
                    (client_id, f"%{vendor}%"),
                )
            row = cur.fetchone()
            cur.close()
        if row:
            return {"po_number": row[0], "external_id": row[1], "vendor": row[2],
                    "amount": str(row[3]) if row[3] else "N/A",
                    "currency": row[4] or "USD", "status": row[5] or "open"}
        return {}
    except Exception as e:
        logger.error("PO DB lookup failed client=%s: %s", client_id, e)
        return {}


def _parse_xero_date(raw: str) -> str:
    """Parse xero date."""
    import re as _re
    if not raw or raw == "N/A":
        return "N/A"
    match = _re.search(r"/Date\((\d+)", raw)
    if match:
        return datetime.fromtimestamp(int(match.group(1)) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    return raw



def _missing_line_item_fields(data: dict) -> list[str]:
    """Execute missing line item fields."""
    return [f for f in _REQUIRED_LINE_ITEM_FIELDS if not data.get(f)]


def _extract_currency_from_message(message: str) -> str | None:
    lower = (message or "").lower()
    if "inr" in lower or "₹" in message:
        return "INR"
    if "usd" in lower or "$" in message:
        return "USD"
    if "sgd" in lower:
        return "SGD"
    if "eur" in lower or "€" in message:
        return "EUR"
    if "gbp" in lower or "£" in message:
        return "GBP"
    if "aud" in lower:
        return "AUD"
    return None


def _is_currency_confirmation_message(message: str) -> bool:
    lower = (message or "").lower()
    currency = _extract_currency_from_message(message)
    if not currency:
        return False
    return any(
        kw in lower
        for kw in (
            "yes", "ok", "okay", "use", "in", "confirm", "proceed",
            "yes use", "okay use", "create invoice in",
        )
    )


def _make_idempotency_key(client_id: str, data: dict) -> str:
    source = (
        f"{client_id}:"
        f"{(data.get('vendor') or '').lower().strip()}:"
        f"{data.get('amount', '')}:"
        f"{(data.get('description') or '').lower().strip()[:50]}:"
        f"{uuid.uuid4().hex}"
    )
    return hashlib.sha256(source.encode()).hexdigest()


def _extract_bill_file_from_task(task: dict) -> tuple[bytes, str]:
    """
    Pull raw file bytes + mime_type from a task for bill document processing.
    Handles both image and PDF types.
    Returns (file_bytes, mime_type) or (b"", "").
    """
    file_bytes = task.get("file_bytes") or b""
    mime_type  = task.get("mime_type", "")

    if not file_bytes or mime_type not in _ALLOWED_BILL_DOC_TYPES:
        return b"", ""

    if mime_type == "application/pdf":
        try:
            from channels.file_processor import _extract_pdf
            text = _extract_pdf(file_bytes)
            if text and len(text.strip()) > 100:
                task["_pdf_text"] = text
                return b"", "text/plain"
        except Exception as exc:
            logger.warning("Bill PDF docling extraction failed: %s", exc)
        try:
            from agents.utils.document_extractor import pdf_to_image_bytes
            file_bytes, mime_type = pdf_to_image_bytes(file_bytes)
        except Exception as exc:
            logger.warning("Bill PDF-image failed client: %s", exc)
            return b"", ""

    return file_bytes, mime_type

class InvoiceAgent(BaseAgent):
    """Represent the InvoiceAgent component and its related behavior."""

    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        super().__init__(client_id)
        self.confidence_threshold = INVOICE_CONFIG["confidence_threshold"]
        self._accounting_cb = CircuitBreaker(f"accounting:{client_id}")

    def get_system_prompt(self) -> str:
        """Return system prompt."""
        return INVOICE_AGENT_PROMPT

    def get_tools(self) -> list[dict]:
        return INVOICE_TOOLS

    def execute_tool(self, tool_name: str, tool_input: dict) -> dict:
        meta = {
            "_sender":    tool_input.pop("_sender", ""),
            "_channel":   tool_input.pop("_channel", "telegram"),
            "_client_id": tool_input.pop("_client_id", self.client_id),
            "_task_id":   tool_input.pop("_task_id", ""),
        }

        dispatch = {
            "create_invoice":   self._tool_create_invoice,
            "send_invoice":     self._tool_send_invoice,
            "list_invoices":    self._tool_list_invoices,
            "check_overdue":    self._tool_check_overdue,
            "track_invoice":    self._tool_track_invoice,
            "approve_invoice":  self._tool_approve_invoice,
            "edit_invoice":     self._tool_edit_invoice,
            "mark_invoice_paid": self._tool_mark_paid,
            "send_reminder":    self._tool_send_reminder,
            "create_bill":      self._tool_create_bill,
            "list_bills":       self._tool_list_bills,
            "create_po":        self._tool_create_po,
            "list_pos":         self._tool_list_pos,
        }

        handler = dispatch.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            return handler(tool_input, meta)
        except Exception as exc:
            logger.error("execute_tool %s failed client=%s: %s", tool_name, self.client_id, exc)
            return {"error": str(exc)}

    def _tool_create_invoice(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":          "create",
            "vendor":          inp.get("vendor"),
            "amount":          inp.get("amount"),
            "currency":        inp.get("currency", _DEFAULT_CURRENCY),
            "description":     inp.get("description", "Invoice"),
            "due_date":        inp.get("due_date"),
            "recipient_email": inp.get("recipient_email"),
            "invoice_number":  inp.get("invoice_number"),
            "confidence":      0.95,
            "_sender":         meta.get("_sender", ""),
            "_channel":        meta.get("_channel", ""),
            "_client_id":      self.client_id,
        }
        data["idempotency_key"] = _make_idempotency_key(self.client_id, data)
        result = self._action_create(data)
        result["action"] = "create"
        return result

    def _tool_send_invoice(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":          "send",
            "invoice_number":  inp.get("invoice_number"),
            "vendor":          inp.get("vendor"),
            "recipient_email": inp.get("recipient_email"),
            "idempotency_key": hashlib.sha256(
                f"{self.client_id}:send:{inp.get('invoice_number')}".encode()
            ).hexdigest(),
            "_sender":    meta.get("_sender", ""),
            "_channel":   meta.get("_channel", ""),
            "_client_id": self.client_id,
        }
        result = self._action_send(data)
        result["action"] = "send"
        return result

    def _tool_list_invoices(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":        "list_invoices",
            "status_filter": inp.get("status_filter"),
            "vendor_filter": inp.get("vendor_filter"),
        }
        result = self._action_list_invoices(data)
        result["action"] = "list_invoices"
        return result

    def _tool_check_overdue(self, inp: dict, meta: dict) -> dict:
        result = self._action_check_overdue({})
        result["action"] = "check_overdue"
        return result

    def _tool_track_invoice(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":         "track",
            "invoice_number": inp.get("invoice_number"),
            "vendor":         inp.get("vendor"),
        }
        result = self._action_track(data)
        result["action"] = "track"
        return result

    def _tool_approve_invoice(self, inp: dict, meta: dict) -> dict:
        if inp.get("approve_all"):
            result = self._action_approve_all({})
            result["action"] = "approve_all"
            return result
        data = {
            "action":         "approve",
            "invoice_number": inp.get("invoice_number"),
            "vendor":         inp.get("vendor"),
            "_sender":        meta.get("_sender", ""),
            "_client_id":     self.client_id,
        }
        result = self._action_approve(data)
        result["action"] = "approve"
        return result

    def _tool_edit_invoice(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":         "edit",
            "invoice_number": inp.get("invoice_number"),
            "vendor":         inp.get("vendor"),
            "edit_fields":    inp.get("edit_fields", {}),
            "_sender":        meta.get("_sender", ""),
            "_client_id":     self.client_id,
        }
        result = self._action_edit(data)
        result["action"] = "edit"
        return result

    def _tool_mark_paid(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":         "mark_paid",
            "invoice_number": inp.get("invoice_number"),
            "vendor":         inp.get("vendor"),
        }
        result = self._action_mark_paid(data)
        result["action"] = "mark_paid"
        return result

    def _tool_send_reminder(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":          "remind",
            "invoice_number":  inp.get("invoice_number"),
            "vendor":          inp.get("vendor"),
            "recipient_email": inp.get("recipient_email"),
        }
        result = self._action_remind(data)
        result["action"] = "remind"
        return result

    def _tool_create_bill(self, inp: dict, meta: dict) -> dict:
        bill_agent = BillAgent(self.client_id)
        data = {
            "vendor":         inp.get("vendor"),
            "amount":         inp.get("amount"),
            "currency":       inp.get("currency", _DEFAULT_CURRENCY),
            "description":    inp.get("description"),
            "invoice_number": inp.get("invoice_number"),
            "due_date":       inp.get("due_date"),
            "confidence":     0.95,
            "_client_id":     self.client_id,
            "action":         "create",
        }
        result = bill_agent._create_bill(data, "tool:create_bill", meta.get("_channel", ""), meta.get("_sender", ""))
        result["action"] = "create_bill"
        return result

    def _tool_list_bills(self, inp: dict, meta: dict) -> dict:
        bill_agent = BillAgent(self.client_id)
        data = {
            "status_filter": inp.get("status_filter"),
            "vendor_filter": inp.get("vendor_filter"),
        }
        result = bill_agent._list_bills(data)
        result["action"] = "list_bills"
        return result

    def _tool_create_po(self, inp: dict, meta: dict) -> dict:
        po_agent = POAgent(self.client_id)
        data = {
            "action":         "create",
            "vendor":         inp.get("vendor"),
            "amount":         inp.get("amount"),
            "currency":       inp.get("currency", _DEFAULT_CURRENCY),
            "description":    inp.get("description"),
            "quantity":       inp.get("quantity"),
            "unit_price":     inp.get("unit_price"),
            "delivery_date":  inp.get("delivery_date"),
            "confidence":     0.95,
            "_client_id":     self.client_id,
        }
        result = po_agent._create_po(data, "tool:create_po")
        result["action"] = "create_po"
        return result

    def _tool_list_pos(self, inp: dict, meta: dict) -> dict:
        po_agent = POAgent(self.client_id)
        data = {
            "status_filter": inp.get("status_filter"),
            "vendor_filter": inp.get("vendor_filter"),
        }
        result = po_agent._list_pos(data)
        result["action"] = "list_pos"
        return result

    def _run(self, task: dict) -> dict:
        """Run the requested operation."""
        message = task.get("message", "")
        is_document = task.get("is_document", False)
        sender = task.get("sender", "")

        ctx_str = ""
        try:
            from core.conversation import _build_enriched_message, _get_context
            ctx_turns = _get_context(sender, self.client_id)
            ctx_str = _build_enriched_message(
                message, ctx_turns,
                sender=sender,
                client_id=self.client_id,
                domain="invoice",
            )
        except Exception:
            pass

        try:
            data = parse_invoice_message(message, is_document=is_document, context=ctx_str)
        except Exception as exc:
            logger.error("parse_invoice_message failed client=%s: %s", self.client_id, exc)
            result = {"status": "error", "message": "Something went wrong reading your request — please try again."}
            log_action(self.client_id, "a01_invoice", "invoice", message, result, "error",
                    message="parse_invoice_message raised")
            return result

        explicit_currency = _extract_currency_from_message(message)
        if explicit_currency and not data.get("currency"):
            data["currency"] = explicit_currency

        is_valid, reason = validate_invoice(data)
        if not is_valid:
            if reason.startswith("__needs_info__:"):
                missing = reason.replace("__needs_info__:", "").strip()
                message_text = (
                    missing if missing.startswith("I couldn't")
                    else f"To create the invoice, please provide: {missing}"
                )
                result = {"status": "needs_info", "message": message_text}
                log_action(self.client_id, "a01_invoice", "invoice", message, result, "needs_info",
                        message=f"Validation: {missing}")
                return result
            result = {"status": "error", "message": reason}
            log_action(self.client_id, "a01_invoice", "invoice", message, result, "error",
                    message=f"Validation failed — {reason}")
            return result

        action = data.get("action", "create")
        vendor = data.get("vendor", "")

        memory = recall_memory(self.client_id, "a01_invoice", message)
        knowledge = retrieve_knowledge(self.client_id, message, "invoice")
        context = build_context(
            task=message, memory=memory, knowledge=knowledge,
            client_id=self.client_id, entity=vendor,
        )

        try:
            raw = self.call_llm(task=format_for_llm(context), intent="invoice")
            llm_data = self.parse_llm_json(raw)
        except json.JSONDecodeError:
            result = {"status": "error", "message": "Could not parse invoice data — please try again."}
            log_action(self.client_id, "a01_invoice", "invoice", message, result, "error",
                    message="LLM parse failed")
            return result
        except Exception as exc:
            logger.error("LLM call failed client=%s: %s", self.client_id, exc)
            result = {"status": "error", "message": "Request processing failed — please try again."}
            log_action(self.client_id, "a01_invoice", "invoice", message, result, "error",
                    message=f"LLM call failed — {exc}")
            return result

        NEVER_OVERRIDE = {"amount", "vendor", "currency", "invoice_number", "action"}
        for key, value in llm_data.items():
            if key not in NEVER_OVERRIDE and not data.get(key):
                data[key] = value

        data["idempotency_key"] = _make_idempotency_key(self.client_id, data)

        confidence = float(data.get("confidence", 0.0))

        if confidence < self.confidence_threshold:
            result = {
                "status": "escalate",
                "message": "Need more details — vendor name and amount at minimum.",
                "raw": data,
            }
            log_action(self.client_id, "a01_invoice", "invoice", message, result, "escalate",
                    message=f"Low confidence ({confidence:.2f})")
            return result

        action = data.get("action", "create")

        if action == "create":
            missing = _missing_line_item_fields(data)
            if missing:
                result = {"status": "needs_info",
                        "message": f"Need the {', '.join(missing)} to create the invoice."}
                log_action(self.client_id, "a01_invoice", "invoice", message, result, "needs_info",
                        message=f"Missing line-item fields: {', '.join(missing)}")
                return result

            user_confirmed_currency = _is_currency_confirmation_message(message)
            if not user_confirmed_currency:
                mismatch = self._check_currency_mismatch(data)
                if mismatch:
                    result = {"status": "needs_info", "message": mismatch}
                    log_action(self.client_id, "a01_invoice", "invoice", message,
                            result, "needs_info", message="Currency mismatch")
                    return result

        data["_sender"] = task.get("sender", "")
        data["_channel"] = task.get("channel", "")
        data["_client_id"] = self.client_id
        result_data = self._execute_action(action, data)

        if result_data.get("error"):
            result = {"status": "error",
                    "message": f"Could not complete {action}: {result_data['error']}"}
            log_action(self.client_id, "a01_invoice", "invoice", message, result, "error",
                    message=f"{action} failed — {result_data['error']}")
            return result

        if action == "create":
            accounting = result_data.get("accounting", {})
            data["invoice_number"] = (
                accounting.get("InvoiceNumber") or accounting.get("DocNumber") or
                data.get("invoice_number") or "Pending sync"
            )
            data["due_date"] = data.get("due_date") or "Not set"

        if vendor and action in ("create", "send", "mark_paid"):
            self.record_entity(
                entity_name=vendor,
                domain="invoice",
                amount=float(data.get("amount") or 0),
                currency=data.get("currency", _DEFAULT_CURRENCY),
            )

        confirmation = format_invoice_confirmation(action, data, result_data)

        try:
            save_memory(
                self.client_id, "a01_invoice",
                f"Invoice {action} for {vendor} amount {data.get('amount')} "
                f"{data.get('currency', _DEFAULT_CURRENCY)}",
            )
        except Exception as exc:
            logger.warning("save_memory non-fatal client=%s: %s", self.client_id, exc)

        result = {
            "status": "success",
            "message": confirmation,
            "action": action,
            "invoice": data,
            "result": result_data,
        }
        log_action(
            self.client_id, "a01_invoice", "invoice", message, result, "success",
            message=f"Invoice {action} for {vendor} — {data.get('currency', 'USD')} {data.get('amount')}",
        )
        return result

    def _post_to_accounting(self, data: dict) -> dict:
        def _create_with_retry() -> dict:
            last_exc: Exception | None = None
            for attempt, delay in enumerate([0.5, 1, 2], start=1):
                try:
                    return get_system_from_config(self.client_id).create_invoice(data)
                except CircuitOpenError:
                    raise
                except Exception as exc:
                    try:
                        if _is_non_retryable(exc):
                            raise
                    except (XeroValidationError, QuickBooksValidationError):
                        raise
                    except Exception:
                        raise
                    last_exc = exc
                    if attempt < 3:
                        time.sleep(delay)
            raise last_exc  # type: ignore

        try:
            return self._accounting_cb.call(_create_with_retry)
        except CircuitOpenError:
            raise
        except Exception as last_exc:
            from core.tasks import retry_accounting_post
            retry_accounting_post.apply_async( # type: ignore
                args=[self.client_id, data],
                kwargs={"sender": data.get("_sender", ""), "channel": data.get("_channel", "")},
                countdown=60, queue="low",
            )
            return {"error": str(last_exc), "queued_for_retry": True}

    def _save_to_db(self, data: dict) -> bool:
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO invoices "
                    "(client_id, vendor, amount, currency, invoice_number, "
                    "due_date, status, idempotency_key, raw_message, description, line_items) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (idempotency_key) DO NOTHING RETURNING id",
                    (
                        self.client_id, data.get("vendor"), data.get("amount"),
                        data.get("currency", _DEFAULT_CURRENCY),
                        data.get("invoice_number"), data.get("due_date"),
                        "pending", data.get("idempotency_key"), json.dumps(data),
                        data.get("description"),
                        json.dumps(data.get("line_items") or []),
                    ),
                )
                row = cur.fetchone()
                cur.close()
            return row is not None
        except Exception as exc:
            logger.error("Invoice DB save failed client=%s: %s", self.client_id, exc)
            return False

    def _check_currency_mismatch(self, data: dict) -> str | None:
        invoice_currency = (data.get("currency") or "USD").upper()
        try:
            org_currency = get_system_from_config(self.client_id).get_organisation_currency().upper()
        except Exception:
            return None

        po_currency = None
        if data.get("po_number"):
            try:
                with get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT currency FROM purchase_orders "
                        "WHERE client_id=%s AND po_number=%s LIMIT 1",
                        (self.client_id, data["po_number"]),
                    )
                    row = cur.fetchone()
                    cur.close()
                if row:
                    po_currency = (row[0] or "USD").upper()
            except Exception:
                pass

        mismatches = []
        if invoice_currency != org_currency:
            mismatches.append(
                f"invoice currency {invoice_currency} differs from your "
                f"accounting platform currency {org_currency}"
            )
        if po_currency and invoice_currency != po_currency:
            mismatches.append(
                f"invoice currency {invoice_currency} differs from PO currency {po_currency}"
            )

        if mismatches:
            return (
                f"Currency mismatch detected: {' and '.join(mismatches)}. "
                f"Reply with the currency you want to use, e.g. "
                f"'create invoice in {org_currency}' or 'yes use {invoice_currency}'."
            )
        return None

    def _execute_action(self, action: str, data: dict) -> dict:
        handler = getattr(self, f"_action_{action}", None)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        return handler(data)
    
    def _action_create(self, data: dict) -> dict:
        if not data.get("description"):
            data["description"] = "Invoice"

        if not data.get("currency"):
            try:
                data["currency"] = get_system_from_config(self.client_id).get_organisation_currency()
            except Exception:
                data["currency"] = _DEFAULT_CURRENCY

        saved = self._save_to_db(data)
        if not saved:
            return {"status": "duplicate"}

        try:
            accounting_result = self._post_to_accounting(data)
        except CircuitOpenError as exc:
            return {"error": str(exc)}

        xero_invoice_number = accounting_result.get("InvoiceNumber") or accounting_result.get("DocNumber")
        xero_invoice_id     = accounting_result.get("InvoiceID") or accounting_result.get("Id")
        ik = data.get("idempotency_key")

        if xero_invoice_id and not xero_invoice_number:
            try:
                import time as _time
                _time.sleep(1)
                fetched = get_system_from_config(self.client_id).get_invoice(xero_invoice_id)
                xero_invoice_number = (
                    fetched.get("DocNumber") or fetched.get("InvoiceNumber") or fetched.get("InvoiceID")
                )
            except Exception as exc:
                logger.warning("Invoice number re-fetch failed client=%s: %s", self.client_id, exc)

        if ik and xero_invoice_number:
            self._update_invoice_field(ik, "invoice_number", xero_invoice_number)
        if ik and xero_invoice_id:
            self._update_invoice_field(ik, "external_id", xero_invoice_id)
        if ik and xero_invoice_id:   
            self._update_invoice_field(ik, "status", "pending")

        xero_total = (
            accounting_result.get("TotalAmt") or
            accounting_result.get("Total") or
            accounting_result.get("TotalAmount")
        )
        if xero_total:
            data["amount"] = xero_total

        pdf_bytes = None
        if xero_invoice_id:
            try:
                pdf_bytes = get_system_from_config(self.client_id).get_invoice_pdf(xero_invoice_id)
            except Exception as exc:
                logger.warning("Invoice PDF fetch failed client=%s: %s", self.client_id, exc)

        result = {"saved": True, "accounting": accounting_result, "pdf": pdf_bytes}
        if data.get("recipient_email") and not accounting_result.get("error"):
            try:
                data["invoice_number"] = xero_invoice_number or data.get("invoice_number")
                data["external_id"] = xero_invoice_id
                send_result = self._action_send(data)
                result["email_sent"] = send_result.get("email_sent", False)
                result["email_error"] = send_result.get("email_error")
            except Exception as exc:
                logger.warning("Auto-send after create failed client=%s: %s", self.client_id, exc)
                result["email_error"] = str(exc)

        return result
    
    def _action_send(self, data: dict) -> dict:
        from integrations.email_factory import get_email_from_config
        accounting      = get_system_from_config(self.client_id)
        results: dict   = {}
        idempotency_key = data.get("idempotency_key")
        external_id     = None

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, external_id, vendor, amount, currency, due_date FROM invoices "
                    "WHERE client_id=%s AND (idempotency_key=%s OR invoice_number=%s) "
                    "ORDER BY created_at DESC LIMIT 1",
                    (self.client_id, idempotency_key, data.get("invoice_number")),
                )
                row = cur.fetchone()
                cur.close()
            if row:
                external_id = row[1]
                data["vendor"]   = data.get("vendor")   or row[2]
                data["amount"]   = data.get("amount")   or row[3]
                data["currency"] = data.get("currency") or row[4]
                if not data.get("due_date") and row[5]:
                    data["due_date"] = str(row[5])
        except Exception as exc:
            logger.error("DB invoice lookup failed client=%s: %s", self.client_id, exc)

        if not external_id and data.get("invoice_number"):
            try:
                inv = accounting.find_invoice_by_number(data["invoice_number"])
                if inv:
                    external_id = inv.get("InvoiceID") or inv.get("Id")
                    results["accounting"] = inv
                    if external_id and idempotency_key:
                        self._update_invoice_field(idempotency_key, "external_id", external_id)
            except Exception as exc:
                logger.error("Accounting invoice lookup failed client=%s: %s", self.client_id, exc)
                results["accounting_error"] = str(exc)

        if not external_id:
            missing = _missing_line_item_fields(data)
            if missing:
                return {"error": f"Cannot create invoice — missing: {', '.join(missing)}"}
            try:
                invoice     = accounting.create_invoice(data)
                external_id = invoice.get("InvoiceID") or invoice.get("Id")
                results["accounting"] = invoice
                if external_id and idempotency_key:
                    self._update_invoice_field(idempotency_key, "external_id", external_id)
            except Exception as exc:
                logger.error("Accounting create failed client=%s: %s", self.client_id, exc)
                results["accounting_error"] = str(exc)
                return results

        pdf_bytes = None
        if external_id:
            for attempt in range(3):
                try:
                    import time as _time
                    if attempt > 0:
                        _time.sleep(2)
                    pdf_bytes = accounting.get_invoice_pdf(external_id)
                    if pdf_bytes:
                        results["pdf"] = pdf_bytes
                        break
                except Exception as exc:
                    logger.warning("Invoice PDF fetch attempt %d failed client=%s: %s",
                                   attempt + 1, self.client_id, exc)

        recipient = data.get("recipient_email")
        if recipient:
            try:
                inv_num = data.get("invoice_number", "")
                vendor = data.get("vendor", "")
                email = get_email_from_config(self.client_id)
                plain_body, html_body = format_email_body(data, pdf_attached=bool(pdf_bytes))
                attachment_name = f"{inv_num or 'invoice'}.pdf" if pdf_bytes else ""
                sent = email.send(
                    recipient=recipient,
                    subject=f"Invoice {inv_num} — {vendor}",
                    body=plain_body,
                    html=html_body,
                    attachment=pdf_bytes if pdf_bytes else b"",
                    attachment_name=attachment_name,
                )
                if sent and idempotency_key:
                    self._update_invoice_field(idempotency_key, "sent_at", "NOW()")
                results["email_sent"] = sent
                results["pdf_attached"] = bool(pdf_bytes)
            except ValueError as e:
                results["email_sent"] = False
                results["email_error"] = "not_connected"
            except Exception as e:
                logger.error("Email send failed client=%s: %s", self.client_id, e)
                results["email_sent"] = False
                results["email_error"] = str(e)

        return results

    def _action_track(self, data: dict) -> dict:
        """Execute action track."""
        invoice_number = data.get("invoice_number")
        vendor = data.get("vendor")
        if not invoice_number and not vendor:
            return {"error": "Invoice number or vendor required for tracking"}

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                if invoice_number:
                    cur.execute(
                        "SELECT id, status, amount, due_date, sent_at, reminder_count, external_id "
                        "FROM invoices WHERE client_id=%s AND invoice_number=%s "
                        "ORDER BY created_at DESC LIMIT 1",
                        (self.client_id, invoice_number),
                    )
                else:
                    cur.execute(
                        "SELECT id, status, amount, due_date, sent_at, reminder_count, external_id "
                        "FROM invoices WHERE client_id=%s AND vendor ILIKE %s "
                        "ORDER BY created_at DESC LIMIT 1",
                        (self.client_id, f"%{vendor}%"),
                    )
                row = cur.fetchone()
                cur.close()

            if row:
                return {"id": row[0], "status": row[1], "amount": str(row[2]),
                        "due_date": str(row[3]), "sent_at": str(row[4]), "reminder_count": row[5]}

            if invoice_number:
                try:
                    xero_inv = get_system_from_config(self.client_id).find_invoice_by_number(invoice_number)
                    if xero_inv:
                        return {
                            "status": xero_inv.get("Status"),
                            "amount": str(xero_inv.get("AmountDue")),
                            "due_date": _parse_xero_date(str(xero_inv.get("DueDate", "N/A"))),
                            "sent_at": "N/A",
                            "reminder_count": 0,
                        }
                except Exception as e:
                    logger.error("Accounting track fallback failed client=%s: %s", self.client_id, e)

            return {"error": f"Invoice {invoice_number or vendor} not found"}

        except Exception as e:
            logger.error("Track invoice failed client=%s: %s", self.client_id, e)
            return {"error": str(e)}

    def _action_remind(self, data: dict) -> dict:
        """Execute action remind."""
        invoice_number = data.get("invoice_number")
        vendor = data.get("vendor")
        recipient = data.get("recipient_email")
        amount = data.get("amount", "")
        currency = data.get("currency", "USD")
        due_date = "N/A"
        contact_name = ""
        external_id = None

        if not invoice_number and vendor:
            try:
                with get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT invoice_number, amount, currency, due_date, raw_message, external_id "
                        "FROM invoices WHERE client_id=%s AND vendor ILIKE %s "
                        "AND status NOT IN ('paid','cancelled') ORDER BY created_at DESC LIMIT 1",
                        (self.client_id, f"%{vendor}%"),
                    )
                    row = cur.fetchone()
                    cur.close()
                if row:
                    invoice_number = row[0];
                    amount = row[1];
                    currency = row[2]
                    due_date = str(row[3]) if row[3] else "N/A"
                    raw = json.loads(row[4]) if row[4] else {}
                    recipient = recipient or raw.get("recipient_email")
                    external_id = row[5];
                    contact_name = vendor
            except Exception as e:
                logger.error("Vendor lookup for reminder failed client=%s: %s", self.client_id, e)

        if not invoice_number:
            return {"error": f"No outstanding invoice found for '{vendor or 'unknown'}'"}

        if invoice_number and not external_id:
            try:
                with get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT external_id, amount, currency, due_date FROM invoices "
                        "WHERE client_id=%s AND invoice_number=%s LIMIT 1",
                        (self.client_id, invoice_number),
                    )
                    row = cur.fetchone()
                    cur.close()
                if row:
                    external_id = row[0];
                    amount = amount or row[1]
                    currency = currency or row[2]
                    due_date = str(row[3]) if row[3] else due_date
            except Exception as e:
                logger.error("Invoice lookup for reminder failed client=%s: %s", self.client_id, e)

        accounting = get_system_from_config(self.client_id)
        if not recipient:
            try:
                xero_inv = accounting.find_invoice_by_number(invoice_number)
                contact_id = xero_inv.get("Contact", {}).get("ContactID")
                contact_name = xero_inv.get("Contact", {}).get("Name", contact_name)
                if contact_id:
                    recipient = accounting.get_contact_email(contact_id)
                external_id = external_id or xero_inv.get("InvoiceID")
                amount = xero_inv.get("AmountDue", amount)
                currency = xero_inv.get("CurrencyCode", currency)
                due_date = _parse_xero_date(str(xero_inv.get("DueDate", "N/A")))
            except Exception as e:
                logger.error("Accounting email lookup failed client=%s: %s", self.client_id, e)

        if not recipient:
            return {"error": "Could not find recipient email — please provide it or add it to the invoice"}

        pdf_bytes = None
        if external_id:
            try:
                pdf_bytes = accounting.get_invoice_pdf(external_id)
            except Exception as e:
                logger.warning("Reminder PDF fetch failed client=%s: %s", self.client_id, e)

        try:
            from integrations.email_factory import get_email_from_config
            today = date.today().strftime("%B %d, %Y")
            name = contact_name or vendor or "Valued Customer"
            plain = (
                f"Dear {name},\n\nThis is a friendly reminder that the following invoice is outstanding:\n\n"
                f"  Invoice Number : {invoice_number}\n"
                f"  Amount Due     : {currency} {amount}\n"
                f"  Due Date       : {due_date}\n\n"
                f"Please arrange payment at your earliest convenience.\n"
                f"If you have already made this payment, please disregard this notice.\n\n"
                f"Kind regards,\nAccounts Team"
            )
            html = (
                f'<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto;">'
                f'<div style="background:#f4f4f4;padding:20px;border-radius:8px;">'
                f'<h2 style="color:#d9534f;">Payment Reminder</h2>'
                f'<p>Dear <strong>{name}</strong>,</p>'
                f'<table style="width:100%;border-collapse:collapse;margin:20px 0;">'
                f'<tr><td style="padding:10px;font-weight:bold;">Invoice Number</td><td>{invoice_number}</td></tr>'
                f'<tr><td style="padding:10px;font-weight:bold;">Amount Due</td>'
                f'<td style="color:#d9534f;font-size:18px;"><strong>{currency} {amount}</strong></td></tr>'
                f'<tr><td style="padding:10px;font-weight:bold;">Due Date</td><td>{due_date}</td></tr>'
                f'<tr><td style="padding:10px;font-weight:bold;">Date Issued</td><td>{today}</td></tr>'
                f'</table></div></body></html>'
            )
            email = get_email_from_config(self.client_id)
            sent = email.send(
                recipient=recipient,
                subject=f"Payment Reminder — Invoice {invoice_number} ({currency} {amount} due {due_date})",
                body=plain,
                html=html,
                attachment=pdf_bytes or b"",
                attachment_name=f"{invoice_number}.pdf" if pdf_bytes else "",
            )
            if sent and invoice_number:
                self._increment_reminder_count(invoice_number)
            return {"reminder_sent": sent, "recipient": recipient}
        except Exception as e:
            logger.error("Reminder email failed client=%s: %s", self.client_id, e)
            return {"error": str(e)}

    def _action_mark_paid(self, data: dict) -> dict:
        invoice_number = data.get("invoice_number")
        vendor = data.get("vendor")

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                if invoice_number:
                    cur.execute(
                        "UPDATE invoices SET status='paid' WHERE id=("
                        "SELECT id FROM invoices WHERE client_id=%s AND invoice_number=%s "
                        "ORDER BY created_at DESC LIMIT 1) "
                        "RETURNING id, external_id, amount, vendor, due_date, currency",
                        (self.client_id, invoice_number),
                    )
                elif vendor:
                    cur.execute(
                        "UPDATE invoices SET status='paid' WHERE id=("
                        "SELECT id FROM invoices WHERE client_id=%s AND vendor ILIKE %s "
                        "AND status NOT IN ('paid','cancelled') ORDER BY created_at DESC LIMIT 1) "
                        "RETURNING id, external_id, amount, vendor, due_date, currency",
                        (self.client_id, f"%{vendor}%"),
                    )
                else:
                    return {"error": "Please provide an invoice number or vendor name to mark as paid"}
                row = cur.fetchone()
                cur.close()

            if not row:
                with get_conn() as conn:
                    cur = conn.cursor()
                    if invoice_number:
                        cur.execute(
                            "SELECT status FROM invoices WHERE client_id=%s AND invoice_number=%s LIMIT 1",
                            (self.client_id, invoice_number),
                        )
                    else:
                        cur.execute(
                            "SELECT status FROM invoices WHERE client_id=%s AND vendor ILIKE %s "
                            "ORDER BY created_at DESC LIMIT 1",
                            (self.client_id, f"%{vendor}%"),
                        )
                    existing = cur.fetchone()
                    cur.close()

                if existing and existing[0] == "paid":
                    return {"marked_paid": True, "already_paid": True}
                return {"error": f"No invoice found for '{invoice_number or vendor}'."}

            db_id, external_id, amount, db_vendor, db_due_date, db_currency = row

            data["vendor"]   = data.get("vendor")   or db_vendor
            data["amount"]   = data.get("amount")   or (float(amount) if amount else None)
            data["currency"] = data.get("currency") or db_currency or _DEFAULT_CURRENCY
            if not data.get("due_date") and db_due_date:
                data["due_date"] = str(db_due_date)

            import re as _re
            is_valid_qb_id = external_id and bool(_re.match(r'^\d+$', str(external_id)))

            if not is_valid_qb_id:
                return {"marked_paid": True, "invoice_id": db_id,
                        "accounting_warning": "Marked paid locally — will sync to QB on next retry."}

            actual_paid_amount = None
            if external_id:
                try:
                    actual_paid_amount = get_system_from_config(self.client_id).mark_invoice_paid(
                        external_id,
                        float(amount) if amount else 0.0,
                        date.today().strftime("%Y-%m-%d"),
                    )
                except Exception as exc:
                    error_str = str(exc).lower()
                    try:
                        if _is_non_retryable(exc):
                            raise
                    except (XeroValidationError, QuickBooksValidationError):
                        try:
                            with get_conn() as conn:
                                cur = conn.cursor()
                                cur.execute("UPDATE invoices SET status='pending' WHERE id=%s", (db_id,))
                                cur.close()
                        except Exception:
                            pass
                        if "payments you entered add up to more" in error_str:
                            return {"error": f"Invoice for {db_vendor} may already be paid in QB."}
                        if "inactive" in error_str or "object not found" in error_str:
                            return {"error": f"Invoice for {db_vendor} not found in QB — recreate and retry."}
                        if "unauthorized" in error_str or "403" in error_str:
                            return {"error": "QB connection expired. Reconnect in Settings → Integrations."}
                        return {"error": f"QB rejected the payment for {db_vendor}."}
                    except Exception:
                        try:
                            with get_conn() as conn:
                                cur = conn.cursor()
                                cur.execute("UPDATE invoices SET status='pending' WHERE id=%s", (db_id,))
                                cur.close()
                        except Exception:
                            pass
                        return {"error": f"QB rejected the payment for {db_vendor}."}
                    return {"marked_paid": True, "invoice_id": db_id,
                            "accounting_warning": "Marked paid locally — QB sync failed and will retry."}
            if actual_paid_amount is not None:
                data["amount"] = actual_paid_amount
            return {"marked_paid": True, "invoice_id": db_id}

        except Exception as e:
            logger.error("Mark paid failed client=%s: %s", self.client_id, e)
            return {"error": str(e)}

    def _action_list_invoices(self, data: dict) -> dict:
        status_filter = data.get("status_filter")
        vendor_filter = data.get("vendor_filter")
        if status_filter and status_filter not in _VALID_STATUS_FILTERS:
            return {"error": f"Invalid status filter '{status_filter}'"}
        try:
            live = get_system_from_config(self.client_id).list_invoices(
                status_filter=status_filter or "", vendor_filter=vendor_filter or "",
            )
            if live:
                return {
                    "invoices": [
                        {"invoice_number": i["invoice_number"], "vendor": i["vendor"],
                        "amount": str(i["amount"]), "currency": i["currency"],
                        "due_date": str(i.get("due_date", "")), "status": i["status"]}
                        for i in live
                    ],
                    "total": len(live),
                }
        except Exception as e:
            logger.error("Live invoice list failed client=%s: %s", self.client_id, e)

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                params: list = [self.client_id]
                where = ["client_id=%s"]
                if status_filter:
                    where.append("status=%s")
                    params.append(status_filter)
                else:
                    where.append("status NOT IN ('authorized','cancelled')")
                if vendor_filter:
                    where.append("vendor ILIKE %s")
                    params.append(f"%{vendor_filter}%")
                where_sql = " AND ".join(where)
                cur.execute(
                    f"SELECT invoice_number, vendor, amount, currency, due_date, status "
                    f"FROM invoices WHERE {where_sql} ORDER BY created_at DESC LIMIT 20",
                    params,
                )
                rows = cur.fetchall()
                cur.execute(f"SELECT COUNT(*) FROM invoices WHERE {where_sql}", params)
                total = cur.fetchone()[0]
                cur.close()
        except Exception as e:
            logger.error("List invoices failed client=%s: %s", self.client_id, e)
            return {"error": str(e)}

        return {
            "invoices": [
                {"invoice_number": r[0], "vendor": r[1], "amount": str(r[2]),
                "currency": r[3], "due_date": str(r[4]), "status": r[5]}
                for r in rows
            ],
            "total": total,
        }

    def _action_check_overdue(self, data: dict) -> dict:
        try:
            live = get_system_from_config(self.client_id).list_invoices(status_filter="overdue")
            if live:
                results = []
                for i in live:
                    due = i.get("due_date")
                    days_overdue = 0
                    if due:
                        try:
                            due_date = due if hasattr(due, "year") else date.fromisoformat(str(due)[:10])
                            days_overdue = (date.today() - due_date).days
                        except Exception:
                            pass
                    results.append({
                        "invoice_number": i["invoice_number"], "vendor": i["vendor"],
                        "amount": str(i["amount"]), "currency": i["currency"],
                        "due_date": str(due) if due else "", "days_overdue": days_overdue,
                    })
                return {
                    "invoices": results,
                    "total_outstanding": sum(float(i["amount_due"] or i["amount"]) for i in live),
                }
        except Exception as e:
            logger.error("Live overdue invoice fetch failed client=%s: %s", self.client_id, e)

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT invoice_number, vendor, amount, currency, due_date, "
                    "CURRENT_DATE - due_date AS days_overdue FROM invoices "
                    "WHERE client_id=%s AND status NOT IN ('paid','cancelled') "
                    "AND due_date < CURRENT_DATE ORDER BY due_date ASC LIMIT 5",
                    (self.client_id,),
                )
                rows = cur.fetchall()
                cur.close()
            return {
                "invoices": [
                    {"invoice_number": r[0], "vendor": r[1], "amount": str(r[2]),
                    "currency": r[3], "due_date": str(r[4]), "days_overdue": r[5]}
                    for r in rows
                ],
                "total_outstanding": sum(float(r[2]) for r in rows),
            }
        except Exception as e:
            logger.error("Check overdue failed client=%s: %s", self.client_id, e)
            return {"error": str(e)}

    def _action_approve(self, data: dict) -> dict:
        invoice_number = data.get("invoice_number")
        vendor = data.get("vendor")
        invoice_numbers = data.get("invoice_numbers") or []

        if invoice_numbers and len(invoice_numbers) > 1:
            return self._approve_batch(invoice_numbers)

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                if invoice_number:
                    cur.execute(
                        "SELECT id, external_id, amount, vendor, raw_message, description, due_date, currency "
                        "FROM invoices WHERE client_id=%s AND invoice_number=%s ORDER BY created_at DESC LIMIT 1",
                        (self.client_id, invoice_number),
                    )
                else:
                    cur.execute(
                        "SELECT id, external_id, amount, vendor, raw_message, description, due_date, currency "
                        "FROM invoices WHERE client_id=%s AND vendor ILIKE %s "
                        "AND status='pending' ORDER BY created_at DESC LIMIT 1",
                        (self.client_id, f"%{vendor}%"),
                    )
                row = cur.fetchone()
                cur.close()

            if not row:
                return {"error": f"No invoice found for '{invoice_number or vendor}'"}

            db_id, external_id, amount, db_vendor, raw_message, db_description, db_due_date, db_currency = row
            data["vendor"]   = data.get("vendor")   or db_vendor
            data["amount"]   = data.get("amount")   or (float(amount) if amount else None)
            data["currency"] = data.get("currency") or db_currency or _DEFAULT_CURRENCY
            if not data.get("due_date") and db_due_date:
                data["due_date"] = str(db_due_date)

            stored_data: dict = {}
            if raw_message:
                try:
                    stored_data = json.loads(raw_message)
                except (json.JSONDecodeError, TypeError):
                    pass
            if db_description and not stored_data.get("description"):
                stored_data["description"] = db_description

            missing = _missing_line_item_fields(stored_data)
            if missing:
                return {"error": f"Cannot authorise — missing: {', '.join(missing)}. Edit the invoice first."}

            if not external_id and invoice_number:
                try:
                    live = get_system_from_config(self.client_id).find_invoice_by_number(invoice_number)
                    if live:
                        external_id = live.get("InvoiceID") or live.get("Id")
                        if external_id:
                            with get_conn() as conn:
                                cur = conn.cursor()
                                cur.execute(
                                    "UPDATE invoices SET external_id=%s WHERE id=%s AND client_id=%s",
                                    (external_id, db_id, self.client_id),
                                )
                                cur.close()
                except Exception as exc:
                    logger.warning("approve: live lookup failed client=%s: %s", self.client_id, exc)

            if not external_id:
                return {"error": "Invoice not found in accounting platform — it may not have synced yet."}

            try:
                get_system_from_config(self.client_id).mark_invoice_authorised(external_id)
            except Exception as exc:
                error_str = str(exc)
                if "inactive" in error_str.lower() or "object not found" in error_str.lower():
                    try:
                        live = get_system_from_config(self.client_id).find_invoice_by_number(invoice_number) if invoice_number else {}
                        real_id = live.get("InvoiceID") or live.get("Id") if live else None
                        if real_id:
                            get_system_from_config(self.client_id).mark_invoice_authorised(real_id)
                            with get_conn() as conn:
                                cur = conn.cursor()
                                cur.execute("UPDATE invoices SET external_id=%s WHERE id=%s AND client_id=%s",
                                            (real_id, db_id, self.client_id))
                                cur.close()
                        else:
                            return {"error": "Invoice not found in accounting platform."}
                    except Exception as inner_exc:
                        return {"error": f"Could not approve invoice: {inner_exc}"}
                elif _is_non_retryable(exc):
                    return {"error": f"Accounting rejected authorisation: {exc}"}
                else:
                    return {"error": str(exc)}

            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE invoices SET status='authorized' WHERE id=%s AND client_id=%s",
                    (db_id, self.client_id))
                cur.close()

            pdf_bytes = None
            try:
                pdf_bytes = get_system_from_config(self.client_id).get_invoice_pdf(external_id)
            except Exception as exc:
                logger.warning("PDF re-fetch after approve failed client=%s: %s", self.client_id, exc)

            return {"approved": True, "invoice_id": db_id, "external_id": external_id, "pdf": pdf_bytes}

        except Exception as exc:
            logger.error("Approve invoice failed client=%s: %s", self.client_id, exc)
            return {"error": str(exc)}

    def _approve_batch(self, invoice_numbers: list[str]) -> dict:
        approved, failed = [], []
        for inv_num in invoice_numbers:
            try:
                with get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT id, external_id, raw_message, description FROM invoices "
                        "WHERE client_id=%s AND invoice_number=%s ORDER BY created_at DESC LIMIT 1",
                        (self.client_id, inv_num),
                    )
                    row = cur.fetchone()
                    cur.close()

                if not row:
                    failed.append({"invoice_number": inv_num, "reason": "Not found"})
                    continue

                db_id, external_id, raw_message, db_description = row

                stored_data: dict = {}
                if raw_message:
                    try:
                        stored_data = json.loads(raw_message)
                    except (json.JSONDecodeError, TypeError):
                        pass
                if db_description and not stored_data.get("description"):
                    stored_data["description"] = db_description

                missing = _missing_line_item_fields(stored_data)
                if missing:
                    failed.append({"invoice_number": inv_num, "reason": f"Missing: {', '.join(missing)}"})
                    continue

                if external_id:
                    try:
                        get_system_from_config(self.client_id).mark_invoice_authorised(external_id)
                    except Exception as exc:
                        failed.append({"invoice_number": inv_num, "reason": str(exc)})
                        continue

                with get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("UPDATE invoices SET status='authorized' WHERE id=%s AND client_id=%s",
                       (db_id, self.client_id))
                    cur.close()

                approved.append(inv_num)

            except Exception as exc:
                logger.error("Batch approve failed inv=%s client=%s: %s", inv_num, self.client_id, exc)
                failed.append({"invoice_number": inv_num, "reason": str(exc)})

        return {
            "batch_approved": True, "approved": approved, "failed": failed,
            "total": len(invoice_numbers), "approved_count": len(approved), "failed_count": len(failed),
        }

    def _action_approve_all(self, data: dict) -> dict:
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT invoice_number FROM invoices WHERE client_id=%s AND status='pending' "
                    "ORDER BY created_at ASC LIMIT 50",
                    (self.client_id,),
                )
                rows = cur.fetchall()
                cur.close()
            if not rows:
                return {"error": "No pending invoices found to approve"}
            return self._approve_batch([r[0] for r in rows if r[0]])
        except Exception as exc:
            logger.error("Approve all failed client=%s: %s", self.client_id, exc)
            return {"error": str(exc)}

    def _action_edit(self, data: dict) -> dict:
        invoice_number = data.get("invoice_number")
        vendor = data.get("vendor")
        edit_fields = data.get("edit_fields") or {}

        if not edit_fields:
            return {"error": "No fields to edit — please specify what to change"}

        if not invoice_number and not vendor:
            from core.conversation import get_action_context
            sender = data.get("_sender", "")
            if sender:
                inv_ctx = get_action_context(sender, self.client_id, "invoice")
                if inv_ctx:
                    invoice_number = inv_ctx.get("invoice_number")
                    vendor = inv_ctx.get("vendor")

        if not invoice_number and not vendor:
            return {"error": "Please specify the invoice number or vendor to edit."}

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                if invoice_number:
                    cur.execute(
                        "SELECT id, external_id, status, vendor, amount, currency, due_date "
                        "FROM invoices WHERE client_id=%s AND invoice_number=%s ORDER BY created_at DESC LIMIT 1",
                        (self.client_id, invoice_number),
                    )
                else:
                    cur.execute(
                        "SELECT id, external_id, status, vendor, amount, currency, due_date "
                        "FROM invoices WHERE client_id=%s AND vendor ILIKE %s "
                        "AND status NOT IN ('paid','cancelled') ORDER BY created_at DESC LIMIT 1",
                        (self.client_id, f"%{vendor}%"),
                    )
                row = cur.fetchone()
                cur.close()

            if not row:
                return {"error": f"No invoice found for '{invoice_number or vendor}'"}

            db_id, external_id, status, db_vendor, db_amount, db_currency, db_due_date = row

            if status in ("paid", "cancelled"):
                return {"error": f"Invoice is '{status}' and cannot be edited"}

            allowed_db_fields = {"amount", "due_date", "description", "vendor", "currency"}
            set_clauses: list[str] = []
            params: list = []
            for field, value in edit_fields.items():
                if field in allowed_db_fields:
                    set_clauses.append(f"{field}=%s")
                    params.append(value)

            if set_clauses:
                params.extend([db_id, self.client_id])
                with get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        f"UPDATE invoices SET {', '.join(set_clauses)} WHERE id=%s AND client_id=%s",
                        params,
                    )
                    cur.close()

            accounting_warning = None
            if external_id:
                try:
                    get_system_from_config(self.client_id).edit_invoice(external_id, edit_fields)
                except Exception as exc:
                    accounting_warning = f"DB updated but accounting sync failed: {exc}"

            pdf_bytes = None
            if external_id:
                try:
                    import time as _time
                    _time.sleep(2)
                    pdf_bytes = get_system_from_config(self.client_id).get_invoice_pdf(external_id)
                except Exception as exc:
                    logger.warning("PDF re-fetch after edit failed client=%s: %s", self.client_id, exc)

            result: dict = {"edited": True, "invoice_id": db_id,
                "fields_updated": list(edit_fields.keys()), "pdf": pdf_bytes}
            if accounting_warning:
                result["accounting_warning"] = accounting_warning
            return result

        except Exception as e:
            logger.error("Edit invoice failed client=%s: %s", self.client_id, e)
            return {"error": str(e)}

    def _update_invoice_field(self, idempotency_key: str, field: str, value) -> None:
        if field not in _VALID_INVOICE_FIELDS:
            raise ValueError(f"Invalid invoice field: '{field}'")
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                if value == "NOW()":
                    cur.execute(f"UPDATE invoices SET {field}=NOW() WHERE idempotency_key=%s",
                                (idempotency_key,))
                else:
                    cur.execute(f"UPDATE invoices SET {field}=%s WHERE idempotency_key=%s",
                                (value, idempotency_key))
                cur.close()
        except Exception as e:
            logger.error("Field update failed client=%s field=%s: %s", self.client_id, field, e)

    def _increment_reminder_count(self, invoice_number: str) -> None:
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE invoices SET reminder_count=reminder_count+1, reminder_sent_at=NOW() "
                    "WHERE client_id=%s AND invoice_number=%s",
                    (self.client_id, invoice_number),
                )
                cur.close()
        except Exception as e:
            logger.error("Reminder count update failed client=%s: %s", self.client_id, e)



class POAgent(BaseAgent):
    """Represent the POAgent component and its related behavior."""

    def __init__(self, client_id: str):
        super().__init__(client_id)
        self.confidence_threshold = INVOICE_CONFIG["confidence_threshold"]
        self._accounting_cb = CircuitBreaker(f"accounting_po:{client_id}")

    def get_system_prompt(self) -> str:
        return PO_AGENT_PROMPT

    def _run(self, task: dict) -> dict:
        message = task.get("message", "")
        sender  = task.get("sender", "")

        ctx_str = ""
        try:
            from core.conversation import _build_enriched_message, _get_context
            ctx_turns = _get_context(sender, self.client_id)
            ctx_str = _build_enriched_message(
                message, ctx_turns,
                sender=sender,
                client_id=self.client_id,
                domain="po",
            )
        except Exception:
            pass

        try:
            data = parse_po_message(message, context=ctx_str)
        except Exception as exc:
            logger.error("parse_po_message failed client=%s: %s", self.client_id, exc)
            return {"status": "error", "message": "Something went wrong — please try again."}

        confidence = float(data.get("confidence", 0.0))
        if confidence < self.confidence_threshold:
            return {
                "status": "needs_info",
                "message": "Please provide vendor name, amount, and what you're purchasing.",
            }

        data["_client_id"] = self.client_id
        action = data.get("action", "create")
        if action == "create":
            return self._create_po(data, message)
        if action == "find":
            return self._find_po(data, message)
        if action == "list":
            return self._list_pos(data)
        if action == "edit":
            return self._edit_po(data, message)
        if action == "approve":
            return self._approve_po(data, message)
        if action == "track":
            return self._track_po(data, message)
        if action == "remind":
            return self._remind_po(data, message)
        if action == "check_overdue":
            return self._check_overdue_pos()
        if action == "mark_received":
            return self._mark_po_received(data, message)
        if action == "send":
            po_number = data.get("po_number")
            if po_number:
                return self._get_po_pdf(po_number, message)
            return {"status": "needs_info", "message": "Which PO number do you want the PDF for?"}

        return {"status": "error", "message": f"Unknown PO action: {action}"}

    def _get_po_pdf(self, po_number: str, message: str) -> dict:
        po = _lookup_po_db(self.client_id, po_number=po_number)
        if not po or not po.get("external_id"):
            return {"status": "error", "message": f"PO {po_number} not found or not yet synced."}
        try:
            pdf_bytes = get_system_from_config(self.client_id).get_purchase_order_pdf(po["external_id"])
            confirmation = format_invoice_confirmation(
                "po_send",
                {"po_number": po_number, "vendor": po.get("vendor"), "currency": po.get("currency", "USD")},
                {"pdf": pdf_bytes},
            )
            return {"status": "success", "message": confirmation, "pdf": pdf_bytes, "po_number": po_number}
        except Exception as e:
            return {"status": "error", "message": f"Could not fetch PDF for {po_number}: {e}"}

    def _post_po_to_accounting(self, data: dict) -> dict:
        def _create_with_retry() -> dict:
            last_exc: Exception | None = None
            for attempt, delay in enumerate([1, 2, 4], start=1):
                try:
                    return get_system_from_config(self.client_id).create_purchase_order(data)
                except CircuitOpenError:
                    raise
                except Exception as exc:
                    try:
                        if _is_non_retryable(exc):
                            raise
                    except (XeroValidationError, QuickBooksValidationError):
                        raise
                    except Exception:
                        raise
                    last_exc = exc
                    if attempt < 3:
                        time.sleep(delay)
            raise last_exc  # type: ignore[misc]

        try:
            return self._accounting_cb.call(_create_with_retry)
        except CircuitOpenError:
            raise
        except Exception as last_exc:
            from core.tasks import retry_accounting_post
            retry_accounting_post.apply_async(args=[self.client_id, data], countdown=60, queue="low")  # type: ignore
            return {"error": str(last_exc), "queued_for_retry": True}

    def _create_po(self, data: dict, message: str) -> dict:
        if not data.get("vendor") or not data.get("amount"):
            return {"status": "needs_info", "message": "Please provide vendor name and amount to create a PO"}

        if not data.get("currency"):
            try:
                data["currency"] = get_system_from_config(self.client_id).get_organisation_currency()
            except Exception:
                data["currency"] = "USD"

        if data.get("delivery_date"):
            from agents.a01_invoice.tools import _resolve_and_validate_due_date
            resolved, error = _resolve_and_validate_due_date(data["delivery_date"])
            if error:
                return {"status": "needs_info", "message": error}
            data["delivery_date"] = resolved

        ik = hashlib.sha256(
            f"{self.client_id}:{data.get('vendor')}:{data.get('amount')}:{message}".encode()
        ).hexdigest()
        data["idempotency_key"] = ik

        try:
            po = self._post_po_to_accounting(data)
        except CircuitOpenError:
            return {"status": "error", "message": "Accounting service temporarily unavailable"}
        except Exception as e:
            error_str = str(e)
            msg = ("Purchase Orders are currently disabled in your QuickBooks account."
                   if "PurchaseOrder has to be enabled" in error_str or "purchase order" in error_str.lower()
                   else f"Could not create PO: {e}")
            return {"status": "error", "message": msg}
        if po.get("error"):
            error_str = po.get("error", "")
            msg = ("Purchase Orders are currently disabled in your QuickBooks account."
                   if "PurchaseOrder has to be enabled" in error_str or "purchase order" in error_str.lower()
                   else f"Could not create PO: {error_str}")
            return {"status": "error", "message": msg}
        po_number = po.get("PurchaseOrderNumber") or po.get("DocNumber") or data.get("po_number")
        po_id     = po.get("PurchaseOrderID") or po.get("Id")
        self._save_po_to_db(data, str(po_number), str(po_id), ik)

        vendor = data.get("vendor", "")
        if vendor:
            self.record_entity(entity_name=vendor, domain="invoice",
                            amount=float(data.get("amount") or 0),
                            currency=data.get("currency", _DEFAULT_CURRENCY))

        pdf_bytes = None
        if po_id:
            try:
                pdf_bytes = get_system_from_config(self.client_id).get_purchase_order_pdf(po_id)
            except Exception as e:
                logger.warning("PO PDF fetch failed client=%s: %s", self.client_id, e)

        data["po_number"] = po_number
        result_data = {"status": "success", "po_number": po_number, "po_id": po_id,
                    "accounting": po, "pdf": pdf_bytes}
        confirmation = format_invoice_confirmation("po_create", data, result_data)
        result = {"status": "success", "message": confirmation,
                "po_number": po_number, "po_id": po_id, "po": data, "result": result_data}
        log_action(self.client_id, "a01_invoice", "purchase_order", message, result, "success",
                message=f"PO created for {vendor} — {data.get('currency', 'USD')} {data.get('amount')}")
        return result

    def _find_po(self, data: dict, message: str) -> dict:
        po_number = data.get("po_number")
        vendor = data.get("vendor")
        po: dict = {}

        if po_number:
            po = _lookup_po_db(self.client_id, po_number=po_number)
            if not po:
                try:
                    raw = get_system_from_config(self.client_id).find_purchase_order_by_number(po_number)
                    if raw:
                        po = {"po_number": raw.get("PurchaseOrderNumber") or raw.get("DocNumber"),
                              "external_id": raw.get("PurchaseOrderID") or raw.get("Id"),
                              "vendor": raw.get("Contact", {}).get("Name", ""),
                              "amount": str(raw.get("Total", "")), "status": raw.get("Status", "")}
                except Exception as e:
                    logger.error("Accounting PO lookup failed client=%s: %s", self.client_id, e)
        elif vendor:
            po = _lookup_po_db(self.client_id, vendor=vendor)

        result_data = {"status": "success" if po else "not_found", "po": po}
        confirmation = format_invoice_confirmation("po_find", data, result_data)

        if po:
            result = {"status": "success", "message": confirmation, "po": po}
            log_action(self.client_id, "a01_invoice", "purchase_order", message, result, "success",
                       message=f"PO found for {po_number or vendor}")
        else:
            result = {"status": "not_found", "message": confirmation}
            log_action(self.client_id, "a01_invoice", "purchase_order", message, result, "not_found",
                       message=f"PO not found for {po_number or vendor}")
        return result

    def _list_pos(self, data: dict = {}) -> dict:
        status_filter = data.get("status_filter");
        vendor_filter = data.get("vendor_filter")
        try:
            live = get_system_from_config(self.client_id).list_purchase_orders(
                status_filter=status_filter or "", vendor_filter=vendor_filter or "",
            )
            if live:
                confirmation = format_invoice_confirmation("po_list", data, {"purchase_orders": live, "total": len(live)})
                return {"status": "success", "message": confirmation, "purchase_orders": live, "total": len(live)}
        except Exception as e:
            logger.error("Live PO list failed client=%s: %s", self.client_id, e)

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                params: list = [self.client_id]
                where = ["client_id=%s", "status NOT IN ('closed','cancelled')"]
                if status_filter:
                    where.append("status=%s"); params.append(status_filter)
                if vendor_filter:
                    where.append("vendor ILIKE %s"); params.append(f"%{vendor_filter}%")
                where_sql = " AND ".join(where)
                cur.execute(
                    f"SELECT po_number, vendor, amount, currency, status, created_at "
                    f"FROM purchase_orders WHERE {where_sql} ORDER BY created_at DESC LIMIT 20", params)
                rows = cur.fetchall()
                cur.execute(f"SELECT COUNT(*) FROM purchase_orders WHERE {where_sql}", params)
                total = cur.fetchone()[0]
                cur.close()
            purchase_orders = [{"po_number": r[0], "vendor": r[1], "amount": str(r[2]),
                "currency": r[3], "status": r[4], "created_at": str(r[5])} for r in rows]
            confirmation = format_invoice_confirmation("po_list", data, {"purchase_orders": purchase_orders, "total": total})
            return {"status": "success", "message": confirmation, "purchase_orders": purchase_orders, "total": total}
        except Exception as e:
            logger.error("List POs failed client=%s: %s", self.client_id, e)
            return {"status": "error", "message": str(e)}

    def _track_po(self, data: dict, message: str) -> dict:
        po_number = data.get("po_number")
        vendor = data.get("vendor")
        try:
            if po_number:
                raw = get_system_from_config(self.client_id).find_purchase_order_by_number(po_number)
                if raw:
                    result_data = {
                        "po_number": raw.get("PurchaseOrderNumber") or raw.get("DocNumber"),
                        "vendor": raw.get("Contact", {}).get("Name", vendor),
                        "amount": str(raw.get("Total", "")), "currency": raw.get("CurrencyCode", "USD"),
                        "status": raw.get("Status", "").lower(),
                    }
                    confirmation = format_invoice_confirmation(
                        "po_track", {"po_number": result_data["po_number"],
                                    "vendor": result_data["vendor"], "currency": result_data["currency"]},
                        result_data)
                    return {"status": "success", "message": confirmation, "po": result_data}
            elif vendor:
                live = get_system_from_config(self.client_id).list_purchase_orders(vendor_filter=vendor)
                if live:
                    match = live[0]
                    confirmation = format_invoice_confirmation(
                        "po_track", {"po_number": match.get("po_number"),
                                     "vendor": match.get("vendor"), "currency": match.get("currency", "USD")}, match)
                    return {"status": "success", "message": confirmation, "po": match}
        except Exception as e:
            logger.error("Live PO track failed client=%s: %s", self.client_id, e)

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                if po_number:
                    cur.execute("SELECT po_number, vendor, amount, currency, status FROM purchase_orders "
                                "WHERE client_id=%s AND po_number=%s LIMIT 1", (self.client_id, po_number))
                else:
                    cur.execute("SELECT po_number, vendor, amount, currency, status FROM purchase_orders "
                                "WHERE client_id=%s AND vendor ILIKE %s ORDER BY created_at DESC LIMIT 1",
                                (self.client_id, f"%{vendor}%"))
                row = cur.fetchone()
                cur.close()
            if not row:
                return {"status": "not_found", "message": f"No PO found for '{po_number or vendor}'."}
            result_data  = {"po_number": row[0], "vendor": row[1], "amount": str(row[2]),
                            "currency": row[3], "status": row[4]}
            confirmation = format_invoice_confirmation(
                "po_track", {"po_number": row[0], "vendor": row[1], "currency": row[3]}, result_data)
            return {"status": "success", "message": confirmation, "po": result_data}
        except Exception as e:
            logger.error("Track PO failed client=%s: %s", self.client_id, e)
            return {"status": "error", "message": str(e)}

    def _remind_po(self, data: dict, message: str) -> dict:
        po_number = data.get("po_number")
        vendor = data.get("vendor")
        recipient = data.get("recipient_email")
        po = _lookup_po_db(self.client_id, po_number=po_number or "", vendor=vendor or "")
        if not po:
            return {"status": "not_found", "message": f"No PO found for '{po_number or vendor}'."}
        if not recipient and po.get("external_id"):
            try:
                raw = get_system_from_config(self.client_id).get_purchase_order(po["external_id"])
                contact_id = raw.get("Contact", {}).get("ContactID")
                if contact_id:
                    recipient = get_system_from_config(self.client_id).get_contact_email(contact_id)
            except Exception as e:
                logger.warning("PO remind email lookup failed client=%s: %s", self.client_id, e)
        if not recipient:
            return {
                "status": "needs_info",
                "message": f"No email on file for {po.get('vendor')}.",
            }
        try:
            from integrations.email_factory import get_email_from_config
            email = get_email_from_config(self.client_id)
            sent = email.send(
                recipient=recipient,
                subject=f"Purchase Order Reminder — {po.get('po_number')}",
                body=(f"Dear {po.get('vendor')},\n\nThis is a reminder regarding PO {po.get('po_number')} "
                      f"for {po.get('currency', 'USD')} {po.get('amount')}.\n\n"
                      f"Please confirm receipt and expected delivery.\n\nKind regards"),
            )
            confirmation = format_invoice_confirmation(
                "po_remind",
                {"po_number": po.get("po_number"), "vendor": po.get("vendor"), "currency": po.get("currency", "USD")},
                {"reminder_sent": sent, "recipient": recipient},
            )
            return {"status": "success", "message": confirmation}
        except Exception as e:
            return {"status": "error", "message": f"Could not send reminder: {e}"}

    def _check_overdue_pos(self) -> dict:
        try:
            live = get_system_from_config(self.client_id).list_purchase_orders(status_filter="open")
            if live:
                from datetime import datetime as _dt
                overdue = []
                for po in live:
                    delivery = po.get("delivery_date")
                    if delivery:
                        try:
                            d = delivery if hasattr(delivery, "year") else _dt.strptime(str(delivery)[:10], "%Y-%m-%d").date()
                            days = (date.today() - d).days
                            if days > 0:
                                po["days_overdue"] = days
                                overdue.append(po)
                        except Exception:
                            pass
                if overdue:
                    confirmation = format_invoice_confirmation("po_check_overdue", {}, {"purchase_orders": overdue})
                    return {"status": "success", "message": confirmation, "purchase_orders": overdue}
        except Exception as e:
            logger.error("Live overdue PO fetch failed client=%s: %s", self.client_id, e)

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT po_number, vendor, amount, currency, CURRENT_DATE - created_at::date AS days_overdue "
                    "FROM purchase_orders WHERE client_id=%s AND status NOT IN ('billed','closed','cancelled') "
                    "AND created_at < NOW() - INTERVAL '30 days' ORDER BY created_at ASC LIMIT 10",
                    (self.client_id,),
                )
                rows = cur.fetchall()
                cur.close()
            purchase_orders = [{"po_number": r[0], "vendor": r[1], "amount": str(r[2]),
                "currency": r[3], "days_overdue": r[4]} for r in rows]
            confirmation = format_invoice_confirmation("po_check_overdue", {}, {"purchase_orders": purchase_orders})
            return {"status": "success", "message": confirmation, "purchase_orders": purchase_orders}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _mark_po_received(self, data: dict, message: str) -> dict:
        po_number = data.get("po_number")
        vendor = data.get("vendor")

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                if po_number:
                    cur.execute(
                        "UPDATE purchase_orders SET status='billed', updated_at=NOW() "
                        "WHERE client_id=%s AND po_number=%s RETURNING po_number, vendor, amount, currency",
                        (self.client_id, po_number),
                    )
                else:
                    cur.execute(
                        "UPDATE purchase_orders SET status='billed', updated_at=NOW() "
                        "WHERE client_id=%s AND vendor ILIKE %s AND status NOT IN ('billed','closed','cancelled') "
                        "ORDER BY created_at DESC LIMIT 1 RETURNING po_number, vendor, amount, currency",
                        (self.client_id, f"%{vendor}%"),
                    )
                row = cur.fetchone()
                cur.close()
            if not row:
                return {"status": "not_found", "message": f"No open PO found for '{po_number or vendor}'."}
            confirmation = format_invoice_confirmation(
                "po_mark_received", {"po_number": row[0], "vendor": row[1], "currency": row[3]}, {"received": True})
            return {"status": "success", "message": confirmation}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _edit_po(self, data: dict, message: str) -> dict:
        po_number = data.get("po_number")
        if not po_number:
            return {"status": "needs_info", "message": "Which PO do you want to edit?"}
        po = _lookup_po_db(self.client_id, po_number=po_number)
        external_id = po.get("external_id") if po else None
        if not external_id:
            try:
                raw = get_system_from_config(self.client_id).find_purchase_order_by_number(po_number)
                if raw:
                    external_id = raw.get("PurchaseOrderID") or raw.get("Id")
            except Exception as e:
                logger.error("PO fallback lookup failed client=%s: %s", self.client_id, e)
        if not external_id:
            return {"status": "error", "message": f"PO {po_number} not found in accounting system."}

        edit_fields = data.get("edit_fields") or {}
        if not edit_fields:
            return {"status": "needs_info", "message": "What do you want to change on this PO?"}

        allowed_db_fields = {"amount", "vendor", "description", "currency", "delivery_date"}
        set_clauses: list[str] = []
        params: list = []
        for field, value in edit_fields.items():
            if field in allowed_db_fields:
                set_clauses.append(f"{field}=%s"); params.append(value)
        if set_clauses:
            params.extend([self.client_id, po_number])
            try:
                with get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        f"UPDATE purchase_orders SET {', '.join(set_clauses)}, updated_at=NOW() "
                        f"WHERE client_id=%s AND po_number=%s", params)
                    cur.close()
            except Exception as e:
                return {"status": "error", "message": f"DB update failed: {e}"}

        accounting_warning = None
        try:
            get_system_from_config(self.client_id).edit_purchase_order(external_id, edit_fields)
        except Exception as e:
            accounting_warning = str(e)

        pdf_bytes = None
        try:
            import time as _time
            _time.sleep(2)
            pdf_bytes = get_system_from_config(self.client_id).get_purchase_order_pdf(external_id)
        except Exception as e:
            logger.warning("PO PDF fetch after edit failed client=%s: %s", self.client_id, e)

        result: dict = {"edited": True, "fields_updated": list(edit_fields.keys()), "pdf": pdf_bytes}
        if accounting_warning:
            result["accounting_warning"] = f"DB updated but accounting sync failed: {accounting_warning}"
        confirmation = format_invoice_confirmation(
            "po_edit", {"po_number": po_number, "vendor": po.get("vendor", data.get("vendor", ""))}, result)
        return {"status": "success", "message": confirmation, "result": result, "pdf": pdf_bytes}

    def _approve_po(self, data: dict, message: str) -> dict:
        po_number = data.get("po_number")
        vendor = data.get("vendor")
        external_id = None
        resolved_po_number = po_number
        resolved_vendor = vendor

        po = _lookup_po_db(self.client_id, po_number=po_number or "", vendor=vendor or "")
        if po:
            external_id = po.get("external_id")
            resolved_po_number = po.get("po_number") or po_number
            resolved_vendor = po.get("vendor") or vendor

        if not external_id and po_number:
            try:
                raw = get_system_from_config(self.client_id).find_purchase_order_by_number(po_number)
                if raw:
                    external_id = raw.get("PurchaseOrderID") or raw.get("Id")
                    resolved_vendor = raw.get("Contact", {}).get("Name", vendor)
            except Exception as e:
                logger.error("Live PO lookup by number failed client=%s: %s", self.client_id, e)

        if not external_id and vendor:
            try:
                results = get_system_from_config(self.client_id).list_purchase_orders(vendor_filter=vendor)
                if results:
                    external_id = results[0].get("external_id"); resolved_po_number = results[0].get("po_number") or resolved_po_number
            except Exception as e:
                logger.error("Live PO lookup by vendor failed client=%s: %s", self.client_id, e)

        if not external_id:
            return {"status": "error", "message": f"PO '{po_number or vendor}' not found."}

        try:
            get_system_from_config(self.client_id).approve_purchase_order(external_id)
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE purchase_orders SET status='submitted' WHERE client_id=%s AND po_number=%s",
                            (self.client_id, resolved_po_number))
                cur.close()
            confirmation = format_invoice_confirmation(
                "po_approve", {"po_number": resolved_po_number, "vendor": resolved_vendor or ""}, {"status": "success"})
            return {"status": "success", "message": confirmation}
        except Exception as e:
            return {"status": "error", "message": f"Could not approve PO: {e}"}

    def _save_po_to_db(self, data: dict, po_number: str, po_id: str, ik: str) -> None:
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO purchase_orders "
                    "(client_id, vendor, amount, currency, po_number, external_id, description, status, idempotency_key) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (idempotency_key) DO NOTHING",
                    (self.client_id, data.get("vendor"), data.get("amount"),
                     data.get("currency", "USD"), po_number, po_id,
                     data.get("description"), "open", ik),
                )
                cur.close()
        except Exception as exc:
            logger.error("PO DB save failed client=%s: %s", self.client_id, exc)



class BillAgent(BaseAgent):
    """Represent the BillAgent component and its related behavior."""

    def __init__(self, client_id: str):
        super().__init__(client_id)
        self.confidence_threshold = INVOICE_CONFIG["confidence_threshold"]
        self._accounting_cb = CircuitBreaker(f"accounting_bill:{client_id}")

    def get_system_prompt(self) -> str:
        return BILL_AGENT_PROMPT

    def _run(self, task: dict) -> dict:
        message = task.get("message", "")
        channel = task.get("channel", "")
        sender = task.get("sender", "")
        is_document = task.get("is_document", False)

        if is_document:
            file_bytes, img_mime = _extract_bill_file_from_task(task)

            if file_bytes:
                from agents.utils.document_extractor import enrich_vision_prompt
                from agents.base_agent import _get_client
                import base64 as _b64
                import re as _re
                from typing import Literal, cast as _cast

                enriched_prompt = enrich_vision_prompt(INVOICE_PDF_EXTRACTION_PROMPT, self.client_id)
                image_b64       = _b64.standard_b64encode(file_bytes).decode("utf-8")
                _mt             = _cast(Literal["image/jpeg", "image/png", "image/gif", "image/webp"], img_mime)

                data = {}
                for model, max_tok in [("claude-sonnet-4-6", 4096), ("claude-haiku-4-5-20251001", 4096)]:
                    try:
                        response = _get_client().messages.create(
                            model=model,
                            max_tokens=max_tok,
                            system=enriched_prompt,
                            messages=[{
                                "role": "user",
                                "content": [
                                    {"type": "image", "source": {"type": "base64", "media_type": _mt, "data": image_b64}},
                                    {"type": "text", "text": "Extract all bill/invoice details from this document."},
                                ],
                            }],
                        )
                        for block in response.content:
                            if block.type == "text":
                                text = block.text.strip()
                                text = _re.sub(r"^```(?:json)?\s*", "", text, flags=_re.IGNORECASE)
                                text = _re.sub(r"\s*```$", "", text).strip()
                                match = _re.search(r'\{.*\}', text, _re.DOTALL)
                                if not match:
                                    continue
                                parsed = _parse_json(match.group())
                                if parsed:
                                    parsed["amount"] = _sanitise_amount(parsed.get("amount"))
                                    parsed["tax_amount"] = _sanitise_amount(parsed.get("tax_amount"))
                                    data = parsed
                                    data["_client_id"] = self.client_id
                                    data["action"]     = "create"
                                    break
                        if data:
                            break
                    except Exception as exc:
                        logger.warning("Bill vision extraction failed model=%s client=%s: %s", model, self.client_id, exc)
                        continue

            elif task.get("_pdf_text"):
                try:
                    from agents.base_agent import _get_client
                    from agents.utils.document_extractor import enrich_vision_prompt
                    import re as _re

                    pdf_text = task["_pdf_text"]
                    enriched_prompt = enrich_vision_prompt(INVOICE_PDF_EXTRACTION_PROMPT, self.client_id)
                    response = _get_client().messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=4096,
                        system=enriched_prompt,
                        messages=[{
                            "role": "user",
                            "content": f"Extract all bill/invoice details from this document text:\n\n{pdf_text}",
                        }],
                    )
                    data = {}
                    for block in response.content:
                        if block.type == "text":
                            text = block.text.strip()
                            text = _re.sub(r"^```(?:json)?\s*", "", text, flags=_re.IGNORECASE)
                            text = _re.sub(r"\s*```$", "", text).strip()
                            match = _re.search(r'\{.*\}', text, _re.DOTALL)
                            if not match:
                                continue
                            parsed = _parse_json(match.group())
                            if parsed:
                                parsed["amount"] = _sanitise_amount(parsed.get("amount"))
                                parsed["tax_amount"] = _sanitise_amount(parsed.get("tax_amount"))
                                data = parsed
                                data["_client_id"] = self.client_id
                                data["action"]     = "create"
                                break
                except Exception as exc:
                    logger.error("Bill PDF text-parse failed client=%s: %s", self.client_id, exc)
                    data = {}

            else:
                try:
                    from agents.base_agent import _get_client
                    import re as _re
                    response = _get_client().messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=4096,
                        system=INVOICE_PDF_EXTRACTION_PROMPT,
                        messages=[{"role": "user", "content": message}],
                    )
                    data = {}
                    for block in response.content:
                        if block.type == "text":
                            text = block.text.strip()
                            text = _re.sub(r"^```(?:json)?\s*", "", text, flags=_re.IGNORECASE)
                            text = _re.sub(r"\s*```$", "", text).strip()
                            match = _re.search(r'\{.*\}', text, _re.DOTALL)
                            if not match:
                                continue
                            parsed = _parse_json(match.group())
                            if parsed:
                                parsed["amount"] = _sanitise_amount(parsed.get("amount"))
                                data = parsed; data["_client_id"] = self.client_id; data["action"] = "create"; break
                except Exception as exc:
                    logger.error("Bill document text-parse failed client=%s: %s", self.client_id, exc); data = {}

            if data and data.get("amount"):
                raw_amount = float(data["amount"] or 0)
                tax_amount = data.get("tax_amount")
                net_amount = get_net_amount(self.client_id, raw_amount, tax_amount)
                if net_amount != raw_amount:
                    data["amount_gross"] = raw_amount; data["amount"] = net_amount
                doc_type = (data.get("document_type") or "bill").lower()
                is_paid  = bool(data.get("is_paid", False))
                if doc_type == "purchase_order":
                    po_agent = POAgent(self.client_id)
                    po_data = {
                        "action":      "create",
                        "vendor":      data.get("vendor"),
                        "amount":      data.get("amount"),
                        "description": data.get("description"),
                        "po_number":   data.get("invoice_number"),
                        "currency":    data.get("currency"),
                        "due_date":    data.get("due_date"),
                        "confidence":  data.get("confidence", 0.9),
                        "_client_id":  self.client_id,
                    }
                    return po_agent._create_po(po_data, message)

                if is_paid or doc_type in ("receipt", "expense"):
                    from agents.a02_expense.agent import ExpenseAgent
                    expense_agent = ExpenseAgent(self.client_id)
                    expense_task = {
                        **task,
                        "message":    message,
                        "action":     "capture",
                        "vendor":     data.get("vendor"),
                        "amount":     data.get("amount"),
                        "tax_amount": data.get("tax_amount"),
                        "currency":   data.get("currency"),
                        "date":       data.get("invoice_date") or data.get("due_date"),
                        "category":   "supplier",
                        "confidence": data.get("confidence", 0.9),
                    }
                    return expense_agent._run(expense_task)

        else:
            ctx_str = ""
            try:
                from core.conversation import _build_enriched_message, _get_context
                ctx_turns = _get_context(sender, self.client_id)
                ctx_str = _build_enriched_message(
                    message, ctx_turns,
                    sender=sender,
                    client_id=self.client_id,
                    domain="bill",
                )
            except Exception:
                pass
            try:
                data = parse_bill_message(message, is_document=False, context=ctx_str)
            except Exception as exc:
                logger.error("parse_bill_message failed client=%s: %s", self.client_id, exc)
                return {"status": "error", "message": "Could not extract bill data — please try again."}

        data["_client_id"] = self.client_id

        if not is_document:
            action     = data.get("action", "create")
            confidence = float(data.get("confidence", 0.0))

            if action in ("list", "list_bills"):
                return self._list_bills(data)
            if action == "find":
                return self._find_bill(data)
            if action == "track":
                return self._track_bill(data)
            if action == "edit":
                return self._edit_bill_record(data)
            if action == "check_overdue":
                return self._check_overdue_bills()

            if confidence < self.confidence_threshold:
                return {
                    "status": "needs_info",
                    "message": "Please provide vendor name and amount. Example: 'log bill from Acme INR 5000 for office supplies'",
                }

        if not data or not data.get("vendor"):
            try:
                raw = self.call_llm(task=message, intent="invoice")
                llm_data = self.parse_llm_json(raw)
                data = {
                    "vendor":          llm_data.get("vendor"),
                    "amount":          llm_data.get("amount"),
                    "description":     llm_data.get("description"),
                    "invoice_number":  llm_data.get("invoice_number"),
                    "po_number":       llm_data.get("po_number"),
                    "currency":        llm_data.get("currency", _DEFAULT_CURRENCY),
                    "due_date":        llm_data.get("due_date"),
                    "recipient_email": llm_data.get("recipient_email"),
                    "confidence":      float(llm_data.get("confidence", 0.0)),
                    "_client_id":      self.client_id,
                }
            except (json.JSONDecodeError, ValueError) as e:
                logger.error("Bill parse failed client=%s: %s", self.client_id, e)
                return {"status": "error", "message": "Could not extract bill data from document"}

        confidence = float(data.get("confidence", 0.0))
        if confidence < self.confidence_threshold:
            return {"status": "escalate", "message": "Could not confidently read this document — please check it manually"}

        if not data.get("vendor") or not data.get("amount"):
            return {"status": "needs_info", "message": "Could not find vendor name or amount — please provide them"}

        if not data.get("description"):
            return {"status": "needs_info", "message": "Could not find a description — please provide a brief summary"}

        if not data.get("currency"):
            vendor = data.get("vendor", "unknown vendor")
            amount = data.get("amount", "")
            country_hint = " ".join(filter(None, [
                data.get("vendor_address", ""),
                data.get("vendor_tax_id", ""),
                data.get("vendor_phone", ""),
                data.get("vendor_email", ""),
                data.get("bill_to_address", ""),
                data.get("notes", ""),
                data.get("payment_method", ""),
                data.get("description", ""),
            ])).strip()

            try:
                org_currency = get_system_from_config(self.client_id).get_organisation_currency()
            except Exception:
                org_currency = None

            try:
                from agents.base_agent import _get_client
                import re as _re, json as _json
                context_hint = f"Context clues from document: {country_hint}." if country_hint else ""
                org_hint = f"Client base currency is {org_currency}." if org_currency else ""
                response = _get_client().messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=150,
                    messages=[{
                        "role": "user",
                        "content": (
                        f"A bill from '{vendor}' for amount {amount} was received. "
                        f"{context_hint} {org_hint} Can you confidently determine the currency from these clues? "
                        f"Reply ONLY as JSON: {{ \"currency\": \"SGD\", \"confident\": true, \"reason\": \"...\" }} "
                        f"or if not confident: {{ \"currency\": null, \"confident\": false, \"reason\": \"...\" }}"
                    )}],
                )
                raw = next((b.text.strip() for b in response.content if b.type == "text"), "{}")
                match = _re.search(r'\{.*\}', raw, _re.DOTALL)
                ai_result = _json.loads(match.group()) if match else {}
            except Exception:
                ai_result = {}

            detected_currency = ai_result.get("currency")
            confident = bool(ai_result.get("confident", False))
            reason = ai_result.get("reason", "")

            if detected_currency and confident:
                data["currency"] = detected_currency.upper()
            else:
                if org_currency:
                    question = (
                        f"I couldn't confidently detect the currency for this {vendor} bill"
                        + (f" ({reason})" if reason else "")
                        + f". Your base currency is {org_currency} — is this bill in {org_currency}, or a different currency?"
                    )
                else:
                    question = (
                        f"I couldn't confidently detect the currency for this {vendor} bill"
                        + (f" ({reason})" if reason else "")
                        + f". Reply with the currency code e.g. 'USD', 'SGD', 'INR'."
                    )
                return {
                    "status": "needs_info",
                    "message": question,
                }

        return self._create_bill(data, message, channel, sender)

    def _post_bill_to_accounting(self, data: dict) -> dict:
        def _create_with_retry() -> dict:
            last_exc: Exception | None = None
            for attempt, delay in enumerate([1, 2, 4], start=1):
                try:
                    return get_system_from_config(self.client_id).create_bill(data)
                except CircuitOpenError:
                    raise
                except Exception as exc:
                    try:
                        if _is_non_retryable(exc):
                            raise
                    except (XeroValidationError, QuickBooksValidationError):
                        raise
                    except Exception:
                        raise
                    last_exc = exc
                    if attempt < 3:
                        time.sleep(delay)
            raise last_exc  # type: ignore[misc]

        try:
            return self._accounting_cb.call(_create_with_retry)
        except CircuitOpenError:
            raise
        except Exception as last_exc:
            from core.tasks import retry_accounting_post
            retry_accounting_post.apply_async(args=[self.client_id, data], countdown=60, queue="low")  # type: ignore
            return {"error": str(last_exc), "queued_for_retry": True}

    def _create_bill(self, data: dict, message: str, channel: str, sender: str) -> dict:
        ik = hashlib.sha256(
            f"{self.client_id}:{data.get('vendor')}:{data.get('amount')}:{data.get('invoice_number')}".encode()
        ).hexdigest()
        data["idempotency_key"] = ik

        if not self._save_bill_to_db(data):
            result = {
                "status": "duplicate",
                "message": format_invoice_confirmation("bill_create", data, {"status": "duplicate"}),
            }
            log_action(self.client_id, "a01_invoice", "bill", message[:200], result, "duplicate")
            return result

        try:
            bill = self._post_bill_to_accounting(data)
        except CircuitOpenError:
            result = {"status": "error", "message": "Accounting service temporarily unavailable"}
            log_action(self.client_id, "a01_invoice", "bill", message[:200], result, "error")
            return result
        except Exception as e:
            result = {"status": "error", "message": f"Could not post bill to accounting: {e}"}
            log_action(self.client_id, "a01_invoice", "bill", message[:200], result, "error")
            return result

        if bill.get("error"):
            result = {"status": "error", "message": f"Could not post bill to accounting: {bill['error']}"}
            log_action(self.client_id, "a01_invoice", "bill", message[:200], result, "error")
            return result

        bill_id = bill.get("InvoiceID") or bill.get("Id")
        if bill_id:
            self._update_bill_external_id(ik, bill_id)

        pdf_bytes = None
        if bill_id:
            try:
                pdf_bytes = get_system_from_config(self.client_id).get_bill_pdf(bill_id)
            except Exception as e:
                logger.warning("Bill PDF fetch failed client=%s: %s", self.client_id, e)

        if bill_id and channel and sender and pdf_bytes:
            try:
                self._send_pdf_to_channel(channel, sender, pdf_bytes, data)
            except Exception as exc:
                logger.warning("Bill PDF send failed client=%s: %s", self.client_id, exc)

        vendor = data.get("vendor", "")
        if vendor:
            self.record_entity(entity_name=vendor, domain="expense",
                               amount=float(data.get("amount") or 0),
                               currency=data.get("currency", _DEFAULT_CURRENCY))
        result_data = {"status": "success", "accounting": bill, "pdf": pdf_bytes}
        confirmation = format_invoice_confirmation("bill_create", data, result_data)
        result = {"status": "success", "message": confirmation, "bill": data}
        log_action(self.client_id, "a01_invoice", "bill", message[:200], result, "success",
            message=f"Bill created for {data.get('vendor')} - {data.get('currency','USD')} {data.get('amount')}")
        return result

    def _list_bills(self, data: dict) -> dict:
        status_filter = data.get("status_filter")
        vendor_filter = data.get("vendor_filter")
        try:
            live = get_system_from_config(self.client_id).list_bills(
                status_filter=status_filter or "", vendor_filter=vendor_filter or "",
            )
            if live:
                bills = [{"vendor": b["vendor"], "amount": str(b["amount"]), "currency": b["currency"],
                    "invoice_number": b["invoice_number"], "status": b["status"],
                    "due_date": str(b.get("due_date", ""))}
                    for b in live
                ]
                confirmation = format_invoice_confirmation("bill_list", data, {"bills": bills, "total": len(bills)})
                return {"status": "success", "message": confirmation, "bills": bills, "total": len(bills)}
        except Exception as e:
            logger.error("Live bill list failed client=%s: %s", self.client_id, e)

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                params: list = [self.client_id]
                where = ["client_id=%s"]
                if status_filter:
                    where.append("status=%s")
                    params.append(status_filter)
                if vendor_filter:
                    where.append("vendor ILIKE %s")
                    params.append(f"%{vendor_filter}%")
                where_sql = " AND ".join(where)
                cur.execute(
                    f"SELECT vendor, amount, currency, invoice_number, status, due_date "
                    f"FROM bills WHERE {where_sql} ORDER BY created_at DESC LIMIT 20", params)
                rows = cur.fetchall()
                cur.execute(f"SELECT COUNT(*) FROM bills WHERE {where_sql}", params)
                total = cur.fetchone()[0]
                cur.close()
            bills = [{"vendor": r[0], "amount": str(r[1]), "currency": r[2],
                "invoice_number": r[3], "status": r[4], "due_date": str(r[5])} for r in rows]
            confirmation = format_invoice_confirmation("bill_list", data, {"bills": bills, "total": total})
            return {"status": "success", "message": confirmation, "bills": bills, "total": total}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _find_bill(self, data: dict) -> dict:
        invoice_number = data.get("invoice_number")
        vendor = data.get("vendor")
        try:
            if invoice_number:
                raw = get_system_from_config(self.client_id).find_invoice_by_number(invoice_number)
                if raw:
                    bill = {
                        "vendor": raw.get("Contact", {}).get("Name", vendor),
                        "amount": str(raw.get("AmountDue", "")),
                        "currency": raw.get("CurrencyCode", "USD"),
                        "invoice_number": invoice_number,
                        "status": raw.get("Status", "").lower(),
                        "due_date": str(raw.get("DueDate", "")),
                    }
                    confirmation = format_invoice_confirmation("bill_find", data, {"status": "success", "bill": bill})
                    return {"status": "success", "message": confirmation, "bill": bill}
            elif vendor:
                live = get_system_from_config(self.client_id).list_bills(vendor_filter=vendor)
                if live:
                    b = live[0]
                    bill = {
                        "vendor": b["vendor"], "amount": str(b["amount"]),
                        "currency": b["currency"], "invoice_number": b["invoice_number"],
                        "status": b["status"], "due_date": str(b.get("due_date", "")),
                    }
                    confirmation = format_invoice_confirmation("bill_find", data, {"status": "success", "bill": bill})
                    return {"status": "success", "message": confirmation, "bill": bill}
        except Exception as e:
            logger.error("Live bill find failed client=%s: %s", self.client_id, e)

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                if invoice_number:
                    cur.execute("SELECT vendor, amount, currency, invoice_number, status, due_date "
                        "FROM bills WHERE client_id=%s AND invoice_number=%s LIMIT 1",
                        (self.client_id, invoice_number))
                else:
                    cur.execute("SELECT vendor, amount, currency, invoice_number, status, due_date "
                                "FROM bills WHERE client_id=%s AND vendor ILIKE %s ORDER BY created_at DESC LIMIT 1",
                                (self.client_id, f"%{vendor}%"))
                row = cur.fetchone()
                cur.close()
            if not row:
                confirmation = format_invoice_confirmation("bill_find", data, {"status": "not_found", "bill": {}})
                return {"status": "not_found", "message": confirmation}
            bill = {"vendor": row[0], "amount": str(row[1]), "currency": row[2],
                    "invoice_number": row[3], "status": row[4], "due_date": str(row[5])}
            confirmation = format_invoice_confirmation("bill_find", data, {"status": "success", "bill": bill})
            return {"status": "success", "message": confirmation, "bill": bill}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    def _track_bill(self, data: dict) -> dict:
        invoice_number = data.get("invoice_number")
        vendor = data.get("vendor")
        try:
            if invoice_number:
                raw = get_system_from_config(self.client_id).find_invoice_by_number(invoice_number)
                if raw:
                    confirmation = format_invoice_confirmation(
                        "bill_track",
                        {"vendor": raw.get("Contact", {}).get("Name", vendor), "currency": raw.get("CurrencyCode", "USD")},
                        {"status": raw.get("Status", "").lower(), "due_date": str(raw.get("DueDate", "N/A")),
                         "amount": str(raw.get("AmountDue", ""))})
                    return {"status": "success", "message": confirmation}
            elif vendor:
                live = get_system_from_config(self.client_id).list_bills(vendor_filter=vendor)
                if live:
                    b = live[0]
                    confirmation = format_invoice_confirmation(
                        "bill_track", {"vendor": b["vendor"], "currency": b["currency"]},
                        {"status": b["status"], "due_date": str(b.get("due_date", "")), "amount": str(b["amount"])})
                    return {"status": "success", "message": confirmation}
        except Exception as e:
            logger.error("Live bill track failed client=%s: %s", self.client_id, e)

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                if invoice_number:
                    cur.execute("SELECT vendor, amount, currency, status, due_date FROM bills "
                                "WHERE client_id=%s AND invoice_number=%s LIMIT 1",
                        (self.client_id, invoice_number))
                else:
                    cur.execute("SELECT vendor, amount, currency, status, due_date FROM bills "
                                "WHERE client_id=%s AND vendor ILIKE %s ORDER BY created_at DESC LIMIT 1",
                       (self.client_id, f"%{vendor}%"))
                row = cur.fetchone()
                cur.close()
            if not row:
                return {"status": "not_found", "message": f"No bill found for '{invoice_number or vendor}'."}
            confirmation = format_invoice_confirmation(
                "bill_track", {"vendor": row[0], "currency": row[2]},
                {"status": row[3], "due_date": str(row[4]), "amount": str(row[1])})
            return {"status": "success", "message": confirmation}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    def _edit_bill_record(self, data: dict) -> dict:
        edit_fields = data.get("edit_fields") or {}
        if not edit_fields:
            return {"error": "No fields to edit — please specify what to change"}
        invoice_number = data.get("invoice_number"); vendor = data.get("vendor")
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                if invoice_number:
                    cur.execute("SELECT id, external_id, status, vendor, amount, currency FROM bills "
                                "WHERE client_id=%s AND invoice_number=%s ORDER BY created_at DESC LIMIT 1",
                                (self.client_id, invoice_number))
                else:
                    cur.execute("SELECT id, external_id, status, vendor, amount, currency FROM bills "
                                "WHERE client_id=%s AND vendor ILIKE %s AND status NOT IN ('paid','cancelled') "
                                "ORDER BY created_at DESC LIMIT 1",
                                (self.client_id, f"%{vendor}%"))
                row = cur.fetchone()
                cur.close()
            if not row:
                return {"error": f"No bill found for '{invoice_number or vendor}'"}
            db_id, external_id, status, db_vendor, db_amount, db_currency = row
            if status in ("paid", "cancelled"):
                return {"error": f"Bill is '{status}' and cannot be edited"}

            allowed_db_fields = {"amount", "due_date", "description", "vendor", "currency"}
            set_clauses: list[str] = []
            params: list = []
            for field, value in edit_fields.items():
                if field in allowed_db_fields:
                    set_clauses.append(f"{field}=%s")
                    params.append(value)

            if not set_clauses:
                return {"error": "No valid fields to update"}

            params.extend([db_id, self.client_id])
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    f"UPDATE bills SET {', '.join(set_clauses)} WHERE id=%s AND client_id=%s",
                    params,
                )
                cur.close()

            accounting_warning = None
            if external_id:
                try:
                    get_system_from_config(self.client_id).edit_bill(external_id, edit_fields)
                except Exception as exc:
                    accounting_warning = f"DB updated but accounting sync failed: {exc}"
            result: dict = {"edited": True, "fields_updated": list(edit_fields.keys())}
            if accounting_warning:
                result["accounting_warning"] = accounting_warning

            confirmation = format_invoice_confirmation("bill_edit", data, result)
            return {"status": "success", "message": confirmation, "result": result}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _check_overdue_bills(self) -> dict:
        try:
            live = get_system_from_config(self.client_id).list_bills(status_filter="overdue")
            if live:
                today = date.today(); bills = []
                for b in live:
                    due_raw = b.get("due_date"); days_overdue = 0
                    if due_raw:
                        try:
                            due_obj     = due_raw if hasattr(due_raw, "year") else date.fromisoformat(str(due_raw)[:10])
                            days_overdue = (today - due_obj).days
                        except Exception:
                            pass
                    bills.append({"vendor": b["vendor"], "amount": str(b["amount"]), "currency": b["currency"],
                                  "due_date": str(due_raw) if due_raw else "", "days_overdue": days_overdue})
                total_outstanding = sum(float(b.get("amount_due") or b.get("amount", 0)) for b in live)
                confirmation = format_invoice_confirmation(
                    "bill_check_overdue", {}, {"bills": bills, "total_outstanding": total_outstanding}
                )
                return {"status": "success", "message": confirmation, "bills": bills}
        except Exception as e:
            logger.error("Live overdue bills fetch failed client=%s: %s", self.client_id, e)
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT vendor, amount, currency, CURRENT_DATE - due_date AS days_overdue FROM bills "
                    "WHERE client_id=%s AND status NOT IN ('paid','cancelled') "
                    "AND due_date IS NOT NULL AND due_date < CURRENT_DATE ORDER BY due_date ASC LIMIT 10",
                    (self.client_id,),
                )
                rows = cur.fetchall()
                cur.close()
            bills = [
                {"vendor": r[0], "amount": str(r[1]), "currency": r[2], "days_overdue": r[3]}
                for r in rows
            ]
            total_outstanding = sum(float(r[1]) for r in rows)
            confirmation = format_invoice_confirmation(
                "bill_check_overdue", {}, {"bills": bills, "total_outstanding": total_outstanding}
            )
            return {"status": "success", "message": confirmation, "bills": bills}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _save_bill_to_db(self, data: dict) -> bool:
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO bills (client_id, vendor, amount, currency, invoice_number, "
                    "po_number, due_date, status, idempotency_key, raw_data) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (idempotency_key) DO NOTHING RETURNING id",
                    (self.client_id, data.get("vendor"), data.get("amount"),
                     data.get("currency", "USD"), data.get("invoice_number"),
                     data.get("po_number"), data.get("due_date"),
                     "pending", data.get("idempotency_key"), json.dumps(data)),
                )
                row = cur.fetchone()
                cur.close()
            return row is not None
        except Exception as e:
            logger.error("Bill DB save failed client=%s: %s", self.client_id, e)
            return False

    def _update_bill_external_id(self, ik: str, external_id: str) -> None:
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE bills SET external_id=%s WHERE idempotency_key=%s", (external_id, ik))
                cur.close()
        except Exception as e:
            logger.error("Bill external_id update failed client=%s: %s", self.client_id, e)

    def _send_pdf_to_channel(self, channel: str, sender: str, pdf_bytes: bytes, data: dict) -> None:
        filename = f"bill_{data.get('invoice_number', 'document')}.pdf"
        caption = f"Bill recorded — {data.get('vendor')} {data.get('currency','USD')} {data.get('amount')}"
        if channel == "telegram":
            from channels.telegram import TelegramChannel
            TelegramChannel(client_id=self.client_id).send_document(
                recipient=sender, document=pdf_bytes, filename=filename, caption=caption)
        elif channel == "whatsapp":
            from channels.whatsapp import WhatsAppChannel
            WhatsAppChannel(client_id=self.client_id).send_document(
                recipient=sender, document=pdf_bytes, filename=filename, caption=caption)