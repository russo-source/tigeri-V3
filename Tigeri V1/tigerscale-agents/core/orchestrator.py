"""Contain orchestrator backend logic."""
import hashlib
import json
import logging
import re
from config.settings import settings
from core.intent_classifier import classify_with_confidence
import redis

logger = logging.getLogger(__name__)
_redis = redis.from_url(settings.redis_url, decode_responses=True)

AGENT_REGISTRY: dict[str, type] = {}
IDEMPOTENCY_TTL = 300
MAX_MESSAGE_LENGTH = 4000

INTENT_TO_AGENT = {
    "invoice":  "a01_invoice",
    "bill":     "a01_invoice",
    "payment":  "a04_payment",
    "expense":  "a02_expense",
    "admin":    "a03_admin",
    "po":       "a01_invoice",
    "general":  "general",
}
INTENT_TO_QUEUE = {
    "invoice":  "high",
    "bill":     "high",
    "payment":  "high",
    "expense":  "normal",
    "admin":    "low",
    "po":       "high",
    "general":  "low",
}
_AGENT_TO_INTENT = {
    "a01_invoice": "invoice",
    "a01_po":      "po",
    "a02_expense": "expense",
    "a03_admin":   "admin",
    "a04_payment": "payment",
}

_AGENT_REGISTRY = {
    "a01_invoice": "invoices, bills, sending/tracking/approving invoices",
    "a01_po":      "purchase orders: create, approve, find, list, edit, PDF",
    "a02_expense": "expense claims, receipts, reimbursements, spend summaries",
    "a03_admin":   "file/find/read/upload documents, meetings, scheduling, permits, folders, contracts, agreements, NDAs, communications",
    "a04_payment": "payments, reconciliation, cash flow, ageing reports",
}
_OUT_OF_SCOPE_MSG = (
    "I'm built for financial and admin workflows only. I can't help with that.\n"
    "Here's what I can do:\n"
    "• _Create invoice for Acme USD 500_\n"
    "• _Log expense $50 DHL_\n"
    "• _Check overdue invoices_\n"
    "• _Record payment from Client X_"
)
_DOCUMENT_CLASSIFY_SYSTEM = """You are a document routing classifier for a business automation system.

Given a user message, filename, mime type, and whether a file is attached, decide which agent should handle it.

Agents:
{agent_descriptions}

Rules:
- The MESSAGE is the primary signal. Read the intent, not just keywords.
- The file is secondary context — use filename/mime only to break ties.
- If message says "file this contract", "store this", "save this", "upload this" → a03_admin
- If message says "expense", "receipt", "log this", "reimburse", "claim" → a02_expense
- Image of a receipt/bill with no clear message → a02_expense
- Any other document/image being filed, read, summarised, or stored → a03_admin
- Invoice/bill text with no storage intent → a01_invoice
- Purchase order → a01_po
- Payment/reconciliation → a04_payment
- Greetings, help, capability questions, unclear intent → general
- When genuinely unsure → general

Reply with a JSON object only. No preamble. Format:
{{"agent": "a03_admin", "confidence": 0.95}}"""
_CLIENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,98}[a-z0-9]$")

def _to_whatsapp_md(text: str) -> str:
    """Normalise LLM output to WhatsApp-compatible markdown.
    WhatsApp renders: *bold*, _italic_, ~strike~, ```mono```.
    Strip any HTML tags the model may have emitted.
    """
    # HTML → WhatsApp markdown
    text = re.sub(r'<b>(.*?)</b>', r'*\1*', text, flags=re.DOTALL)
    text = re.sub(r'<strong>(.*?)</strong>', r'*\1*', text, flags=re.DOTALL)
    text = re.sub(r'<i>(.*?)</i>', r'_\1_', text, flags=re.DOTALL)
    text = re.sub(r'<em>(.*?)</em>', r'_\1_', text, flags=re.DOTALL)
    text = re.sub(r'<code>(.*?)</code>', r'`\1`', text, flags=re.DOTALL)
    # Strip any remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Markdown **bold** → WhatsApp *bold*
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)
    return text

