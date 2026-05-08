"""Contain tools backend logic."""
import json
import re
from agents.base_agent import _get_client
from agents.a02_expense.prompts import _EXPENSE_CONFIRMATION_PROMPT,EXPENSE_TOOLS_PROMPT
import logging

logger = logging.getLogger(__name__)
# Maximum input len used by this module.
MAX_INPUT_LEN = 3000

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

def parse_expense_message(message: str, context: str = "") -> dict:
    """Parse expense message."""
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
            max_tokens=300,
            system=EXPENSE_TOOLS_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        for block in response.content:
            if block.type == "text":
                data = _parse_json(block.text)
                if data:
                    data["amount"] = _sanitise_amount(data.get("amount"))
                    data["tax_amount"] = _sanitise_amount(data.get("tax_amount"))
                    return data
    except Exception as e:
        logger.error("parse_expense_message failed: %s", e)
    return {}


def validate_expense(data: dict) -> tuple[bool, str]:
    """Validate expense."""
    from agents.a02_expense.config import EXPENSE_CONFIG

    action = data.get("action", "capture")

    if action not in EXPENSE_CONFIG["valid_actions"]:
        return False, f"Unknown action: {action}"

    if action == "capture":
        if not data.get("vendor"):
            return False, "Please provide the vendor or merchant name"
        if not data.get("amount"):
            return False, "Please provide the expense amount"
        if not data.get("category"):
            return False, (
                f"Please provide a category - one of: "
                f"{', '.join(EXPENSE_CONFIG['valid_categories'])}"
            )
        try:
            float(data["amount"])
        except (ValueError, TypeError):
            return False, "Amount must be a number"
        if data["category"] not in EXPENSE_CONFIG["valid_categories"]:
            return False, (
                f"Invalid category - must be one of: "
                f"{', '.join(EXPENSE_CONFIG['valid_categories'])}"
            )

    if action in ("approve", "reject"):
        if not data.get("reference") and not data.get("vendor"):
            return False, "Please provide the expense reference or vendor name"

    if action == "track":
        if not data.get("reference") and not data.get("vendor"):
            return False, "Please provide the expense reference or vendor name"

    if action == "delete":
        if not data.get("delete_all") and not data.get("reference") and not data.get("vendor"):
            return False, "Please provide the expense reference or vendor name"

    return True, "ok"

def _fmt_amount(currency: str, amount) -> str:
    """Execute fmt amount."""
    try:
        return f"{currency} {float(amount):,.2f}"
    except (ValueError, TypeError):
        return f"{currency} {amount}" if amount else f"{currency} -"

def format_expense_confirmation(action: str, data: dict, result: dict | None = None) -> str:
    """Execute format expense confirmation."""
    result = result or {}
    client_id = data.get("_client_id", "")
    currency = data.get("currency", "USD")
    amount = data.get("amount", "")
    vendor = data.get("vendor") or "unknown"
    category = data.get("category", "N/A")
    ref = data.get("reference") or data.get("idempotency_key", "N/A")
    amount_fmt = _fmt_amount(currency, amount)

    try:
        from integrations.accounting_factory import get_accounting_platform_name
        platform = get_accounting_platform_name(client_id) if client_id else "your accounting platform"
    except Exception:
        platform = "your accounting platform"

    facts: dict = {
        "action": action,
        "vendor": vendor,
        "amount": amount_fmt,
        "category": category,
        "reference": ref,
        "currency": currency,
        "accounting_platform": platform,
    }

    if action == "capture":
        approval_status = result.get("approval_status", "pending")
        threshold = result.get("threshold", "")
        accounting = result.get("accounting", {})
        facts["approval_status"] = approval_status
        facts["auto_approved"] = approval_status == "approved"
        facts["threshold"] = _fmt_amount(currency, threshold) if threshold else None
        facts["synced_to_accounting"] = bool(
            approval_status == "approved" and not accounting.get("queued_for_retry")
        )
        facts["accounting_queued"] = accounting.get("queued_for_retry", False)
        facts["duplicate"] = result.get("status") == "duplicate"

    elif action == "approve":
        facts["approved"] = result.get("approved", False)
        facts["expense_id"] = result.get("expense_id")
        facts["error"] = result.get("error")
        facts["notified_submitter"] = True

    elif action == "reject":
        facts["rejected"] = result.get("rejected", False)
        facts["reason"] = data.get("notes") or result.get("reason")
        facts["error"] = result.get("error")
        facts["notified_submitter"] = True

    elif action == "track":
        facts["approval_status"] = result.get("approval_status", "unknown")
        facts["vendor"] = result.get("vendor", vendor)
        facts["amount"] = _fmt_amount(
            result.get("currency", currency), result.get("amount", amount)
        )
        facts["category"] = result.get("category", category)
        facts["approved_at"] = result.get("approved_at")
        facts["error"] = result.get("error")

    elif action == "list_expenses":
        items = result.get("expenses", [])
        facts["total"] = result.get("total", len(items))
        facts["page"] = result.get("page", 1)
        facts["pages"] = result.get("pages", 1)
        facts["items"] = [
            {
                "vendor": e.get("vendor"),
                "amount": _fmt_amount(e.get("currency", "USD"), e.get("amount", 0)),
                "category": e.get("category"),
                "status": e.get("approval_status"),
            }
            for e in items[:10]
        ]
        facts["error"] = result.get("error")
    elif action == "edit":
        facts["edited"] = result.get("edited", False)
        facts["fields_updated"] = result.get("fields_updated", [])
        facts["error"] = result.get("error")
    elif action == "summary":
        breakdown = result.get("breakdown", [])
        facts["month"] = result.get("month", "")
        facts["total_lines"] = result.get("total_lines", len(breakdown))
        facts["over_budget_categories"] = [
            b["category"] for b in breakdown if b.get("over_budget")
        ]
        facts["breakdown"] = [
            {
                "category": b["category"],
                "total": _fmt_amount(b.get("currency", "USD"), b.get("total", 0)),
                "count": b.get("count", 0),
                "budget_used_pct": b.get("budget_used_pct"),
                "over_budget": b.get("over_budget", False),
            }
            for b in breakdown[:10]
        ]
        facts["error"] = result.get("error")
    elif action == "delete":
        facts["deleted"] = result.get("deleted", False)
        facts["deleted_count"] = result.get("deleted_count", 0)
        facts["scope"] = result.get("scope", "unknown")
        facts["error"] = result.get("error")
    user_message = f"Action completed: {json.dumps(facts, default=str)}"
    try:
        response = _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            system=_EXPENSE_CONFIRMATION_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        for block in response.content:
            if block.type == "text":
                return block.text.strip()
    except Exception as e:
        logger.warning("format_expense_confirmation LLM call failed, using fallback: %s", e)

    return f"Expense {action} completed for {vendor} ({amount_fmt})."