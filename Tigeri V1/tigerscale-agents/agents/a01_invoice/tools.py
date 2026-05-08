"""Contain tools backend logic."""
import json
import re
from agents.base_agent import _get_client
from agents.a01_invoice.prompts import (
    INVOICE_TOOLS_PROMPT,
    INVOICE_PDF_EXTRACTION_PROMPT,
    _CONFIRMATION_PROMPT,
    _PO_CONFIRMATION_PROMPT,
    _BILL_CONFIRMATION_PROMPT,
)

import logging
logger = logging.getLogger(__name__)
# Maximum input len used by this module.
MAX_INPUT_LEN = 3000

_PO_ACTIONS = {
    "po_create", "po_find", "po_list", "po_track",
    "po_edit", "po_approve", "po_send", "po_remind",
    "po_check_overdue", "po_mark_received",
}
_BILL_ACTIONS = {
    "bill_create", "bill_list", "bill_find",
    "bill_track", "bill_edit", "bill_check_overdue",
}
 
def _parse_json(text: str) -> dict:
    """Parse json."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


def _sanitise_amount(raw) -> float | None:
    """Execute sanitise amount."""
    if raw is None:
        return None
    try:
        cleaned = re.sub(r"[^\d.]", "", str(raw).replace(",", ""))
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None


def parse_invoice_message(message: str, is_document: bool = False, context: str = "") -> dict:
    """Parse invoice message."""
    system_prompt = INVOICE_PDF_EXTRACTION_PROMPT if is_document else INVOICE_TOOLS_PROMPT
    message = message[:MAX_INPUT_LEN]
 
    if context and not is_document:
        user_content = (
            f"[Recent conversation:\n{context[:600]}\n]\n\n"
            f"Current message: {message}"
        )
    else:
        user_content = message
 
    try:
        response = _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        for block in response.content:
            if block.type == "text":
                data = _parse_json(block.text)
                if data:
                    line_items = data.get("line_items") or []
                    if line_items:
                        for item in line_items:
                            item["amount"] = _sanitise_amount(item.get("amount"))
                        data["amount"] = sum(
                            float(i["amount"]) for i in line_items if i.get("amount")
                        )
                        if not data.get("description"):
                            data["description"] = ", ".join(
                                i["description"] for i in line_items
                                if i.get("description")
                            )
                    else:
                        data["amount"] = _sanitise_amount(data.get("amount"))
                    data["line_items"] = line_items
                    return data
    except Exception as e:
        logger.error("parse_invoice_message failed: %s", e)
    return {}


def validate_invoice(data: dict) -> tuple[bool, str]:
    """Validate invoice."""
    from agents.a01_invoice.config import INVOICE_CONFIG

    action = data.get("action")

    if not action or str(action).strip().lower() in ("null", "none", ""):
        return False, "__needs_info__: I couldn't understand what you want to do. Try: 'create invoice for Acme USD 500', 'list invoices', or 'check overdue'"

    action = str(action).strip().lower()
    data["action"] = action

    if action not in INVOICE_CONFIG["valid_actions"]:
        return False, "__needs_info__: I couldn't understand what you want to do. Try: 'create invoice for Acme USD 500', 'list invoices', or 'check overdue'"

    if action in ("track", "mark_paid"):
        if not data.get("invoice_number") and not data.get("vendor"):
            return False, "Please provide an invoice number or vendor name"
        return True, "ok"

    if action == "remind":
        if not data.get("invoice_number") and not data.get("vendor"):
            return False, "Please provide the invoice number or vendor name"
        return True, "ok"

    if action in ("list_invoices", "check_overdue", "approve_all"):
        return True, "ok"

    if action == "create":
        missing = []
        if not data.get("vendor"):
            missing.append("vendor/client name")
        if not data.get("amount"):
            missing.append("amount")
        if not data.get("description"):
            missing.append("line item description")
        if missing:
            return False, f"__needs_info__: {', '.join(missing)}"

        if data.get("due_date"):
            resolved, error = _resolve_and_validate_due_date(data["due_date"])
            if error:
                return False, f"__needs_info__: {error}"
            data["due_date"] = resolved

    if action == "send":
        if not data.get("vendor") and not data.get("invoice_number"):
            return False, "Please provide vendor name or invoice number"

    if action == "approve":
        if not data.get("invoice_number") and not data.get("invoice_numbers") and not data.get("vendor"):
            return False, "Please provide an invoice number or vendor name to approve"

    if action == "edit":
        edit_fields = data.get("edit_fields") or {}
        if "due_date" in edit_fields:
            resolved, error = _resolve_and_validate_due_date(edit_fields["due_date"])
            if error:
                return False, f"__needs_info__: {error}"
            edit_fields["due_date"] = resolved

    if data.get("amount") is not None:
        try:
            float(data["amount"])
        except (ValueError, TypeError):
            return False, "Invalid amount — must be a number"

    return True, "ok"


def _build_po_facts(action: str, data: dict, result: dict, client_id: str = "") -> tuple[dict, str]:
    from integrations.accounting_factory import get_accounting_platform_name
    currency = data.get("currency", "USD")
    amount = data.get("amount")
    try:
        amount_fmt = f"{currency} {float(amount):,.2f}" if amount is not None else "unspecified"
    except (ValueError, TypeError):
        amount_fmt = f"{currency} {amount}" if amount else "unspecified"

    platform = get_accounting_platform_name(client_id) if client_id else "your accounting platform"

    facts: dict = {
        "action": action,
        "vendor": data.get("vendor") or "unknown",
        "amount": amount_fmt,
        "po_number": data.get("po_number") or result.get("po_number") or "pending",
        "currency": currency,
        "description": data.get("description") or "N/A",
        "accounting_platform": platform,
    }

    if action == "po_create":
        facts["queued"] = result.get("queued_for_retry", False)
        facts["duplicate"] = result.get("status") == "duplicate"
        facts["pdf_attached"] = result.get("pdf") is not None
        facts["error"] = result.get("error")

    elif action == "po_find":
        po = result.get("po", {})
        facts["po_number"] = po.get("po_number") or data.get("po_number") or "N/A"
        facts["vendor"] = po.get("vendor") or facts["vendor"]
        facts["amount"] = po.get("amount") or amount_fmt
        facts["status"] = po.get("status", "N/A")
        facts["found"] = result.get("status") == "success"

    elif action == "po_list":
        items = result.get("purchase_orders", [])
        facts["total"] = result.get("total", len(items))
        facts["status_filter"] = data.get("status_filter")
        facts["vendor_filter"] = data.get("vendor_filter")
        facts["items"] = [
            {
                "po_number": i.get("po_number") or "N/A",
                "vendor": i.get("vendor"),
                "amount": f"{i.get('currency','USD')} {float(i.get('amount', 0)):,.2f}",
                "status": i.get("status"),
            }
            for i in items[:5]
        ]
    elif action == "po_track":
        facts["status"] = result.get("status", "unknown")
        facts["delivery_date"] = result.get("delivery_date", "N/A")
        facts["error"] = result.get("error")
 
    elif action == "po_edit":
        facts["edited"] = result.get("edited", False)
        facts["fields_updated"] = result.get("fields_updated", [])
        facts["accounting_warning"] = result.get("accounting_warning")
        facts["error"] = result.get("error")
        for field in result.get("fields_updated", []):
            if field in data:
                facts[f"new_{field}"] = data[field]
 
    elif action == "po_approve":
        facts["approved"] = result.get("status") == "success"
        facts["error"] = result.get("error")
 
    elif action == "po_remind":
        facts["sent"] = result.get("reminder_sent", False)
        facts["recipient"] = result.get("recipient")
        facts["error"] = result.get("error")
 
    elif action == "po_check_overdue":
        items = result.get("purchase_orders", [])
        facts["count"] = len(items)
        facts["items"] = [
            {
                "po_number": i.get("po_number") or "N/A",
                "vendor": i.get("vendor"),
                "amount": f"{i.get('currency','USD')} {float(i.get('amount', 0)):,.2f}",
                "days_overdue": i.get("days_overdue", 0),
            }
            for i in items[:5]
        ]
 
    elif action == "po_mark_received":
        facts["received"] = result.get("received", False)
        facts["error"] = result.get("error")
 
    return facts, _PO_CONFIRMATION_PROMPT


def _build_bill_facts(action: str, data: dict, result: dict, client_id: str = "") -> tuple[dict, str]:
    from integrations.accounting_factory import get_accounting_platform_name
    currency = data.get("currency", "USD")
    amount = data.get("amount")
    try:
        amount_fmt = f"{currency} {float(amount):,.2f}" if amount is not None else "unspecified"
    except (ValueError, TypeError):
        amount_fmt = f"{currency} {amount}" if amount else "unspecified"

    platform = get_accounting_platform_name(client_id) if client_id else "your accounting platform"

    facts: dict = {
        "action": action,
        "vendor": data.get("vendor") or "unknown",
        "amount": amount_fmt,
        "invoice_ref": data.get("invoice_number") or "N/A",
        "po_number": data.get("po_number") or "N/A",
        "due_date": data.get("due_date") or "not set",
        "currency": currency,
        "accounting_platform": platform,
    }

    if action == "bill_create":
        facts["duplicate"] = result.get("status") == "duplicate"
        facts["po_missing"] = result.get("status") == "po_required"
        facts["error"] = result.get("error")
        facts["pdf_attached"] = result.get("pdf") is not None
    elif action == "bill_list":
        items = result.get("bills", [])
        facts["total"] = result.get("total", len(items))
        facts["status_filter"] = data.get("status_filter")
        facts["vendor_filter"] = data.get("vendor_filter")
        facts["items"] = [
            {
                "vendor": i.get("vendor"),
                "amount": f"{i.get('currency','USD')} {float(i.get('amount', 0)):,.2f}",
                "status": i.get("status"),
                "invoice_number": i.get("invoice_number") or "N/A",
            }
            for i in items[:5]
        ]
 
    elif action == "bill_find":
        bill = result.get("bill", {})
        facts["found"] = result.get("status") == "success"
        facts["status"] = bill.get("status", "N/A")
        facts["amount"] = bill.get("amount") or amount_fmt
 
    elif action == "bill_track":
        facts["status"] = result.get("status", "unknown")
        facts["due_date"] = result.get("due_date", "N/A")
        facts["error"] = result.get("error")
 
    elif action == "bill_edit":
        facts["edited"] = result.get("edited", False)
        facts["fields_updated"] = result.get("fields_updated", [])
        facts["error"] = result.get("error")
 
    elif action == "bill_check_overdue":
        items = result.get("bills", [])
        facts["count"] = len(items)
        try:
            facts["total_outstanding"] = f"{currency} {float(result.get('total_outstanding', 0)):,.2f}"
        except (ValueError, TypeError):
            facts["total_outstanding"] = str(result.get("total_outstanding", 0))
        facts["items"] = [
            {
                "vendor": i.get("vendor"),
                "amount": f"{i.get('currency','USD')} {float(i.get('amount', 0)):,.2f}",
                "days_overdue": i.get("days_overdue", 0),
            }
            for i in items[:5]
        ]
 
    return facts, _BILL_CONFIRMATION_PROMPT


def format_invoice_confirmation(action: str, data: dict, result: dict | None = None) -> str:
    """Execute format invoice confirmation."""
    result = result or {}
    client_id = data.get("_client_id", "")

    if action in _PO_ACTIONS:
        facts, system_prompt = _build_po_facts(action, data, result, client_id)
    elif action in _BILL_ACTIONS:
        facts, system_prompt = _build_bill_facts(action, data, result, client_id)
    else:
        facts, system_prompt = _build_invoice_facts(action, data, result, client_id)

    user_message = f"Action completed: {json.dumps(facts, default=str)}"

    try:
        response = _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        for block in response.content:
            if block.type == "text":
                return block.text.strip()
    except Exception as e:
        logger.warning("format_invoice_confirmation LLM call failed, using fallback: %s", e)

    vendor = facts.get("vendor", "unknown")
    amount = facts.get("amount", "unspecified")
    return f"{action.replace('_', ' ').title()} completed for {vendor} ({amount})."


def _build_invoice_facts(action: str, data: dict, result: dict, client_id: str = "") -> tuple[dict, str]:
    from integrations.accounting_factory import get_accounting_platform_name
    currency = data.get("currency", "USD")
    amount = data.get("amount")
    try:
        amount_fmt = f"{currency} {float(amount):,.2f}" if amount is not None else "unspecified"
    except (ValueError, TypeError):
        amount_fmt = f"{currency} {amount}" if amount else "unspecified"

    platform = get_accounting_platform_name(client_id) if client_id else "your accounting platform"
    facts: dict = {
        "action": action,
        "vendor": data.get("vendor") or "unknown",
        "amount": amount_fmt,
        "invoice_number": data.get("invoice_number") or "pending",
        "due_date": data.get("due_date") or "not set",
        "currency": currency,
        "accounting_platform": platform,
    }

    if action == "create":
        accounting = result.get("accounting", {})
        synced_number = (
            accounting.get("InvoiceNumber") or accounting.get("DocNumber")
            or facts["invoice_number"]
        )
        facts["synced_number"] = synced_number
        facts["queued"] = accounting.get("queued_for_retry", False)
        facts["duplicate"] = False

    elif action == "send":
        facts["email_sent"] = result.get("email_sent", False)
        facts["recipient"] = data.get("recipient_email")
        facts["accounting_error"] = result.get("accounting_error")
        facts["email_error"] = result.get("email_error")

    elif action == "track":
        facts["status"] = result.get("status", "unknown")
        facts["amount"] = result.get("amount") or amount_fmt
        facts["due_date"] = result.get("due_date") or facts["due_date"]
        facts["reminder_count"] = result.get("reminder_count", 0)
        facts["error"] = result.get("error")

    elif action == "remind":
        facts["sent"] = result.get("reminder_sent", False)
        facts["recipient"] = result.get("recipient") or data.get("recipient_email")
        facts["error"] = result.get("error")

    elif action == "mark_paid":
        facts["error"] = result.get("error")
        facts["accounting_warning"] = result.get("accounting_warning")
        facts["xero_auth_required"] = (
            "Authorised" in str(result.get("error", ""))
            or "authorised" in str(result.get("error", ""))
        )
        if data.get("amount") is not None:
            try:
                facts["amount"] = f"{currency} {float(data['amount']):,.2f}"
            except (ValueError, TypeError):
                pass

    elif action == "approve":
        facts["approved"] = result.get("approved", False)
        facts["invoice_id"] = result.get("invoice_id")
        facts["error"] = result.get("error")
        if result.get("batch_approved"):
            facts["batch_approved"] = True
            facts["approved_count"] = result.get("approved_count", 0)
            facts["failed_count"] = result.get("failed_count", 0)
            facts["failed"] = result.get("failed", [])

    elif action == "approve_all":
        facts["batch_approved"] = result.get("batch_approved", False)
        facts["approved_count"] = result.get("approved_count", 0)
        facts["failed_count"] = result.get("failed_count", 0)
        facts["failed"] = result.get("failed", [])
        facts["error"] = result.get("error")

    elif action == "edit":
        edit_fields = data.get("edit_fields") or {}
        facts["edited"] = result.get("edited", False)
        facts["fields_updated"] = result.get("fields_updated", [])
        facts["accounting_warning"] = result.get("accounting_warning")
        facts["error"] = result.get("error")
        # pull real updated values so confirmation shows correct numbers
        for field, value in edit_fields.items():
            facts[f"new_{field}"] = value
        if "amount" in edit_fields:
            try:
                facts["amount"] = f"{currency} {float(edit_fields['amount']):,.2f}"
            except (ValueError, TypeError):
                pass
        if "line_items" in edit_fields:
            try:
                total = sum(float(i.get("amount", 0)) for i in edit_fields["line_items"] if i.get("amount"))
                facts["amount"] = f"{currency} {total:,.2f}"
            except (ValueError, TypeError):
                pass

    elif action == "list_invoices":
        items = result.get("invoices", [])
        facts["total"] = result.get("total", len(items))
        facts["vendor_filter"] = data.get("vendor_filter")
        facts["items"] = [
            {
                "invoice_number": i.get("invoice_number") or "Pending",
                "vendor": i.get("vendor"),
                "amount": f"{i.get('currency','USD')} {float(i.get('amount', 0)):,.2f}",
                "status": i.get("status"),
            }
            for i in items[:5]
        ]

    elif action == "check_overdue":
        items = result.get("invoices", [])
        facts["count"] = len(items)
        try:
            facts["total_outstanding"] = f"USD {float(result.get('total_outstanding', 0)):,.2f}"
        except (ValueError, TypeError):
            facts["total_outstanding"] = str(result.get("total_outstanding", 0))
        facts["items"] = [
            {
                "invoice_number": i.get("invoice_number") or "Pending",
                "vendor": i.get("vendor"),
                "amount": f"{i.get('currency','USD')} {float(i.get('amount', 0)):,.2f}",
                "days_overdue": i.get("days_overdue", 0),
            }
            for i in items[:5]
        ]

    return facts, _CONFIRMATION_PROMPT


def format_email_body(data: dict, pdf_attached: bool = False) -> tuple[str, str]:
    inv_num = data.get("invoice_number") or "N/A"
    vendor = data.get("vendor") or "Valued Customer"
    amount = data.get("amount")
    currency = data.get("currency", "USD")
    due_date = data.get("due_date") or "Not set"

    try:
        amount_fmt = f"{currency} {float(amount):,.2f}" if amount else "N/A"
    except (ValueError, TypeError):
        amount_fmt = f"{currency} {amount}"

    plain = (
        f"Dear {vendor},\n\n"
        f"Please find {'attached ' if pdf_attached else ''}invoice {inv_num}.\n\n"
        f"Amount Due : {amount_fmt}\n"
        f"Due Date   : {due_date}\n\n"
        f"Please arrange payment by the due date.\n"
        f"If you have any questions, reply to this email.\n\n"
        f"Kind regards"
    )

    html = (
        f'<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto;">'
        f'<div style="background:#f9f9f9;padding:24px;border-radius:8px;">'
        f'<h2 style="color:#2c3e50;margin-bottom:4px;">Invoice {inv_num}</h2>'
        f'<p>Dear <strong>{vendor}</strong>,</p>'
        f'<p>Please find {"the attached " if pdf_attached else ""}invoice details below.</p>'
        f'<table style="width:100%;border-collapse:collapse;margin:20px 0;">'
        f'<tr style="background:#fff;border-bottom:1px solid #e0e0e0;">'
        f'<td style="padding:12px;font-weight:bold;width:40%;">Invoice Number</td>'
        f'<td style="padding:12px;">{inv_num}</td></tr>'
        f'<tr style="background:#f4f4f4;border-bottom:1px solid #e0e0e0;">'
        f'<td style="padding:12px;font-weight:bold;">Amount Due</td>'
        f'<td style="padding:12px;color:#2980b9;font-size:18px;"><strong>{amount_fmt}</strong></td></tr>'
        f'<tr style="background:#fff;">'
        f'<td style="padding:12px;font-weight:bold;">Due Date</td>'
        f'<td style="padding:12px;">{due_date}</td></tr>'
        f'</table>'
        f'<p>Please arrange payment by the due date.<br>'
        f'If you have any questions, reply to this email.</p>'
        f'<hr style="border:none;border-top:1px solid #e0e0e0;margin:20px 0;">'
        f'<p style="font-size:11px;color:#aaa;">This is an automated invoice notification.</p>'
        f'</div></body></html>'
    )

    return plain, html


def _resolve_and_validate_due_date(due_date: str | None) -> tuple[str | None, str | None]:
    from datetime import date, timedelta
    import dateparser

    if not due_date or str(due_date).lower() in ("not set", "none", "null", ""):
        return None, None

    today = date.today()

    parsed_dt = dateparser.parse(
        str(due_date),
        settings={
            "PREFER_DATES_FROM": "future",
            "PREFER_DAY_OF_MONTH": "first",
            "RETURN_AS_TIMEZONE_AWARE": False,
            "RELATIVE_BASE": __import__("datetime").datetime.combine(
                today, __import__("datetime").time.min
            ),
        },
    )

    if not parsed_dt:
        return None, (
            f"Could not understand due date '{due_date}' — "
            f"use format YYYY-MM-DD or '15 June 2026'"
        )

    parsed = parsed_dt.date()

    if parsed < today:
        for years_ahead in (1, 2):
            candidate = parsed.replace(year=parsed.year + years_ahead)
            if candidate >= today:
                parsed = candidate
                break

    if parsed < today:
        return None, (
            f"Due date {parsed.isoformat()} is in the past "
            f"(today is {today.isoformat()}). "
            f"Please provide a future date, e.g. "
            f"'{(today + timedelta(days=30)).isoformat()}'"
        )

    return parsed.isoformat(), None
def parse_po_message(message: str, context: str = "") -> dict:
    """Parse PO message with full context support."""
    from agents.a01_invoice.prompts import PO_AGENT_PROMPT
    message = message[:MAX_INPUT_LEN]
 
    if context:
        user_content = (
            f"[Recent conversation:\n{context[:600]}\n]\n\n"
            f"Current message: {message}"
        )
    else:
        user_content = message
 
    try:
        response = _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=700,
            system=PO_AGENT_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        for block in response.content:
            if block.type == "text":
                data = _parse_json(block.text)
                if data:
                    line_items = data.get("line_items") or []
                    if line_items:
                        for item in line_items:
                            item["amount"] = _sanitise_amount(item.get("amount"))
                        data["amount"] = sum(
                            float(i["amount"]) * float(i.get("quantity", 1))
                            for i in line_items if i.get("amount")
                        )
                        if not data.get("description"):
                            data["description"] = ", ".join(
                                i["description"] for i in line_items
                                if i.get("description")
                            )
                    else:
                        data["amount"] = _sanitise_amount(data.get("amount"))
                    data["line_items"] = line_items
                    return data
    except Exception as e:
        logger.error("parse_po_message failed: %s", e)
    return {}

def parse_bill_message(message: str, is_document: bool = False, context: str = "") -> dict:
    """Parse bill message with full context support."""
    from agents.a01_invoice.prompts import BILL_AGENT_PROMPT
    message = message[:MAX_INPUT_LEN]
 
    system_prompt = BILL_AGENT_PROMPT
 
    if context and not is_document:
        user_content = (
            f"[Recent conversation:\n{context[:600]}\n]\n\n"
            f"Current message: {message}"
        )
    else:
        user_content = message
 
    try:
        response = _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        for block in response.content:
            if block.type == "text":
                data = _parse_json(block.text)
                if data:
                    data["amount"] = _sanitise_amount(data.get("amount"))
                    return data
    except Exception as e:
        logger.error("parse_bill_message failed: %s", e)
    return {}