def _check_maintenance() -> dict | None:
    try:
        raw = _redis.get("admin:settings:toggles")
        if not raw:
            return None
        toggles = json.loads(raw) # type: ignore
        if toggles.get("maintenance_mode"):
            return {
                "status": "maintenance",
                "message": "System is under maintenance. Please try again later.",
                "maintenance_until": toggles.get("maintenance_until"),
            }
    except Exception as e:
        logger.warning("Maintenance check failed (fail-open): %s", e)
    return None


def register_agent(name: str, agent_class: type) -> None:
    AGENT_REGISTRY[name] = agent_class
    logger.info("Registered agent: %s", name)


def _load_active_agents(client_id: str) -> list[str]:
    try:
        from config.client_config import get_client_config
        config = get_client_config(client_id)
        raw = config.get("active_agents", [])
        if not raw:
            return []
        if isinstance(raw[0], dict):
            return [a["agent"] for a in raw if "agent" in a]
        return list(raw)
    except Exception as e:
        logger.warning("active_agents load failed for %s (fail-open): %s", client_id, e)
        return []

def _classify_document_agent(
    client_id: str,
    message: str,
    mime_type: str,
    filename: str,
    is_document: bool,
    _retry: bool = False,
) -> tuple[str, float]:
    """
    Unified LLM classifier for document + text routing.
    Returns (agent_name_or_general, confidence).
    Haiku first, Sonnet if confidence < 0.7.
    """
    agent_descriptions = "\n".join(
        f"- {name}: {desc}" for name, desc in _AGENT_REGISTRY.items()
    )
    system = _DOCUMENT_CLASSIFY_SYSTEM.format(agent_descriptions=agent_descriptions)
    model = "claude-sonnet-4-6" if _retry else "claude-haiku-4-5-20251001"

    user_content = (
        f"Message: {message or '(none)'}\n"
        f"Filename: {filename or 'none'}\n"
        f"MimeType: {mime_type or 'none'}\n"
        f"FileAttached: {is_document}"
    )

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=model,
            max_tokens=50,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = next((b.text.strip() for b in response.content if b.type == "text"), "")
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw).strip()

        match = re.search(r'\{[^}]+\}', raw, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON object found: {raw[:100]}")
        parsed = json.loads(match.group())
        agent = str(parsed.get("agent", "")).strip().lower()
        confidence = float(parsed.get("confidence", 0.0))

        valid = set(_AGENT_REGISTRY.keys()) | {"general"}
        if agent not in valid:
            logger.warning("_classify_document_agent invalid agent=%r — falling back", agent)
            return "general", 0.0

        if confidence < 0.7 and not _retry:
            logger.info("Haiku low confidence %.2f — retrying with Sonnet", confidence)
            return _classify_document_agent(
                client_id, message, mime_type, filename, is_document, _retry=True
            )

        return agent, confidence

    except Exception as e:
        logger.warning("_classify_document_agent model=%s failed: %s", model, e)
        if not _retry:
            return _classify_document_agent(
                client_id, message, mime_type, filename, is_document, _retry=True
            )
        return "general", 0.0
    
def run_agent_task_dispatch(
    client_id: str,
    intent: str,
    message: str,
    mime_type: str,
    filename: str,
    is_document: bool,
) -> str:
    """
    Resolve final agent name from intent + document classifier.
    Returns agent name, 'general', or '' if out of scope.
    """
    _INTENT_TO_AGENT = {
        "invoice": "a01_invoice",
        "bill":    "a01_invoice",   
        "po":      "a01_po",
        "expense": "a02_expense",
        "admin":   "a03_admin",
        "payment": "a04_payment",
    }

    if is_document:
        agent, confidence = _classify_document_agent(
            client_id, message, mime_type, filename, is_document
        )
        logger.info(
            "Document classified client=%s agent=%s confidence=%.2f",
            client_id, agent, confidence,
        )
        return agent

    agent_name = _INTENT_TO_AGENT.get(intent)
    if agent_name:
        return agent_name

    agent, confidence = _classify_document_agent(
        client_id, message, mime_type, filename, is_document
    )
    logger.info(
        "Fallback classify client=%s agent=%s confidence=%.2f",
        client_id, agent, confidence,
    )
    return agent


def _handle_general(message: str, client_id: str) -> dict:
    """Handle general queries — capabilities, integrations, help, greetings."""
    try:
        from agents.base_agent import _get_client
        from config.db_pool import get_conn

        connected = []
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT provider FROM client_integrations "
                    "WHERE client_id=%s AND connected=TRUE",
                    (client_id,),
                )
                connected = [r[0] for r in cur.fetchall()]
                cur.close()
        except Exception:
            pass

        system = """You are a helpful assistant for a financial operations platform.
Answer questions about capabilities, integrations, and how to use the platform naturally and warmly.

The platform supports:
- Invoices: create, send, track, remind, mark paid, list, check overdue, approve, edit
- Purchase Orders: create, list, track, find, edit, approve, remind, mark received
- Bills: log inbound vendor bills, list, track, edit
- Expenses: log, approve, reject, track, list, summary
- Payments: track, reconcile, remind, report, refund
- Admin: schedule meetings, file documents, find documents, track permits, send communications

Users interact via Telegram or WhatsApp using natural language.
Example commands:
- create invoice for Acme INR 5000 for consulting
- log expense $50 DHL logistics
- check overdue invoices
- schedule meeting with Acme tomorrow 3pm IST
- create PO for DHL 100 bags at 50 each

Integrations supported: Xero, QuickBooks, Google Calendar, Outlook, Google Drive, SharePoint, Gmail, Stripe.

FORMATTING RULES (strictly enforced):
- Use WhatsApp markdown only: *bold*, _italic_. Never use HTML tags like <b>, <i>, <code>.
- Be warm, concise, and helpful. Max 3 sentences.
- For greetings, respond naturally and mention 1-2 things you can help with.
- For capability questions, give concrete examples.
- If asked about connected integrations, use the list provided.
- Never say "I cannot" or "I don't support" — always suggest the closest available action."""

        user_msg = message
        if connected:
            user_msg = f"Connected integrations: {', '.join(connected)}\n\nUser message: {message}"

        response = _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        for block in response.content:
            if block.type == "text" and block.text.strip():
                return {"status": "success", "message": _to_whatsapp_md(block.text.strip()), "intent": "general"}
    except Exception as e:
        logger.error("_handle_general failed client=%s: %s", client_id, e)

    return {
        "status": "success",
        "message": "I handle invoices, purchase orders, bills, expenses, payments, and admin tasks. Try: _create invoice for Acme INR 5000_ or _check overdue invoices_.",
        "intent": "general",
    }

