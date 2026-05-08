"""Goal decomposition and planning for the autonomous agent loop - dynamic tool catalog."""
from __future__ import annotations

import json
import logging
import re
from typing import NamedTuple

from agents.base_agent import _get_client

logger = logging.getLogger(__name__)

_HAIKU  = "claude-haiku-4-5-20251001"
_SONNET = "claude-sonnet-4-6"

_SINGLE_ACTION_PATTERNS = [
    r"^(create|make|generate)\s+invoice",
    r"^(log|add|capture)\s+expense",
    r"^(create|make)\s+po\b",
    r"^(create|make)\s+purchase\s+order",
    r"^(send|email)\s+invoice",
    r"^(mark|set)\s+.+\s+paid",
    r"^(approve|reject)\s+expense",
    r"^(schedule|book)\s+meeting",
    r"^(find|search|look\s+for)\s+.+\s+(document|file|contract)",
    r"^(track|check)\s+payment",
    r"^(generate|create)\s+.+\s+report",
    r"^(list|show|get)\s+(all\s+)?(invoices|expenses|bills|pos|meetings|documents)",
    r"^(check|find)\s+overdue",
    r"^reconcile\b",
    r"^refund\b",
]

_MULTI_STEP_SIGNALS = [
    "and then", "after that", "also", "then", "followed by",
    "as well as", "plus", "additionally", "next",
    "clean up", "process all", "handle all", "go through all",
    "for each", "for every", "all overdue", "all pending",
    "send reminders to all", "remind all",
]

_COMPLEXITY_SYSTEM = """You are a task complexity classifier for a financial operations platform.

Given a user message, determine if it requires a single action or multiple sequential steps.

SINGLE action examples:
- "create invoice for Acme USD 500"
- "log expense $50 DHL"
- "send reminder for INV-001"
- "check overdue invoices"
- "approve expense for Uber"
- "schedule meeting with Acme tomorrow 3pm"

MULTI-STEP examples:
- "check all overdue invoices and send reminders to each one"
- "find the Acme contract, read it, and summarise the payment terms"
- "create invoice for DHL, approve it, then send it to billing@dhl.com"
- "list all pending expenses and approve the ones under $200"
- "check cash flow report and send it to the CFO"

Reply ONLY with JSON. No preamble.
{"is_multi_step": false, "confidence": 0.95, "reason": "single invoice creation"}"""

_DECOMPOSE_SYSTEM_HEADER = """You are a task planner for a financial operations AI platform.

Break down the user's request into an ordered list of tool calls needed to complete it.

The following tools are currently available (pulled live from the platform):

{tool_catalog}

RULES:
- Only include steps that are actually needed
- Order steps logically - reads before writes, checks before actions
- Use concrete values from the message where available
- For "all overdue" / "all pending" patterns, plan a list step first, then the action (Claude will handle iteration in the loop)
- Maximum 6 steps - if more are needed, simplify
- If a step depends on the result of a previous step, set depends_on to that step number

Reply ONLY with JSON. No preamble.
{
  "steps": [
    {
      "step": 1,
      "agent": "a01_invoice",
      "tool": "check_overdue",
      "input": {},
      "reason": "Find all overdue invoices first",
      "depends_on": null
    },
    {
      "step": 2,
      "agent": "a01_invoice",
      "tool": "send_reminder",
      "input": {"vendor": null},
      "reason": "Send reminder for each overdue invoice found in step 1",
      "depends_on": 1
    }
  ],
  "summary": "Check overdue invoices then send reminders to each"
}"""

_AGENT_MAP = {
    "a01_invoice": ("agents.a01_invoice.agent", "InvoiceAgent"),
    "a02_expense": ("agents.a02_expense.agent", "ExpenseAgent"),
    "a03_admin":   ("agents.a03_admin.agent",   "AdminAgent"),
    "a04_payment": ("agents.a04_payment.agent", "PaymentAgent"),
}

_tool_catalog_cache: str | None = None


class PlanStep(NamedTuple):
    step:       int
    agent:      str
    tool:       str
    input:      dict
    reason:     str
    depends_on: int | None


class Plan(NamedTuple):
    steps:   list[PlanStep]
    summary: str


def _build_tool_catalog(client_id: str = "planner") -> str:
    """
    Build the tool catalog at runtime by calling get_tools() on each agent.
    Always in sync with base_tools.py - no static copy to maintain.
    Cached for the process lifetime - call invalidate_tool_catalog_cache() to reset.
    """
    global _tool_catalog_cache
    if _tool_catalog_cache is not None:
        return _tool_catalog_cache

    lines: list[str] = []
    for agent_key, (module_path, class_name) in _AGENT_MAP.items():
        try:
            import importlib
            module   = importlib.import_module(module_path)
            cls      = getattr(module, class_name)
            instance = cls(client_id=client_id)
            tools    = instance.get_tools()
            if not tools:
                continue
            lines.append(f"\n{agent_key.upper()} (agent: {agent_key}):")
            for tool in tools:
                name        = tool.get("name", "")
                description = tool.get("description", "")
                schema      = tool.get("input_schema", {})
                props       = schema.get("properties", {})
                required    = schema.get("required", [])
                req_params  = [p for p in props if p in required]
                opt_params  = [f"[{p}]" for p in props if p not in required]
                param_str   = ", ".join(req_params + opt_params)
                lines.append(f"  - {name}({param_str})")
                lines.append(f"    {description}")
        except Exception as exc:
            logger.warning("_build_tool_catalog failed for %s: %s", agent_key, exc)

    catalog = "\n".join(lines)
    _tool_catalog_cache = catalog
    return catalog


