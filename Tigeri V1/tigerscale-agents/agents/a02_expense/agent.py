"""Contain agent backend logic."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
from datetime import date

from agents.a02_expense.config import EXPENSE_CONFIG
from agents.a02_expense.prompts import EXPENSE_AGENT_PROMPT, RECEIPT_PARSE_PROMPT
from agents.a02_expense.tools import (
    format_expense_confirmation,
    parse_expense_message,
    validate_expense,
)
from agents.base_agent import BaseAgent
from agents.base_tools import EXPENSE_TOOLS
from anthropic.types import MessageParam
from config.db_pool import get_conn
from config.client_config import (
    get_client_financial_config,
    get_employee_from_sender,
    get_net_amount,
    resolve_category_from_code,
)
from integrations.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    QuickBooksValidationError,
    XeroValidationError,
    _is_non_retryable,
)
from core.context_builder import build_context, format_for_llm
from integrations.accounting_factory import get_system_from_config
from memory.agent_memory import recall_memory, save_memory
from memory.rag import retrieve_knowledge
from security.audit import log_action

logger = logging.getLogger(__name__)

_VALID_STATUS_FILTERS   = {"pending", "approved", "rejected"}
_VALID_CATEGORY_FILTERS = set(EXPENSE_CONFIG["valid_categories"])
_DEFAULT_CURRENCY       = EXPENSE_CONFIG["default_currency"]

_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_ALLOWED_DOCUMENT_TYPES = _ALLOWED_IMAGE_TYPES | {"application/pdf"}

_RECEIPT_CONFIDENCE_SKIP_LLM = 0.85


def _normalize_expense_intent_overrides(message: str, data: dict) -> dict:
    """Apply deterministic overrides for common expense intents and typos."""
    lower = (message or "").lower()

    if any(k in lower for k in ("delete all my expenses", "delete all expenses", "remove all my expenses", "clear all my expenses", "clear expenses")):
        data["action"] = "delete"
        data["delete_all"] = True
        return data

    if ("delete" in lower or "remove" in lower or "clear" in lower) and ("expense" in lower or "expenses" in lower or "expence" in lower or "expences" in lower):
        data["action"] = "delete"
        data.setdefault("delete_all", False)
    m = re.search(r"what\s+is\s+([a-z0-9 .,&'-]+?)'?s\s+expense", lower)
    if m:
        data["action"] = "list_expenses"
        data["vendor_filter"] = m.group(1).strip().title()

    return data



def _extract_image_from_task(task: dict) -> tuple[bytes | None, str]:
    """
    Pull raw image bytes + media_type from any task shape.
    Returns (bytes, media_type) or (None, "").
    Validates size and type before returning.
    """
    raw, media_type = None, "image/jpeg"

    for key in ("image", "image_data", "receipt_image"):
        val = task.get(key)
        if val:
            raw = val
            media_type = (
                task.get("media_type")
                or task.get("image_media_type")
                or "image/jpeg"
            )
            break

    if raw is None:
        file_bytes = task.get("file_bytes")
        mime = task.get("mime_type", "")
        if file_bytes and mime in _ALLOWED_DOCUMENT_TYPES:
            raw = file_bytes
            media_type = mime

    if raw is None:
        att = task.get("attachment")
        if isinstance(att, dict) and att.get("data"):
            raw = att["data"]
            media_type = att.get("media_type", "image/jpeg")

    if raw is None:
        for att in task.get("attachments") or []:
            if isinstance(att, dict) and att.get("media_type", "") in _ALLOWED_DOCUMENT_TYPES:
                raw = att.get("data")
                media_type = att.get("media_type", "image/jpeg")
                break

    if raw is None:
        return None, ""

    if isinstance(raw, bytes):
        file_bytes = raw
    else:
        s = str(raw)
        if "," in s:
            s = s.split(",", 1)[1]
        try:
            file_bytes = base64.b64decode(s)
        except Exception:
            logger.warning("Could not decode file data — skipping receipt parse")
            return None, ""

    if media_type not in _ALLOWED_DOCUMENT_TYPES:
        logger.warning("Unsupported media_type=%s — skipping receipt parse", media_type)
        return None, ""

    if len(file_bytes) > _MAX_IMAGE_BYTES and media_type != "application/pdf":
        logger.warning("File too large (%d bytes) — skipping receipt parse", len(file_bytes))
        return None, ""

    if media_type == "application/pdf":
        try:
            from agents.utils.document_extractor import pdf_to_image_bytes
            file_bytes, media_type = pdf_to_image_bytes(file_bytes)
        except Exception as exc:
            logger.warning("PDF to image conversion failed - skipping vision: %s", exc)
            return None, ""

    return file_bytes, media_type


def _parse_receipt_vision(
    client_id: str,
    image_bytes: bytes,
    media_type: str,
) -> dict:
    from typing import Literal, cast
    from agents.base_agent import _get_client
    from agents.utils.document_extractor import enrich_vision_prompt

    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    _media_type = cast(
        Literal["image/jpeg", "image/png", "image/gif", "image/webp"],
        media_type,
    )
    enriched_prompt = enrich_vision_prompt(RECEIPT_PARSE_PROMPT, client_id)

    vision_messages: list[MessageParam] = cast(
        list[MessageParam],
        [{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type":       "base64",
                        "media_type": _media_type,
                        "data":       image_b64,
                    },
                },
                {
                    "type": "text",
                    "text": "Extract the expense details from this receipt.",
                },
            ],
        }],
    )

    for model, max_tok in [("claude-sonnet-4-6", 4096), ("claude-haiku-4-5-20251001", 4096)]:
        try:
            response = _get_client().messages.create(
                model=model,
                max_tokens=max_tok,
                system=enriched_prompt,
                messages=vision_messages,
            )
        except Exception as exc:
            logger.warning("Receipt vision API call failed model=%s client=%s: %s", model, client_id, exc)
            continue

        for block in response.content:
            if block.type != "text":
                continue
            text = block.text.strip()
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text).strip()

            import re as _re
            match = _re.search(r'\{.*\}', text, _re.DOTALL)
            if not match:
                continue

            try:
                parsed = json.loads(match.group())
            except json.JSONDecodeError:
                continue

            for field in ("amount", "tax_amount"):
                val = parsed.get(field)
                if val is not None:
                    try:
                        cleaned = re.sub(r"[^\d.]", "", str(val).replace(",", ""))
                        parsed[field] = float(cleaned) if cleaned else None
                    except (ValueError, TypeError):
                        parsed[field] = None

            claim_code = parsed.get("claim_code") or parsed.get("category_code")
            if claim_code:
                resolved = resolve_category_from_code(client_id, claim_code)
                if resolved:
                    parsed["category"] = resolved

            return parsed

    return {}


def _build_receipt_idempotency_key(client_id: str, receipt_data: dict, image_bytes: bytes) -> str:
    """
    Build idempotency key from receipt content so two different receipts
    sent with the same caption ("add to expenses") never collide,
    and the same receipt sent twice is correctly deduped.
    """
    vendor = (receipt_data.get("vendor") or "").strip().lower()
    amount = str(receipt_data.get("amount") or "")
    dt     = str(receipt_data.get("date") or "")

    if vendor and amount:
        raw = f"receipt:{client_id}:{vendor}:{amount}:{dt}"
    else:
        raw = f"receipt:{client_id}:{hashlib.sha256(image_bytes).hexdigest()}"

    return hashlib.sha256(raw.encode()).hexdigest()


class ExpenseAgent(BaseAgent):
    """Represent the ExpenseAgent component and its related behavior."""
    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        super().__init__(client_id)
        self.confidence_threshold = EXPENSE_CONFIG["confidence_threshold"]
        self._accounting_cb = CircuitBreaker(f"accounting_expense:{client_id}")

    def get_system_prompt(self) -> str:
        """Return system prompt."""
        return EXPENSE_AGENT_PROMPT

    def get_tools(self) -> list[dict]:
        return EXPENSE_TOOLS

    def execute_tool(self, tool_name: str, tool_input: dict) -> dict:
        """Dispatch tool calls from the run_loop to the matching _action_* method."""
        meta = {
            "_sender":    tool_input.pop("_sender", ""),
            "_channel":   tool_input.pop("_channel", "telegram"),
            "_client_id": tool_input.pop("_client_id", self.client_id),
            "_task_id":   tool_input.pop("_task_id", ""),
        }

        dispatch = {
            "capture_expense":  self._tool_capture_expense,
            "approve_expense":  self._tool_approve_expense,
            "reject_expense":   self._tool_reject_expense,
            "list_expenses":    self._tool_list_expenses,
            "expense_summary":  self._tool_expense_summary,
            "track_expense":    self._tool_track_expense,
            "edit_expense":     self._tool_edit_expense,
            "delete_expense":   self._tool_delete_expense,
        }

        handler = dispatch.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            return handler(tool_input, meta)
        except Exception as exc:
            logger.error("execute_tool %s failed client=%s: %s", tool_name, self.client_id, exc)
            return {"error": str(exc)}

    def _tool_capture_expense(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":           "capture",
            "vendor":           inp.get("vendor"),
            "amount":           inp.get("amount"),
            "currency":         inp.get("currency", _DEFAULT_CURRENCY),
            "category":         inp.get("category", "ops"),
            "date":             inp.get("date"),
            "notes":            inp.get("notes"),
            "receipt_url":      inp.get("receipt_url"),
            "idempotency_key":  hashlib.sha256(
                f"{self.client_id}:{inp.get('vendor')}:{inp.get('amount')}:{inp.get('date')}".encode()
            ).hexdigest(),
            "confidence":       0.95,
        }
        result = self._action_capture(data)
        result["action"] = "capture"
        return result

    def _tool_approve_expense(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":    "approve",
            "vendor":    inp.get("vendor"),
            "reference": inp.get("reference"),
        }
        result = self._action_approve(data)
        result["action"] = "approve"
        return result

    def _tool_reject_expense(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":    "reject",
            "vendor":    inp.get("vendor"),
            "reference": inp.get("reference"),
            "notes":     inp.get("reason"),
        }
        result = self._action_reject(data)
        result["action"] = "reject"
        return result

    def _tool_list_expenses(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":          "list_expenses",
            "status_filter":   inp.get("status_filter"),
            "category_filter": inp.get("category_filter"),
            "vendor_filter":   inp.get("vendor_filter"),
            "month":           inp.get("month"),
        }
        result = self._action_list_expenses(data)
        result["action"] = "list_expenses"
        return result

    def _tool_expense_summary(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":     "summary",
            "month":      inp.get("month"),
            "month_from": inp.get("month_from"),
            "month_to":   inp.get("month_to"),
        }
        result = self._action_summary(data)
        result["action"] = "summary"
        return result

    def _tool_track_expense(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":    "track",
            "vendor":    inp.get("vendor"),
            "reference": inp.get("reference"),
        }
        result = self._action_track(data)
        result["action"] = "track"
        return result

    def _tool_edit_expense(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":      "edit",
            "vendor":      inp.get("vendor"),
            "reference":   inp.get("reference"),
            "edit_fields": inp.get("edit_fields", {}),
        }
        result = self._action_edit(data)
        result["action"] = "edit"
        return result

    def _tool_delete_expense(self, inp: dict, meta: dict) -> dict:
        data = {
            "action":     "delete",
            "vendor":     inp.get("vendor"),
            "reference":  inp.get("reference"),
            "delete_all": inp.get("delete_all", False),
        }
        result = self._action_delete(data)
        result["action"] = "delete"
        return result

    def _run(self, task: dict) -> dict:
        message = task.get("message", "")
        sender = task.get("sender", "")
        channel = task.get("channel", "telegram")

        receipt_data: dict = {}
        image_bytes, media_type = _extract_image_from_task(task)

        if image_bytes:
            receipt_data = _parse_receipt_vision(self.client_id, image_bytes, media_type)

        if image_bytes and receipt_data:
            idempotency_key = _build_receipt_idempotency_key(
                self.client_id, receipt_data, image_bytes
            )
        else:
            idempotency_key = hashlib.sha256(
                f"{self.client_id}:{message}".encode()
            ).hexdigest()

        receipt_conf = float(receipt_data.get("confidence", 0.0)) if receipt_data else 0.0

        if receipt_data and receipt_conf >= self.confidence_threshold:
            data = {
                "action":           "capture",
                "vendor":           receipt_data.get("vendor"),
                "amount":           receipt_data.get("amount"),
                "tax_amount":       receipt_data.get("tax_amount"),
                "currency":         receipt_data.get("currency"),
                "date":             receipt_data.get("date"),
                "category":         receipt_data.get("category"),
                "notes":            receipt_data.get("notes"),
                "confidence":       receipt_conf,
                "reference":        None,
                "project_code":     None,
                "receipt_url":      None,
                "recipient_email":  None,
                "edit_fields":      None,
                "month":            None,
                "month_from":       None,
                "month_to":         None,
            }
        else:
            ctx_str = ""
            try:
                from core.conversation import _build_enriched_message, _get_context
                ctx_turns = _get_context(sender, self.client_id)
                ctx_str = _build_enriched_message(
                    message, ctx_turns,
                    sender=sender,
                    client_id=self.client_id,
                    domain="expense",
                )
            except Exception:
                pass
            try:
                data = parse_expense_message(message, context=ctx_str)
            except Exception as exc:
                logger.error("parse_expense_message failed client=%s: %s", self.client_id, exc)
                result = {
                    "status":  "error",
                    "message": "Something went wrong reading your request — please try again.",
                }
                log_action(
                    self.client_id, "a02_expense", "expense", message, result, "error",
                    message="parse_expense_message raised",
                )
                return result

            if receipt_data:
                data.setdefault("action", "capture")
                for field in ("vendor", "amount", "tax_amount", "currency", "date", "category"):
                    if receipt_data.get(field) is not None:
                        data[field] = receipt_data[field]
                if not data.get("notes") and receipt_data.get("notes") is not None:
                    data["notes"] = receipt_data["notes"]
                if receipt_conf > float(data.get("confidence", 0.0)):
                    data["confidence"] = receipt_conf

            data = _normalize_expense_intent_overrides(message, data)

        employee = get_employee_from_sender(self.client_id, sender, channel)
        if employee:
            data.setdefault("employee_name", employee.get("name", ""))
            data.setdefault("employee_id",   employee.get("id", ""))
            data.setdefault("department",    employee.get("dept", ""))

        data["idempotency_key"] = idempotency_key

        is_valid, reason = validate_expense(data)
        if not is_valid:
            result = {"status": "needs_info", "message": reason}
            log_action(
                self.client_id, "a02_expense", "expense", message, result, "needs_info",
                message=f"Validation failed - {reason}",
            )
            return result

        action = data.get("action", "capture")
        vendor = data.get("vendor", "")

        skip_llm = receipt_conf >= _RECEIPT_CONFIDENCE_SKIP_LLM
        if not skip_llm and not image_bytes:
            memory    = recall_memory(self.client_id, "a02_expense", message)
            knowledge = retrieve_knowledge(self.client_id, message, "expense")
            context   = build_context(
                task=message, memory=memory, knowledge=knowledge,
                client_id=self.client_id, entity=vendor,
            )
            try:
                raw      = self.call_llm(task=format_for_llm(context), intent="expense")
                llm_data = self.parse_llm_json(raw)
            except json.JSONDecodeError:
                result = {
                    "status":  "error",
                    "message": "Could not parse your expense details — please try again.",
                }
                log_action(
                    self.client_id, "a02_expense", "expense", message, result, "error",
                    message="LLM parse failed",
                )
                return result
            except Exception as exc:
                logger.error("LLM call failed client=%s: %s", self.client_id, exc)
                result = {
                    "status":  "error",
                    "message": "Request processing failed — please try again.",
                }
                log_action(
                    self.client_id, "a02_expense", "expense", message, result, "error",
                    message=f"LLM call failed — {exc}",
                )
                return result

            NEVER_OVERRIDE = {"amount", "vendor", "currency", "action", "category", "date", "tax_amount"}
            for key, value in llm_data.items():
                if key not in NEVER_OVERRIDE and not data.get(key):
                    data[key] = value

        confidence = float(data.get("confidence", 0.0))
        if confidence < self.confidence_threshold:
            result = {
                "status":  "escalate",
                "message": "I need more details — please provide vendor, amount, and category.",
                "raw":     data,
            }
            log_action(
                self.client_id, "a02_expense", "expense", message, result, "escalate",
                message=f"Low confidence ({confidence})",
            )
            return result

        raw_amount  = float(data.get("amount") or 0)
        tax_amount  = data.get("tax_amount")
        net_amount  = get_net_amount(self.client_id, raw_amount, tax_amount)
        if net_amount != raw_amount:
            data["amount_gross"] = raw_amount   # preserve original for display
            data["amount"]       = net_amount   # post net to accounting

        # --- FX conversion ---
        from_currency = (data.get("currency") or "").upper()
        if from_currency:
            try:
                from agents.utils.document_extractor import to_base_currency
                converted, rate = to_base_currency(raw_amount, from_currency, self.client_id)
                if rate != 1.0:
                    data["amount_original"]          = raw_amount
                    data["currency_original"]        = from_currency
                    data["exchange_rate"]            = rate
                    fc = get_client_financial_config(self.client_id)
                    data["currency"] = fc.get("base_currency", from_currency)
                    data["amount"]   = converted
            except Exception as exc:
                logger.warning("FX conversion non-fatal client=%s: %s", self.client_id, exc)

        data["_client_id"] = self.client_id
        result_data = self._execute_action(action, data)

        if result_data.get("error"):
            result = {"status": "error", "message": result_data["error"]}
            log_action(
                self.client_id, "a02_expense", "expense", message, result, "error",
                message=f"{action} failed - {result_data['error']}",
            )
            return result

        if vendor and action in ("capture", "approve"):
            self.record_entity(
                entity_name=vendor,
                domain="expense",
                amount=float(data.get("amount") or 0),
                currency=data.get("currency", _DEFAULT_CURRENCY),
            )

        try:
            save_memory(
                self.client_id, "a02_expense",
                f"Expense {action} for {vendor} amount {data.get('amount')} "
                f"{data.get('currency', _DEFAULT_CURRENCY)} category {data.get('category')}",
            )
        except Exception as e:
            logger.warning("save_memory non-fatal client=%s: %s", self.client_id, e)

        result = {
            "status":  "success",
            "message": format_expense_confirmation(action, data, result_data),
            "action":  action,
            "expense": data,
            "result":  result_data,
        }
        log_action(
            self.client_id, "a02_expense", "expense", message, result, "success",
            message=f"Expense {action} for {vendor} - "
                    f"{data.get('currency', 'USD')} {data.get('amount')} ({data.get('category')})",
        )
        return result

    def _execute_action(self, action: str, data: dict) -> dict:
        handler = getattr(self, f"_action_{action}", None)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        return handler(data)

    def _action_capture(self, data: dict) -> dict:
        auto_approve = EXPENSE_CONFIG.get("auto_approve_all", True)
        try:
            from config.client_config import get_client_config
            config = get_client_config(self.client_id)
            if "expense_auto_approve" in config:
                auto_approve = bool(config["expense_auto_approve"])
            fc = get_client_financial_config(self.client_id)
            if "auto_approve_expenses" in fc:
                auto_approve = bool(fc["auto_approve_expenses"])
        except Exception:
            pass

        data["approval_status"] = "approved" if auto_approve else "pending"

        if data["approval_status"] == "approved":
            accounting = self._post_to_accounting(data)

            if accounting.get("error") and not accounting.get("queued_for_retry"):
                return {
                    "error": f"Could not post to accounting: {accounting['error']}"
                }

            if accounting.get("queued_for_retry"):
                data["approval_status"] = "pending"
                saved = self._save_to_db(data)
                if not saved:
                    return {"status": "duplicate", "error": "Expense already recorded"}
                return {"approval_status": "pending", "accounting": accounting}

            saved = self._save_to_db(data)
            if not saved:
                return {"status": "duplicate", "error": "Expense already recorded"}

            recipient = data.get("recipient_email") or ""
            if recipient and "@" in recipient and "." in recipient:
                self._notify_submitter(data, "approved")
            return {"approval_status": "approved", "accounting": accounting}

        saved = self._save_to_db(data)
        if not saved:
            return {"status": "duplicate", "error": "Expense already recorded"}

        self._notify_approver(data)
        return {"approval_status": "pending"}

    def _action_approve(self, data: dict) -> dict:
        """Approve a pending expense — platform first, DB only on success."""
        reference = data.get("reference")
        vendor    = data.get("vendor")

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                if reference:
                    cur.execute(
                        "SELECT id, vendor, amount, currency, category, project_code, "
                        "expense_date, idempotency_key FROM expenses "
                        "WHERE client_id=%s AND (idempotency_key=%s OR reference=%s) "
                        "AND approval_status='pending' ORDER BY created_at DESC LIMIT 1",
                        (self.client_id, reference, reference),
                    )
                else:
                    cur.execute(
                        "SELECT id, vendor, amount, currency, category, project_code, "
                        "expense_date, idempotency_key FROM expenses "
                        "WHERE client_id=%s AND vendor ILIKE %s "
                        "AND approval_status='pending' ORDER BY created_at DESC LIMIT 1",
                        (self.client_id, f"%{vendor}%"),
                    )
                row = cur.fetchone()
                cur.close()

            if not row:
                return {"error": f"No pending expense found for '{reference or vendor}'"}

            expense_data = {
                "vendor":          row[1],
                "amount":          row[2],
                "currency":        row[3],
                "category":        row[4],
                "project_code":    row[5],
                "date":            str(row[6]) if row[6] else None,
                "reference":       reference,
                "idempotency_key": row[7],
            }

            category     = expense_data.get("category", "ops")
            platform_map = EXPENSE_CONFIG.get("category_account_map", {}).get(category, {})
            try:
                from integrations.accounting_factory import get_accounting_platform_name
                _platform_key = "quickbooks" if get_accounting_platform_name(self.client_id) == "QuickBooks" else "xero"
            except Exception:
                _platform_key = "xero"

            expense_data["xero_account_code"]       = platform_map.get("xero", "429")
            expense_data["quickbooks_account_code"] = platform_map.get("quickbooks", "5300")
            expense_data["accounting_code"]         = platform_map.get(_platform_key, "429")

            accounting = self._post_to_accounting(expense_data)

            if accounting.get("error") and not accounting.get("queued_for_retry"):
                return {"error": f"Could not post to accounting: {accounting['error']}"}

            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE expenses SET approval_status='approved', approved_at=NOW() "
                    "WHERE id=%s AND client_id=%s",
                    (row[0], self.client_id),
                )
                cur.close()

            ext_id = (
                accounting.get("ReceiptID")
                or accounting.get("InvoiceID")
                or accounting.get("Id")
                or (accounting.get("Purchase") or {}).get("Id")
            )
            if ext_id:
                with get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE expenses SET external_id=%s WHERE id=%s AND client_id=%s",
                        (ext_id, row[0], self.client_id),
                    )
                    cur.close()

            self._notify_submitter(expense_data, "approved")
            return {"approved": True, "expense_id": row[0], "accounting": accounting}

        except Exception as e:
            logger.error("Approve expense failed client=%s: %s", self.client_id, e)
            return {"error": str(e)}

    def _action_reject(self, data: dict) -> dict:
        """Execute action reject for ExpenseAgent."""
        reference = data.get("reference")
        vendor    = data.get("vendor")
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                if reference:
                    cur.execute(
                        "UPDATE expenses SET approval_status='rejected' "
                        "WHERE id=(SELECT id FROM expenses WHERE client_id=%s "
                        "AND (idempotency_key=%s OR reference=%s) ORDER BY created_at DESC LIMIT 1) "
                        "RETURNING id",
                        (self.client_id, reference, reference),
                    )
                else:
                    cur.execute(
                        "UPDATE expenses SET approval_status='rejected' "
                        "WHERE id=(SELECT id FROM expenses WHERE client_id=%s AND vendor ILIKE %s "
                        "AND approval_status='pending' ORDER BY created_at DESC LIMIT 1) RETURNING id",
                        (self.client_id, f"%{vendor}%"),
                    )
                row = cur.fetchone()
                cur.close()

            if not row:
                return {"error": f"No pending expense found for '{reference or vendor}'"}

            self._notify_submitter(data, "rejected")
            return {"rejected": True, "expense_id": row[0], "reason": data.get("notes")}

        except Exception as e:
            logger.error("Reject expense failed client=%s: %s", self.client_id, e)
            return {"error": str(e)}

    def _action_track(self, data: dict) -> dict:
        """Execute action track for ExpenseAgent."""
        reference = data.get("reference")
        vendor = data.get("vendor")
        if not reference and not vendor:
            return {"error": "Please provide the expense reference or vendor name to track"}

        try:
            live = get_system_from_config(self.client_id).list_expenses(
                vendor_filter=vendor or "",
                reference=reference or "",
            )
            if live:
                e = live[0]
                return {
                    "id":              e.get("external_id", ""),
                    "vendor":          e.get("vendor", ""),
                    "amount":          str(e.get("amount", "")),
                    "currency":        e.get("currency", "USD"),
                    "category":        e.get("category", ""),
                    "approval_status": e.get("status", ""),
                    "approved_at":     e.get("date", ""),
                    "created_at":      e.get("date", ""),
                }
        except AttributeError:
            logger.warning("list_expenses not implemented client=%s", self.client_id)
        except Exception as e:
            logger.error("Live expense track failed client=%s: %s", self.client_id, e)

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                if reference:
                    cur.execute(
                        "SELECT id, vendor, amount, currency, category, "
                        "approval_status, approved_at, created_at FROM expenses "
                        "WHERE client_id=%s AND (idempotency_key=%s OR reference=%s) LIMIT 1",
                        (self.client_id, reference, reference),
                    )
                else:
                    cur.execute(
                        "SELECT id, vendor, amount, currency, category, "
                        "approval_status, approved_at, created_at FROM expenses "
                        "WHERE client_id=%s AND vendor ILIKE %s ORDER BY created_at DESC LIMIT 1",
                        (self.client_id, f"%{vendor}%"),
                    )
                row = cur.fetchone()
                cur.close()
            if not row:
                return {"error": f"No expense found for '{reference or vendor}'"}
            return {
                "id":              row[0],
                "vendor":          row[1],
                "amount":          str(row[2]),
                "currency":        row[3],
                "category":        row[4],
                "approval_status": row[5],
                "approved_at":     str(row[6]),
                "created_at":      str(row[7]),
            }
        except Exception as e:
            logger.error("Track expense failed client=%s: %s", self.client_id, e)
            return {"error": str(e)}

    def _action_list_expenses(self, data: dict) -> dict:
        status_filter   = data.get("status_filter")
        category_filter = data.get("category_filter") or data.get("category")
        vendor_filter   = data.get("vendor_filter") or data.get("vendor")
        date_from       = data.get("date_from")
        date_to         = data.get("date_to")
        page            = max(1, int(data.get("page", 1)))
        per_page        = 20
        offset          = (page - 1) * per_page

        if status_filter and status_filter not in _VALID_STATUS_FILTERS:
            return {"error": f"Invalid status filter '{status_filter}'"}
        if category_filter and category_filter not in _VALID_CATEGORY_FILTERS:
            return {"error": f"Invalid category filter '{category_filter}'"}

        try:
            live = get_system_from_config(self.client_id).list_expenses(
                vendor_filter=vendor_filter or "",
                status_filter=status_filter or "",
                category_filter=category_filter or "",
                date_from=date_from or "",
                date_to=date_to or "",
                page=page,
                page_size=per_page,
            )
            if live:
                return {
                    "expenses": [
                        {
                            "vendor":          e.get("vendor", ""),
                            "amount":          str(e.get("amount", "")),
                            "currency":        e.get("currency", "USD"),
                            "category":        e.get("category", ""),
                            "approval_status": e.get("status", ""),
                            "reference":       e.get("reference") or e.get("external_id", ""),
                            "expense_date":    str(e.get("date", "")),
                        }
                        for e in live
                    ],
                    "total": len(live),
                    "page":  page,
                    "pages": 1,
                }
        except AttributeError:
            logger.warning("list_expenses not implemented client=%s", self.client_id)
        except Exception as e:
            logger.error("Live list_expenses failed client=%s: %s", self.client_id, e)

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT vendor, amount, currency, category, approval_status, "
                    "reference, expense_date, COUNT(*) OVER() AS total FROM expenses "
                    "WHERE client_id=%s "
                    "AND (%s::text IS NULL OR approval_status=%s) "
                    "AND (%s::text IS NULL OR category=%s) "
                    "AND (%s::text IS NULL OR vendor ILIKE %s) "
                    "AND (%s::date IS NULL OR expense_date>=%s::date) "
                    "AND (%s::date IS NULL OR expense_date<=%s::date) "
                    "ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    (
                        self.client_id,
                        status_filter, status_filter,
                        category_filter, category_filter,
                        vendor_filter, f"%{vendor_filter}%" if vendor_filter else None,
                        date_from, date_from,
                        date_to, date_to,
                        per_page, offset,
                    ),
                )
                rows = cur.fetchall()
                cur.close()

            if not rows:
                return {"expenses": [], "total": 0, "page": page, "pages": 0,
                        "message": "No expenses found"}

            total = int(rows[0][7])
            return {
                "expenses": [
                    {
                        "vendor":          r[0],
                        "amount":          str(r[1]),
                        "currency":        r[2],
                        "category":        r[3],
                        "approval_status": r[4],
                        "reference":       r[5],
                        "expense_date":    str(r[6]) if r[6] else None,
                    }
                    for r in rows
                ],
                "total": total,
                "page":  page,
                "pages": -(-total // per_page),
            }
        except Exception as e:
            logger.error("List expenses failed client=%s: %s", self.client_id, e)
            return {"error": str(e)}

    def _action_delete(self, data: dict) -> dict:
        reference = data.get("reference")
        vendor = data.get("vendor")
        delete_all = bool(data.get("delete_all"))

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                if delete_all:
                    cur.execute("DELETE FROM expenses WHERE client_id=%s RETURNING id", (self.client_id,))
                    rows = cur.fetchall()
                    cur.close()
                    if not rows:
                        return {"error": "No expenses found to delete"}
                    return {"deleted": True, "deleted_count": len(rows), "scope": "all"}

                if reference:
                    cur.execute(
                        "DELETE FROM expenses WHERE id=("
                        "SELECT id FROM expenses WHERE client_id=%s AND (idempotency_key=%s OR reference=%s) "
                        "ORDER BY created_at DESC LIMIT 1) RETURNING id",
                        (self.client_id, reference, reference),
                    )
                    row = cur.fetchone()
                    cur.close()
                    if not row:
                        return {"error": f"No expense found for '{reference}'"}
                    return {"deleted": True, "deleted_count": 1, "scope": "reference"}

                if vendor:
                    cur.execute(
                        "DELETE FROM expenses WHERE client_id=%s AND vendor ILIKE %s RETURNING id",
                        (self.client_id, f"%{vendor}%"),
                    )
                    rows = cur.fetchall()
                    cur.close()
                    if not rows:
                        return {"error": f"No expense found for '{vendor}'"}
                    return {"deleted": True, "deleted_count": len(rows), "scope": "vendor"}

                cur.close()
                return {"error": "Please provide the expense reference or vendor name"}
        except Exception as e:
            logger.error("Delete expense failed client=%s: %s", self.client_id, e)
            return {"error": str(e)}

    def _action_summary(self, data: dict) -> dict:
        month      = data.get("month")
        month_from = data.get("month_from")
        month_to   = data.get("month_to")
        target     = month or __import__("datetime").date.today().strftime("%Y-%m")

        try:
            live = get_system_from_config(self.client_id).list_expenses(
                date_from=f"{month_from or target}-01",
                date_to=f"{month_to or target}-31",
                page=1,
                page_size=200,
            )
            if live:
                from collections import defaultdict
                bucket: dict = defaultdict(float)
                counts: dict = defaultdict(int)
                currencies: dict = {}
                for e in live:
                    cat = e.get("category") or "ops"
                    bucket[cat] += float(e.get("amount") or 0)
                    counts[cat] += 1
                    currencies[cat] = e.get("currency", "USD")

                budget_caps = EXPENSE_CONFIG.get("monthly_budget_caps", {})
                breakdown = []
                for cat, total in sorted(bucket.items(), key=lambda x: -x[1]):
                    cap = budget_caps.get(cat)
                    breakdown.append({
                        "category":        cat,
                        "total":           total,
                        "count":           counts[cat],
                        "currency":        currencies.get(cat, "USD"),
                        "over_budget":     bool(cap and total > cap),
                        "budget_used_pct": round((total / cap) * 100, 1) if cap else None,
                        "budget_cap":      cap,
                    })
                return {
                    "breakdown":   breakdown,
                    "total_lines": len(breakdown),
                    "month":       f"{month_from} to {month_to}" if month_from else target,
                }
        except AttributeError:
            logger.warning("list_expenses not implemented client=%s", self.client_id)
        except Exception as e:
            logger.error("Live summary failed client=%s: %s", self.client_id, e)

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                if month_from and month_to:
                    cur.execute(
                        "SELECT category, SUM(amount), COUNT(*), currency FROM expenses "
                        "WHERE client_id=%s "
                        "AND TO_CHAR(COALESCE(expense_date, created_at), 'YYYY-MM') BETWEEN %s AND %s "
                        "GROUP BY category, currency ORDER BY SUM(amount) DESC",
                        (self.client_id, month_from, month_to),
                    )
                else:
                    cur.execute(
                        "SELECT category, SUM(amount), COUNT(*), currency FROM expenses "
                        "WHERE client_id=%s "
                        "AND TO_CHAR(COALESCE(expense_date, created_at), 'YYYY-MM') = %s "
                        "GROUP BY category, currency ORDER BY SUM(amount) DESC",
                        (self.client_id, target),
                    )
                rows = cur.fetchall()
                cur.close()

            budget_caps = EXPENSE_CONFIG.get("monthly_budget_caps", {})
            breakdown = []
            for r in rows:
                category, total, count, currency = r[0], float(r[1]), r[2], r[3]
                cap = budget_caps.get(category)
                breakdown.append({
                    "category": category, "total": total, "count": count, "currency": currency,
                    "over_budget": bool(cap and total > cap),
                    "budget_used_pct": round((total / cap) * 100, 1) if cap else None,
                    "budget_cap": cap,
                })
            return {
                "breakdown": breakdown,
                "total_lines": len(breakdown),
                "month": f"{month_from} to {month_to}" if month_from else target,
            }
        except Exception as e:
            logger.error("Summary failed client=%s: %s", self.client_id, e)
            return {"error": str(e)}

    def _action_edit(self, data: dict) -> dict:
        edit_fields = data.get("edit_fields") or {}
        if not edit_fields:
            return {"error": "No fields to edit — please specify what to change"}
        reference = data.get("reference")
        vendor = data.get("vendor")
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                if reference:
                    cur.execute(
                        "SELECT id, external_id, vendor, amount, currency, category, approval_status "
                        "FROM expenses WHERE client_id=%s "
                        "AND (idempotency_key=%s OR reference=%s) ORDER BY created_at DESC LIMIT 1",
                        (self.client_id, reference, reference),
                    )
                elif vendor:
                    cur.execute(
                        "SELECT id, external_id, vendor, amount, currency, category, approval_status "
                        "FROM expenses WHERE client_id=%s AND vendor ILIKE %s ORDER BY created_at DESC LIMIT 1",
                        (self.client_id, f"%{vendor}%"),
                    )
                else:
                    cur.execute(
                        "SELECT id, external_id, vendor, amount, currency, category, approval_status "
                        "FROM expenses WHERE client_id=%s ORDER BY created_at DESC LIMIT 1",
                        (self.client_id,),
                    )
                row = cur.fetchone()
                cur.close()

            if not row:
                return {"error": "No expense found to edit"}

            db_id, external_id, db_vendor, db_amount, db_currency, db_category, db_status = row
            allowed_db_fields = {"vendor", "amount", "category", "currency", "notes"}
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
                    f"UPDATE expenses SET {', '.join(set_clauses)} WHERE id=%s AND client_id=%s",
                    params,
                )
                cur.close()

            if external_id and db_status == "approved":
                try:
                    updated_data = {
                        "vendor":   edit_fields.get("vendor",   db_vendor),
                        "amount":   edit_fields.get("amount",   db_amount),
                        "currency": edit_fields.get("currency", db_currency),
                        "category": edit_fields.get("category", db_category),
                    }
                    get_system_from_config(self.client_id).post_expense(updated_data)
                except Exception as exc:
                    logger.warning("Accounting re-sync after edit failed client=%s: %s", self.client_id, exc)

            return {
                "edited":            True,
                "expense_id":        db_id,
                "fields_updated":    list(edit_fields.keys()),
                "previous_vendor":   db_vendor,
                "previous_amount":   str(db_amount),
                "previous_category": db_category,
            }
        except Exception as e:
            logger.error("Edit expense failed client=%s: %s", self.client_id, e)
            return {"error": str(e)}

    def _post_to_accounting(self, data: dict) -> dict:
        """Post expense to accounting. Captures ReceiptID from Xero expense claim response."""
        category = data.get("category", "ops")
        platform = EXPENSE_CONFIG.get("category_account_map", {}).get(category, {})
        try:
            from integrations.accounting_factory import get_accounting_platform_name
            _platform_key = "quickbooks" if get_accounting_platform_name(self.client_id) == "QuickBooks" else "xero"
        except Exception:
            _platform_key = "xero"
        enriched = {
            **data,
            "xero_account_code": data.get("xero_account_code") or platform.get("xero", "429"),
            "accounting_code": data.get("accounting_code") or platform.get(_platform_key, "429"),
            "date": data.get("date") or date.today().isoformat(),
        }
        enriched.pop("quickbooks_account_code", None)
        last_exc: Exception | None = None
        for attempt, delay in enumerate([1, 2, 4], start=1):
            try:
                result = self._accounting_cb.call(get_system_from_config(self.client_id).post_expense, enriched)
                ext_id = (
                    result.get("ReceiptID")
                    or result.get("InvoiceID")
                    or result.get("Id")
                    or (result.get("Purchase") or {}).get("Id")
                )
                if ext_id and enriched.get("idempotency_key"):
                    try:
                        with get_conn() as conn:
                            cur = conn.cursor()
                            cur.execute(
                                "UPDATE expenses SET external_id=%s WHERE idempotency_key=%s",
                                (ext_id, enriched["idempotency_key"]),
                            )
                            cur.close()
                    except Exception as db_exc:
                        logger.warning("expense external_id update failed client=%s: %s", self.client_id, db_exc)
                return result
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
                logger.warning("Expense accounting attempt %d/3 failed client=%s: %s", attempt, self.client_id, exc)
                if attempt < 3:
                    time.sleep(delay)

        logger.error("Expense accounting failed after 3 attempts client=%s: %s", self.client_id, last_exc)
        from core.tasks import retry_expense_accounting_post
        retry_expense_accounting_post.apply_async(  # type: ignore
            kwargs={"client_id": self.client_id, "data": enriched},
            queue="low", countdown=60,
        )
        return {"error": str(last_exc), "queued_for_retry": True}

    def _save_to_db(self, data: dict) -> bool:
        expense_date = data.get("date")
        if expense_date:
            try:
                expense_date = date.fromisoformat(str(expense_date))
            except ValueError:
                expense_date = date.today()
        else:
            expense_date = date.today()

        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO expenses "
                    "(client_id, vendor, amount, tax_amount, category, currency, "
                    "status, approval_status, idempotency_key, reference, "
                    "project_code, receipt_url, expense_date, raw_message) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (idempotency_key) DO NOTHING RETURNING id",
                    (
                        self.client_id, data.get("vendor"), data.get("amount"),
                        data.get("tax_amount"), data.get("category"),
                        data.get("currency", _DEFAULT_CURRENCY),
                        "processed", data.get("approval_status", "pending"),
                        data.get("idempotency_key"), data.get("reference"),
                        data.get("project_code"), data.get("receipt_url"),
                        expense_date, json.dumps(data),
                    ),
                )
                row = cur.fetchone()
                cur.close()
            return row is not None
        except Exception as e:
            logger.error("Expense DB save failed client=%s: %s", self.client_id, e)
            return False

    def _notify_submitter(self, data: dict, status: str) -> None:
        recipient = data.get("recipient_email")
        if not recipient or "@" not in str(recipient):
            return
        try:
            from integrations.email_factory import get_email_from_config
            word     = "approved" if status == "approved" else "rejected"
            reason   = f"\nReason: {data.get('notes')}" if status == "rejected" and data.get("notes") else ""
            currency = data.get("currency", "USD")
            amount   = data.get("amount", "")
            email    = get_email_from_config(self.client_id)
            email.send(
                recipient=recipient,
                subject=f"Expense {word.title()} — {data.get('vendor')} {currency} {amount}",
                body=(
                    f"Your expense has been {word}.\n\n"
                    f"Vendor:   {data.get('vendor')}\n"
                    f"Amount:   {currency} {amount}\n"
                    f"Category: {data.get('category')}{reason}"
                ),
            )
        except Exception as e:
            logger.error("_notify_submitter failed client=%s: %s", self.client_id, e)

    def _notify_approver(self, data: dict) -> None:
        try:
            from channels.telegram import TelegramChannel
            from config.client_config import get_client_config
            from integrations.token_manager import _get_stored

            config = get_client_config(self.client_id)
            approver_chat_id = config.get("approver_chat_id") or config.get("approve_chat_id")
            if not approver_chat_id:
                return

            if not (_get_stored(f"telegram:{self.client_id}") or {}).get("access_token"):
                return

            ref = data.get("idempotency_key", "N/A")
            employee_label = data.get("employee_name") or data.get("_sender", ref[:8])

            TelegramChannel(client_id=self.client_id).send_with_buttons(
                recipient=approver_chat_id,
                message=(
                    f"Expense approval required\n"
                    f"Staff:     {employee_label}\n"
                    f"Vendor:    {data.get('vendor')}\n"
                    f"Amount:    {data.get('currency', 'USD')} {data.get('amount')}\n"
                    f"Category:  {data.get('category')}\n"
                    f"Reference: {ref}"
                ),
                buttons=[
                    {"label": "Approve", "data": f"expense_approve:{ref}"},
                    {"label": "Reject",  "data": f"expense_reject:{ref}"},
                ],
            )
        except Exception as e:
            logger.error("_notify_approver failed client=%s: %s", self.client_id, e)