def route(
    client_id: str,
    message: str,
    sender: str = "",
    channel: str = "telegram",
    mime_type: str = "",
    filename: str = "",
    file_bytes: bytes = b"",
) -> dict:
    if not client_id or not _CLIENT_ID_RE.match(client_id):
        logger.warning("route() invalid client_id: %r", client_id)
        return {"status": "error", "message": "Invalid client identifier."}

    is_document = bool(mime_type and file_bytes)

    if (not message or not message.strip()) and not is_document:
        return {"status": "error", "message": "Empty message."}

    if is_document and not message:
        message = "document"

    if not is_document:
        message = message[:MAX_MESSAGE_LENGTH]
    maintenance = _check_maintenance()
    if maintenance:
        return maintenance

    active_agents = _load_active_agents(client_id)

    if is_document:
        agent_name = run_agent_task_dispatch(
            client_id=client_id,
            intent="",
            message=message,
            mime_type=mime_type,
            filename=filename,
            is_document=True,
        )
        confidence = 0.95
        intent = _AGENT_TO_INTENT.get(agent_name, "admin")
    else:
        try:
            result = classify_with_confidence(message, client_id=client_id)
            intent = str(result.get("intent", "unknown")).lower().strip()
            confidence = float(result.get("confidence", 0.0))
        except Exception as e:
            logger.error("Classification failed client=%s: %s", client_id, e)
            return {"status": "error", "message": "Classification error. Please try again."}

        from core.intelligence_loop import get_client_confidence
        threshold = get_client_confidence(client_id, intent)

        if (intent == "unknown" or confidence < threshold) and sender:
            try:
                from core.conversation import get_pending_intent as _get_pending
                pending = _get_pending(sender, client_id)
                pending_intent = pending.get("intent", "")
                if pending_intent and pending_intent != "unknown" and pending_intent in INTENT_TO_QUEUE:
                    logger.info(
                        "Correction fallback client=%s classified=%s conf=%.2f → using pending intent=%s",
                        client_id, intent, confidence, pending_intent,
                    )
                    intent = pending_intent
                    confidence = 0.80
            except Exception as e:
                logger.debug("Correction fallback failed (non-fatal) client=%s: %s", client_id, e)

        if intent == "unknown" or confidence < threshold:
            reply = _build_out_of_scope_reply(message, client_id)
            return {"status": "out_of_scope", "message": reply, "intent": intent, "confidence": confidence}

        if intent not in INTENT_TO_QUEUE:
            logger.warning("Unknown intent: %r client=%s", intent, client_id)
            return {"status": "out_of_scope", "message": _OUT_OF_SCOPE_MSG, "intent": intent}

    agent_name = INTENT_TO_AGENT.get(intent)
    if agent_name and agent_name != "general" and active_agents and agent_name not in active_agents:
        return {"status": "error", "message": "This feature isn't enabled on your account. Contact support.", "intent": intent}

    if agent_name and agent_name != "general" and _redis.exists(f"agent:paused:{client_id}:{agent_name}"):
        return {"status": "paused", "message": "This service is temporarily unavailable.", "intent": intent}

    if intent == "general" or agent_name == "general":
        return _handle_general(message, client_id)

    msg_hash = hashlib.sha256(message.encode()).hexdigest()
    dedup_key = f"dedup:{client_id}:{agent_name}:{msg_hash}"

    if not is_document:
        existing = _redis.get(dedup_key)
        if existing:
            return {"status": "queued", "task_id": existing, "intent": intent, "confidence": confidence, "deduplicated": True}

    from core.tasks import run_agent_task
    queue = INTENT_TO_QUEUE.get(intent, "normal")
    try:
        task = run_agent_task.apply_async( # type: ignore
            kwargs={
                "client_id":      client_id,
                "intent":         intent,
                "message":        message,
                "sender":         sender,
                "channel":        channel,
                "mime_type":      mime_type,
                "filename":       filename,
                "is_document":    is_document,
                "file_bytes_hex": file_bytes.hex() if file_bytes else "",
            },
            queue=queue,
        )
    except Exception as e:
        logger.error("Dispatch failed client=%s intent=%s: %s", client_id, intent, e)
        return {"status": "error", "message": "Failed to queue request. Please try again."}

    if not is_document:
        _redis.setex(dedup_key, IDEMPOTENCY_TTL, task.id)

    logger.info("Routed client=%s intent=%s queue=%s task=%s conf=%.2f", client_id, intent, queue, task.id, confidence)
    return {"status": "queued", "task_id": task.id, "intent": intent, "confidence": confidence, "queue": queue}




