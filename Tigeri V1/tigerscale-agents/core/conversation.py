"""Contain conversation backend logic."""
import json
import logging
import re
import time
from dataclasses import dataclass

import redis as redis_lib

from config.settings import settings

logger = logging.getLogger(__name__)

_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)

CONTEXT_WINDOW  = 40
CONTEXT_TTL     = 86400 * 30
TASK_RESULT_TTL = 86400 * 7
PENDING_TTL     = 86400
_TZ_TTL         = 86400 * 180   # 180 days
_CONTEXT_DOMAINS = frozenset({
    "invoice",
    "expense",
    "po",
    "payment",
    "admin",
    "bill",
    "staffing",
})

_INTENT_TO_DOMAIN = {
    "invoice": "invoice",
    "po":      "po",
    "expense": "expense",
    "payment": "payment",
    "admin":   "admin",
    "bill":    "bill",
}

_VALID_TZ_ABBRS = frozenset({
    "UTC", "GMT", "IST", "EST", "EDT", "PST", "PDT", "CST", "CDT",
    "MST", "MDT", "SGT", "GST", "JST", "BST", "CET", "CEST",
    "AEST", "PKT", "BDT",
})


def _get_db_conn():
    """Return a DB connection via the pool."""
    from config.db_pool import get_conn
    return get_conn()


@dataclass
class PreRouteOutcome:
    handled:          bool  = False
    reply:            str   = ""
    pdf_bytes:        bytes = b""
    pdf_filename:     str   = ""
    pdf_caption:      str   = ""
    intent:           str   = "conversation"
    enriched_message: str   = ""


def save_pending_intent(
    sender: str,
    client_id: str,
    intent: str,
    original_message: str,
    action: str = "",
    partial_data: dict | None = None,
) -> None:
    key = f"conv:pending:{client_id}:{sender}"
    payload = {
        "intent":           intent,
        "action":           action,
        "original_message": original_message[:2000],
        "partial_data":     partial_data or {},
        "saved_at":         int(time.time()),
    }
    if partial_data and partial_data.get("awaiting"):
        payload["awaiting"] = partial_data["awaiting"]
    try:
        _redis.setex(key, PENDING_TTL, json.dumps(payload))
    except Exception as e:
        logger.warning("save_pending_intent failed sender=%s: %s", sender, e)


def get_pending_intent(sender: str, client_id: str) -> dict:
    key = f"conv:pending:{client_id}:{sender}"
    try:
        raw = _redis.get(key)
        if raw:
            return json.loads(raw) # type: ignore
    except Exception as e:
        logger.warning("get_pending_intent failed sender=%s: %s", sender, e)
    return {}


def clear_pending_intent(sender: str, client_id: str) -> None:
    try:
        _redis.delete(f"conv:pending:{client_id}:{sender}")
    except Exception as e:
        logger.warning("clear_pending_intent failed sender=%s: %s", sender, e)


def save_action_context(
    sender: str,
    client_id: str,
    domain: str,
    payload: dict,
) -> None:
    """
    Save the last meaningful action for a given domain.
    One key per (client_id, sender, domain) — overwrites previous value.
    """
    if domain not in _CONTEXT_DOMAINS:
        logger.debug("save_action_context: unknown domain '%s' — skipping", domain)
        return
    key = f"conv:ctx:action:{client_id}:{sender}:{domain}"
    try:
        _redis.setex(key, TASK_RESULT_TTL, json.dumps({
            **payload,
            "saved_at": int(time.time()),
        }))
    except Exception as e:
        logger.warning(
            "save_action_context failed sender=%s domain=%s: %s", sender, domain, e
        )


def get_action_context(sender: str, client_id: str, domain: str) -> dict:
    """Return the last saved context for a single domain, or {} if absent."""
    key = f"conv:ctx:action:{client_id}:{sender}:{domain}"
    try:
        raw = _redis.get(key)
        return json.loads(raw) if raw else {} # type: ignore
    except Exception as e:
        logger.warning(
            "get_action_context failed sender=%s domain=%s: %s", sender, domain, e
        )
        return {}