def invalidate_tool_catalog_cache() -> None:
    global _tool_catalog_cache
    _tool_catalog_cache = None


def should_plan(message: str, intent: str = "") -> bool:
    lower = message.lower().strip()

    for pattern in _SINGLE_ACTION_PATTERNS:
        if re.search(pattern, lower):
            return False

    for signal in _MULTI_STEP_SIGNALS:
        if signal in lower:
            return True

    word_count   = len(lower.split())
    action_verbs = sum(
        1 for v in ("create", "send", "approve", "check", "find", "list",
                     "schedule", "track", "remind", "generate", "reconcile")
        if v in lower
    )
    if word_count > 12 and action_verbs >= 2:
        return True

    return False


def classify_complexity(message: str) -> tuple[bool, float]:
    try:
        response = _get_client().messages.create(
            model=_HAIKU,
            max_tokens=100,
            system=_COMPLEXITY_SYSTEM,
            messages=[{"role": "user", "content": message}],
        )
        for block in response.content:
            if block.type == "text":
                text  = re.sub(r"^```(?:json)?\s*", "", block.text.strip(), flags=re.IGNORECASE)
                text  = re.sub(r"\s*```$", "", text).strip()
                match = re.search(r'\{[^}]+\}', text, re.DOTALL)
                if match:
                    parsed     = json.loads(match.group())
                    is_multi   = bool(parsed.get("is_multi_step", False))
                    confidence = float(parsed.get("confidence", 0.8))
                    logger.debug("classify_complexity: is_multi=%s conf=%.2f reason=%s",
                                 is_multi, confidence, parsed.get("reason", ""))
                    return is_multi, confidence
    except Exception as exc:
        logger.warning("classify_complexity LLM failed, using heuristic: %s", exc)

    return should_plan(message), 0.7


def decompose_goal(
    message:    str,
    context:    str = "",
    client_id:  str = "planner",
    use_sonnet: bool = False,
) -> Plan | None:
    model        = _SONNET if use_sonnet else _HAIKU
    tool_catalog = _build_tool_catalog(client_id)
    system       = _DECOMPOSE_SYSTEM_HEADER.format(tool_catalog=tool_catalog)
    user_content = f"Context:\n{context}\n\nRequest:\n{message}" if context else message

    try:
        response = _get_client().messages.create(
            model=model,
            max_tokens=800,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        for block in response.content:
            if block.type != "text":
                continue
            text  = re.sub(r"^```(?:json)?\s*", "", block.text.strip(), flags=re.IGNORECASE)
            text  = re.sub(r"\s*```$", "", text).strip()
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if not match:
                continue

            parsed    = json.loads(match.group())
            raw_steps = parsed.get("steps", [])
            summary   = parsed.get("summary", "")

            if not raw_steps:
                return None

            steps = [
                PlanStep(
                    step=       s.get("step", i + 1),
                    agent=      s.get("agent", ""),
                    tool=       s.get("tool", ""),
                    input=      s.get("input") or {},
                    reason=     s.get("reason", ""),
                    depends_on= s.get("depends_on"),
                )
                for i, s in enumerate(raw_steps)
                if s.get("tool")
            ]

            if not steps:
                return None

            if not use_sonnet and len(steps) == 1 and len(message.split()) > 15:
                logger.info("decompose_goal: escalating to Sonnet")
                return decompose_goal(message, context, client_id, use_sonnet=True)

            logger.info("decompose_goal: %d steps model=%s summary=%s",
                        len(steps), model, summary[:80])
            return Plan(steps=steps, summary=summary)

    except json.JSONDecodeError as exc:
        logger.warning("decompose_goal JSON parse failed model=%s: %s", model, exc)
        if not use_sonnet:
            return decompose_goal(message, context, client_id, use_sonnet=True)
    except Exception as exc:
        logger.error("decompose_goal failed model=%s: %s", model, exc)

    return None


def plan_and_summarise(
    message:   str,
    context:   str = "",
    client_id: str = "planner",
) -> tuple[Plan | None, bool]:
    if not should_plan(message):
        return None, False

    is_multi, confidence = classify_complexity(message)
    if not is_multi:
        logger.debug("plan_and_summarise: LLM says single-step (conf=%.2f)", confidence)
        return None, False

    plan = decompose_goal(message, context, client_id)
    if not plan or not plan.steps:
        logger.debug("plan_and_summarise: decomposition empty - treating as single-step")
        return None, False

    return plan, True


def format_plan_for_log(plan: Plan) -> str:
    lines = [f"Plan: {plan.summary}", "Steps:"]
    for s in plan.steps:
        dep = f" (after step {s.depends_on})" if s.depends_on else ""
        lines.append(f"  {s.step}. [{s.agent}] {s.tool}{dep} - {s.reason}")
    return "\n".join(lines)