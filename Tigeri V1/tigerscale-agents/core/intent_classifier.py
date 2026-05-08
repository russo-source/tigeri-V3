"""Contain intent classifier backend logic."""
import json
import logging
import re

from agents.base_agent import _get_client

logger = logging.getLogger(__name__)
MAX_CLASSIFY_LEN = 2000


_SYSTEM_PROMPT = """You are an intent classifier for a business financial automation system.
Classify the user message into exactly one intent. Return JSON only.

INTENTS AND WHAT THEY COVER:

invoice:
  Creating, sending, tracking, listing, approving, editing invoices sent TO customers.
  Keywords: invoice, bill someone, "make one for", "send it to [client]", overdue invoices,
  approve invoice, mark invoice paid, list invoices, pending invoices, authorized invoices.
  Examples:
  - "create invoice for Acme 5000" -> invoice
  - "list all invoices" -> invoice
  - "show me all invoices" -> invoice
  - "any overdue invoices" -> invoice
  - "approve all pending invoices" -> invoice
  - "whats pending" (in invoice context) -> invoice
  - "paid ones" -> invoice
  - "show me the invoices" -> invoice
  - "give me the invoices" -> invoice
  - "pull up invoices" -> invoice

bill:
  Inbound bills/invoices RECEIVED FROM vendors and suppliers. Logging, listing, tracking vendor bills.
  Keywords: bill from [vendor], vendor bill, supplier bill, received invoice, log bill, record bill,
  list bills, show bills, find bill, track bill, overdue bills.
  Examples:
  - "log bill from Acme INR 5000" -> bill
  - "list all the bills" -> bill
  - "show me my bills" -> bill
  - "give me the bills" -> bill
  - "show me the bills" -> bill
  - "pull up the bills" -> bill
  - "what bills do we have" -> bill
  - "any overdue bills" -> bill
  - "find bill from Good Grocery" -> bill
  - "track bill for Raj" -> bill
  - "got a bill from supplier" -> bill

expense:
  Employee expenses, receipts, spend tracking, expense reports, monthly summaries.
  Keywords: expense, receipt, spend, spending, log expense, capture expense, list expenses,
  show expenses, what did we spend, monthly summary, expense report.
  Examples:
  - "log expense 500 DHL" -> expense
  - "list all the expenses" -> expense
  - "show me the expenses" -> expense
  - "give me the expenses" -> expense
  - "pull up expenses" -> expense
  - "what are my expenses" -> expense
  - "show expenses" -> expense
  - "list expenses" -> expense
  - "uber 500 travel" -> expense
  - "how much did we spend" -> expense
  - "monthly spending summary" -> expense
  - "expense report" -> expense

po:
  Purchase orders — creating, listing, approving, editing, tracking POs.
  Examples:
  - "create PO for DHL" -> po
  - "list all POs" -> po
  - "approve PO-1234" -> po
  - "open purchase orders" -> po

payment:
  Tracking payments received, reconciliation, cash flow, payouts.
  Examples:
  - "track payment from Acme" -> payment
  - "mark payment received" -> payment
  - "cash flow report" -> payment

admin:
  Meetings, documents, files, folders, permits, calendar, communications.
  Examples:
  - "schedule meeting with Acme tomorrow 3pm" -> admin
  - "list all documents" -> admin
  - "find contract for Acme" -> admin
  - "create folder Invoices" -> admin
  - "upload document" -> admin

general:
  Greetings, small talk, capability questions, how-to guidance, integration status checks.
  Examples:
  - "hi", "hello", "thanks" -> general
  - "what can you do" -> general
  - "how do I create an invoice" -> general
  - "is xero connected" -> general
  - "what integrations are active" -> general
  - "help" -> general

unknown:
  Anything completely unrelated to finance or business operations.
  Examples: weather, sports, recipes, coding help, general knowledge.

CRITICAL DISAMBIGUATION RULES:

1. bill vs expense vs invoice:
   - bill = inbound from a VENDOR (you owe them) → "bill from", "vendor bill", "supplier invoice"
   - expense = employee spend / receipts / cost tracking → "expense", "receipt", "spend", "what did we spend"
   - invoice = outbound to a CUSTOMER (they owe you) → "invoice for [client]", "bill [client]"

2. "give me the X" / "show me the X" / "pull up X" / "list X" / "what are my X":
   - "give me the bills" -> bill
   - "give me the expenses" -> expense
   - "give me the invoices" -> invoice
   - "show me the bills" -> bill
   - "show me the expenses" -> expense
   These are ALWAYS classified by the noun, never ambiguous.

3. Guidance vs action:
   - "how do I create an invoice" -> general (asking HOW)
   - "create invoice for Acme" -> invoice (DOING it)

4. List queries — classify by the NOUN being listed:
   - "list all the bills" -> bill
   - "list all the expenses" -> expense
   - "list all invoices" -> invoice
   - "list all POs" -> po
   - "list all documents" -> admin

5. Ambiguous list queries with no noun:
   - "show me everything" -> general (ask for clarification)
   - "list all" (no noun) -> general

Reply with JSON only. No preamble.
{"intent": "bill", "confidence": 0.97}

Confidence guide:
- 0.95-0.99: crystal clear intent
- 0.80-0.94: clear but slightly ambiguous phrasing
- 0.70-0.79: context-dependent, best guess
- below 0.70: genuinely unclear"""


def _parse_json(text: str) -> dict | None:
    """Parse json."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r'\{[^}]+\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    logger.warning("Could not parse classifier JSON from: %.100r", text)
    return None


def _build_system_prompt(message: str, client_id: str = "") -> str:
    """Build system prompt."""
    prompt = _SYSTEM_PROMPT

    if client_id:
        try:
            from core.intelligence_loop import get_client_persona, format_persona_for_prompt
            persona_line = format_persona_for_prompt(get_client_persona(client_id))
            if persona_line:
                prompt = prompt + f"\n\n{persona_line}"
        except Exception as exc:
            logger.debug("persona injection failed (non-fatal): %s", exc)

    try:
        from core.intelligence_loop import get_classifier_examples
        examples = get_classifier_examples(message, top_k=5)
        if examples:
            prompt = prompt + f"\n\nReal production examples for reference:\n{examples}"
    except Exception as exc:
        logger.debug("get_classifier_examples failed (non-fatal): %s", exc)

    return prompt


def classify_with_confidence(
    message: str,
    client_id: str = "",
    _retry: bool = False,
) -> dict:
    """Execute classify with confidence."""
    message = message[:MAX_CLASSIFY_LEN]

    model = "claude-sonnet-4-6" if _retry else "claude-haiku-4-5-20251001"
    system = _build_system_prompt(message, client_id)

    try:
        res = _get_client().messages.create(
            model=model,
            max_tokens=100,
            system=system,
            messages=[{"role": "user", "content": message}],
        )
        for block in res.content:
            if block.type == "text":
                parsed = _parse_json(block.text)
                if parsed:
                    confidence = float(parsed.get("confidence", 0.0))
                    if confidence < 0.7 and not _retry:
                        logger.info(
                            "Haiku low confidence %.2f for '%s' — retrying with Sonnet",
                            confidence, message[:60],
                        )
                        return classify_with_confidence(message, client_id, _retry=True)
                    return {
                        "intent":     str(parsed.get("intent", "unknown")).lower().strip(),
                        "confidence": max(0.0, min(1.0, confidence)),
                    }
    except Exception as e:
        logger.error("classify_with_confidence model=%s: %s", model, e)
        if not _retry:
            return classify_with_confidence(message, _retry=True)
    return {"intent": "unknown", "confidence": 0.0}