def get_all_action_contexts(sender: str, client_id: str) -> dict[str, dict]:
    """
    Fetch all domain contexts for this sender in a single pipeline call.
    Returns {domain: context_dict} for every domain in _CONTEXT_DOMAINS.
    """
    keys = {
        domain: f"conv:ctx:action:{client_id}:{sender}:{domain}"
        for domain in _CONTEXT_DOMAINS
    }
    try:
        pipe = _redis.pipeline()
        for key in keys.values():
            pipe.get(key)
        results = pipe.execute()
        return {
            domain: json.loads(raw) if raw else {}
            for domain, raw in zip(keys.keys(), results)
        }
    except Exception as e:
        logger.warning("get_all_action_contexts failed sender=%s: %s", sender, e)
    return {}


def save_file_bytes_context(
    sender: str,
    client_id: str,
    file_bytes: bytes,
    mime_type: str,
    filename: str,
) -> None:
    """Cache raw file bytes so later agent calls can re-use the last attachment."""
    try:
        _redis.setex(
            f"conv:ctx:file_bytes:{client_id}:{sender}",
            TASK_RESULT_TTL,
            file_bytes.hex(),
        )
        _redis.setex(
            f"conv:ctx:file_meta:{client_id}:{sender}",
            TASK_RESULT_TTL,
            json.dumps({"mime_type": mime_type, "filename": filename}),
        )
    except Exception as e:
        logger.warning("save_file_bytes_context failed sender=%s: %s", sender, e)


def get_file_bytes_context(
    sender: str, client_id: str
) -> tuple[bytes, str, str]:
    """
    Return (file_bytes, mime_type, filename).
    All three are empty / b"" when nothing is cached.
    """
    try:
        raw_bytes = _redis.get(f"conv:ctx:file_bytes:{client_id}:{sender}")
        raw_meta  = _redis.get(f"conv:ctx:file_meta:{client_id}:{sender}")
        if not raw_bytes or not raw_meta:
            return b"", "", ""
        meta = json.loads(raw_meta) # type: ignore
        return (
            bytes.fromhex(raw_bytes), # type: ignore
            meta.get("mime_type", ""),
            meta.get("filename", ""),
        )
    except Exception as e:
        logger.warning("get_file_bytes_context failed sender=%s: %s", sender, e)
        return b"", "", ""


def clear_file_bytes_context(sender: str, client_id: str) -> None:
    """
    Delete cached file bytes for this sender.
    """
    try:
        pipe = _redis.pipeline()
        pipe.delete(f"conv:ctx:file_bytes:{client_id}:{sender}")
        pipe.delete(f"conv:ctx:file_meta:{client_id}:{sender}")
        pipe.execute()
    except Exception as e:
        logger.warning("clear_file_bytes_context failed sender=%s: %s", sender, e)


def get_client_timezone(client_id: str) -> str:
    try:
        tz = _redis.get(f"client:timezone:{client_id}")
        if tz:
            return str(tz)
    except Exception as e:
        logger.warning("get_client_timezone Redis failed client=%s: %s", client_id, e)

    try:
        from config.client_config import get_client_financial_config
        fc = get_client_financial_config(client_id)
        tz = fc.get("timezone", "")
        if not tz and fc.get("country"):
            from agents.a03_admin.tools import COUNTRY_TIMEZONE_MAP
            tz = COUNTRY_TIMEZONE_MAP.get(fc["country"].lower(), "")
        if tz:
            try:
                _redis.setex(f"client:timezone:{client_id}", _TZ_TTL, tz)
            except Exception:
                pass
            return tz
    except Exception as e:
        logger.warning("get_client_timezone financial_config failed client=%s: %s", client_id, e)

    try:
        with _get_db_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT timezone FROM client_config WHERE client_id = %s LIMIT 1",
                (client_id,),
            )
            row = cur.fetchone()
            cur.close()
            if row and row[0]:
                tz = str(row[0])
                try:
                    _redis.setex(f"client:timezone:{client_id}", _TZ_TTL, tz)
                except Exception:
                    pass
                return tz
    except Exception as e:
        logger.warning("get_client_timezone DB failed client=%s: %s", client_id, e)

    return ""