def _build_out_of_scope_reply(message: str, client_id: str) -> str:
    try:
        from agents.base_agent import _get_client
        response = _get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system="""You are a financial operations assistant.
A user sent a message that didn't match a known workflow exactly.

Your job: figure out what they likely wanted and suggest the closest supported action.

Supported workflows:
- Invoices: create, send, track, remind, mark paid, list, check overdue, approve, edit
- Purchase Orders: create, list, track, find, edit, approve, remind, mark received, check overdue
- Bills: log, list, find, track, edit, check overdue
- Expenses: log, approve, reject, track, list, summary, edit
- Payments: track, reconcile, remind, report, refund, dispute
- Admin: schedule meeting, file document, find document, track permit

FORMATTING RULES (strictly enforced):
- Use WhatsApp markdown only: *bold*, _italic_. Never use HTML tags like <b>, <i>, <code>.
- 1-2 sentences max.
- Suggest the most likely action they wanted with a concrete working example.
- Never say "I can't" or "out of scope". Always offer something useful.
- If their request is genuinely unrelated to finance/admin, politely redirect with an example.""",
            messages=[{"role": "user", "content": f"User said: {message}"}],
        )
        for block in response.content:
            if block.type == "text" and block.text.strip():
                return _to_whatsapp_md(block.text.strip())
    except Exception:
        pass

    return "Not sure what you meant — I handle invoices, expenses, POs, bills, and payments. Try: _create invoice for Acme INR 5000_ or _log expense 250 DHL logistics_."