def save_client_timezone(client_id: str, timezone: str) -> None:
    """
    Persist IANA timezone for this client to Redis and DB.
    Called when the user explicitly provides their timezone,
    and on every successful schedule_meeting so it stays fresh.
    """
    if not timezone or not client_id:
        return

    tz_upper = timezone.strip().upper()
    tz_clean = timezone.strip()
    if (
        len(tz_clean) < 2
        or ("/" not in tz_clean and tz_upper not in _VALID_TZ_ABBRS)
    ):
        logger.warning(
            "save_client_timezone: rejected suspicious value '%s' client=%s",
            timezone, client_id,
        )
        return

    try:
        _redis.setex(f"client:timezone:{client_id}", _TZ_TTL, tz_clean)
    except Exception as e:
        logger.warning("save_client_timezone Redis failed client=%s: %s", client_id, e)

    try:
        with _get_db_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO client_config (client_id, timezone)
                VALUES (%s, %s)
                ON CONFLICT (client_id) DO UPDATE
                    SET timezone   = EXCLUDED.timezone,
                        updated_at = NOW()
                """,
                (client_id, tz_clean),
            )
            cur.close()
    except Exception as e:
        logger.warning("save_client_timezone DB failed client=%s: %s", client_id, e)

def pre_route(
    client_id: str,
    sender: str,
    message: str,
    channel: str = "telegram",
) -> PreRouteOutcome:
    stripped = message.strip()

    context = _get_context(sender, client_id)
    _append_context(sender, client_id, stripped, role="user")
    enriched = _build_enriched_message(stripped, context, sender, client_id, domain="")

    return PreRouteOutcome(
        handled=False,
        enriched_message=enriched,
        intent="",
    )


def _context_key(sender: str, client_id: str) -> str:
    return f"conv:ctx:{client_id}:{sender}"


def _get_context(sender: str, client_id: str) -> list[dict]:
    key = _context_key(sender, client_id)
    raw = _redis.get(key)
    if not raw:
        return []
    try:
        return json.loads(raw) # type: ignore
    except Exception:
        return []


def _append_context(
    sender: str,
    client_id: str,
    message: str,
    role: str = "user",
) -> None:
    key     = _context_key(sender, client_id)
    context = _get_context(sender, client_id)
    context.append({
        "role":    role,
        "content": message[:1500],
        "ts":      int(time.time()),
    })
    context = context[-CONTEXT_WINDOW:]
    try:
        _redis.setex(key, CONTEXT_TTL, json.dumps(context))
    except Exception as e:
        logger.warning("_append_context failed sender=%s: %s", sender, e)


def save_agent_reply(sender: str, client_id: str, reply: str) -> None:
    _append_context(sender, client_id, reply[:500], role="assistant")

_CONTEXT_FORMATTERS: dict = {
    "invoice": lambda c: (
        f"Last invoice: {c['invoice_number']} "
        f"for {c.get('vendor', '')} "
        f"{c.get('currency', '')} {c.get('amount', '')}"
        if c.get("invoice_number") else None
    ),
    "expense": lambda c: (
        f"Last expense: {c.get('vendor', '')} "
        f"{c.get('currency', '')} {c.get('amount', '')} "
        f"({c.get('category', '')})"
        if c.get("vendor") else None
    ),
    "po": lambda c: (
        f"Last PO: {c['po_number']} for {c.get('vendor', '')}"
        if c.get("po_number") else None
    ),
    "payment": lambda c: (
        f"Last payment: {c.get('amount', '')} {c.get('currency', '')} "
        f"from {c.get('payer', c.get('vendor', ''))}"
        if c.get("payer") or c.get("vendor") else None
    ),
    "admin": lambda c: (
        f"Last admin action: {c.get('action', '')} — "
        f"file '{c.get('filename', '')}' in folder '{c.get('folder', '')}'"
        if c.get("action") else None
    ),
    "bill": lambda c: (
        f"Last bill: {c.get('vendor', '')} "
        f"{c.get('currency', '')} {c.get('amount', '')} "
        f"(inv# {c.get('invoice_number', '')})"
        if c.get("vendor") else None
    ),
    "staffing": lambda c: (
        f"Last staffing action: {c.get('action', '')} — "
        f"employee '{c.get('employee_name', '')}' on {c.get('date', '')}"
        if c.get("action") else None
    ),
}


def _build_enriched_message(
    message: str,
    context: list[dict],
    sender: str = "",
    client_id: str = "",
    domain: str = "",
) -> str:
    sections = []

    if sender and client_id:
        hints = []

        try:
            contexts = get_all_action_contexts(sender, client_id)
            for ctx_domain, ctx in contexts.items():
                if not ctx:
                    continue
                if domain and ctx_domain != domain:
                    continue
                formatter = _CONTEXT_FORMATTERS.get(ctx_domain)
                if formatter:
                    hint = formatter(ctx)
                    if hint:
                        hints.append(hint)
        except Exception:
            pass

        if not domain or domain == "admin":
            try:
                _, _, cached_filename = get_file_bytes_context(sender, client_id)
                if cached_filename:
                    hints.append(
                        f"Cached file available: '{cached_filename}' (can be re-filed or re-read)"
                    )
            except Exception:
                pass

        try:
            pending = get_pending_intent(sender, client_id)
            if pending and pending.get("intent"):
                pending_domain = _INTENT_TO_DOMAIN.get(pending.get("intent", ""), "")
                if not domain or not pending_domain or pending_domain == domain:
                    hints.append(
                        f"Previous intent: {pending['intent']}. "
                        f"Original: {pending.get('original_message', '')[:200]}"
                    )
        except Exception:
            pass

        if hints:
            sections.append("[Context:\n" + "\n".join(hints) + "\n]")

    if context:
        recent = context[-15:]
        history_lines = []
        for turn in recent:
            role = "User" if turn.get("role") == "user" else "Assistant"
            content = turn.get("content", "")
            if role == "Assistant" and len(content) > 200:
                content = content[:200] + "..."
            history_lines.append(f"{role}: {content}")
        sections.append(
            "[Conversation:\n" + "\n".join(history_lines) + "\n]"
        )

    sections.append(f"Current message: {message}")
    return "\n\n".join(sections)


def save_task_result(
    sender: str,
    client_id: str,
    task_id: str,
    result: dict,
) -> None:
    key = f"conv:last_result:{client_id}:{sender}"
    try:
        invoice  = result.get("invoice", {}) or {}
        po       = result.get("po", {}) or {}
        result_d = result.get("result", {}) or {}

        pdf = None
        if isinstance(result_d, dict):
            pdf = result_d.get("pdf")
        has_pdf = isinstance(pdf, (bytes, bytearray)) and len(pdf) > 0

        if not has_pdf:
            try:
                existing_raw = _redis.get(key)
                if existing_raw:
                    existing = json.loads(existing_raw)  # type: ignore
                    if existing.get("has_pdf"):
                        has_pdf = True
            except Exception:
                pass

        storable = {
            "task_id":        task_id,
            "status":         result.get("status"),
            "intent":         result.get("action") or result.get("intent"),
            "invoice_number": (
                result.get("po_number")
                or po.get("po_number")
                or invoice.get("invoice_number")
            ),
            "vendor": po.get("vendor") or invoice.get("vendor"),
            "has_pdf": has_pdf,
            "ts":      int(time.time()),
        }

        if not storable["invoice_number"]:
            try:
                existing_raw = _redis.get(key)
                if existing_raw:
                    existing = json.loads(existing_raw) # type: ignore
                    storable["invoice_number"] = (
                        storable["invoice_number"] or existing.get("invoice_number")
                    )
                    storable["vendor"] = (
                        storable["vendor"] or existing.get("vendor")
                    )
            except Exception:
                pass

        _redis.setex(key, TASK_RESULT_TTL, json.dumps(storable))

        if has_pdf and isinstance(pdf, (bytes, bytearray)):
            pdf_key = f"conv:pdf:{client_id}:{sender}"
            _redis.setex(pdf_key, TASK_RESULT_TTL, bytes(pdf).hex())

        if not sender:
            return

        action = result.get("action", "")
        status = result.get("status", "")
        expense = result.get("expense") or {}
        bill = result.get("bill")    or {}

        domain: str | None        = None
        domain_payload: dict | None = None

        if invoice.get("invoice_number") and status == "success":
            domain = "invoice"
            domain_payload = {
                "invoice_number": invoice.get("invoice_number"),
                "vendor":         invoice.get("vendor", ""),
                "amount":         str(invoice.get("amount", "")),
                "currency":       invoice.get("currency", "USD"),
                "action":         action,
            }

        elif expense and status in ("success", "needs_info"):
            domain = "expense"
            domain_payload = {
                "vendor":   expense.get("vendor", ""),
                "amount":   str(expense.get("amount", "")),
                "currency": expense.get("currency", ""),
                "category": expense.get("category", ""),
                "action":   action,
            }

        elif po.get("po_number") and status == "success":
            domain = "po"
            domain_payload = {
                "po_number": po.get("po_number"),
                "vendor":    po.get("vendor", ""),
                "action":    action,
            }

        elif result.get("action") in (
            "track_payment", "reconcile", "capture_payment",
            "refund", "send_reminder",
        ) and status == "success":
            pay_result = result_d if isinstance(result_d, dict) else {}
            domain = "payment"
            domain_payload = {
                "action":       action,
                "amount":       str(result.get("amount", "") or pay_result.get("amount", "")),
                "currency":     result.get("currency", "") or pay_result.get("currency", ""),
                "payer":        result.get("payer", "") or pay_result.get("payer", ""),
                "payment_ref":  result.get("payment_ref", "") or pay_result.get("payment_ref", ""),
            }

        elif bill and status in ("success", "needs_info"):
            domain = "bill"
            domain_payload = {
                "vendor":         bill.get("vendor", ""),
                "amount":         str(bill.get("amount", "")),
                "currency":       bill.get("currency", ""),
                "invoice_number": bill.get("invoice_number", ""),
                "action":         action,
            }

        elif action in (
            "file_document", "upload_document",
            "find_document", "read_document",
        ) and status == "success":
            domain = "admin"
            domain_payload = {
                "action":   action,
                "filename": result_d.get("filename", "") if isinstance(result_d, dict) else "",
                "folder":   result_d.get("folder", "")   if isinstance(result_d, dict) else "",
                "query":    result_d.get("query", "")    if isinstance(result_d, dict) else "",
            }

        elif action in (
            "roster_shift", "approve_leave", "reject_leave",
            "generate_payroll", "track_attendance", "request_leave",
        ) and status == "success":
            domain = "staffing"
            domain_payload = {
                "action":        action,
                "employee_name": result.get("employee_name", "")
                                 or (result_d.get("employee_name", "") if isinstance(result_d, dict) else ""),
                "date":          result.get("date", "")
                                 or (result_d.get("date", "") if isinstance(result_d, dict) else ""),
                "shift_id":      result_d.get("shift_id", "") if isinstance(result_d, dict) else "",
            }

        if domain and domain_payload:
            save_action_context(sender, client_id, domain, domain_payload)

        if (
            action in ("file_document", "upload_document")
            and status == "success"
            and isinstance(result_d, dict)
        ):
            file_bytes = result_d.get("file_bytes") or result_d.get("bytes")
            mime_type  = result_d.get("mime_type", "application/octet-stream")
            filename   = result_d.get("filename", "document")
            if isinstance(file_bytes, (bytes, bytearray)) and file_bytes:
                save_file_bytes_context(
                    sender=sender,
                    client_id=client_id,
                    file_bytes=bytes(file_bytes),
                    mime_type=mime_type,
                    filename=filename,
                )

    except Exception as e:
        logger.warning("save_task_result failed sender=%s: %s", sender, e)


def clear_context(sender: str, client_id: str) -> None:
    pipe = _redis.pipeline()
    pipe.delete(_context_key(sender, client_id))
    pipe.delete(f"conv:last_result:{client_id}:{sender}")
    pipe.delete(f"conv:pdf:{client_id}:{sender}")
    pipe.delete(f"conv:pending:{client_id}:{sender}")
    pipe.delete(f"conv:ctx:file_bytes:{client_id}:{sender}")
    pipe.delete(f"conv:ctx:file_meta:{client_id}:{sender}")
    for domain in _CONTEXT_DOMAINS:
        pipe.delete(f"conv:ctx:action:{client_id}:{sender}:{domain}")
    pipe.execute()