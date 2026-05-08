"""Defensive guardrails for chat input → tool execution.

Two concerns this module covers:

1. **Prompt injection** — a user message (or the contents of an uploaded file
   that we surface to the model) can try to override the system prompt with
   "ignore previous instructions" style payloads. We can't make this
   impossible — the LLM is the one deciding — but we can surface a clear
   refusal-cue and refuse to forward arguments that look like exfiltration of
   privileged config to an LLM tool call.

2. **Tool-argument abuse** — even after the LLM picks a tool, the orchestrator
   forwards `args` verbatim. We sanitise structured arg values (recursively)
   so a model that's been talked into "set tenant_id=tnt_other" can't actually
   leak across tenants and so a model that wedged a curl-style command into a
   string field doesn't end up echoed in our audit trail.

Both checks return ``(ok, reason)`` so callers can decide whether to short-
circuit (we do, for any args mismatch) and surface a friendly error to the
user without leaking the rule itself."""

from __future__ import annotations

import re
from typing import Any

# --- Prompt-injection cues -------------------------------------------------
# These patterns are intentionally conservative — we only block on the most
# unambiguous override phrases. The cost of a false positive (refusing a real
# question that happens to use these words) is much higher than the cost of a
# false negative (the model already has its own training and the system
# prompt also instructs it to ignore overrides).

_INJECTION_PATTERNS = [
    re.compile(r"\bignore\s+(all\s+)?previous\s+(instructions|messages|prompts)\b", re.I),
    re.compile(r"\bdisregard\s+(all\s+)?previous\b", re.I),
    re.compile(r"\bsystem\s*prompt\s*[:=]", re.I),
    re.compile(r"\b(reveal|print|dump|show)\s+(your\s+)?system\s+prompt\b", re.I),
    re.compile(r"\byou\s+are\s+now\s+a\s+", re.I),
    re.compile(r"<\s*\|?\s*(im_start|im_end|system|user|assistant)\s*\|?\s*>", re.I),
]


def detect_injection(text: str) -> str | None:
    """Return the first matching pattern's name, or None if clean.

    Used for *logging* not for hard refusal — we still send the message to
    the LLM (it's better at refusing than a regex), but we tag the audit
    record so a flood of injection attempts surfaces in dashboards."""

    if not text:
        return None
    for pat in _INJECTION_PATTERNS:
        if pat.search(text):
            return pat.pattern
    return None


# --- Tool-argument scoping -------------------------------------------------

# Keys the model is never allowed to set on a tool call — we override these
# from the request scope on the server side. If the model tries to set them
# the orchestrator quietly drops them; we don't fail because the model often
# guesses tenant_id from context as a helpful gesture.
SCOPE_OVERRIDE_KEYS = {"tenant_id", "user_id", "actor", "scope"}

# Keys the model must NEVER set, period. Setting these in args would be an
# escalation attempt — we refuse the whole call.
FORBIDDEN_KEYS = {"role", "is_admin", "admin", "bypass", "override_tenant"}

# Hard cap on string arg length to prevent the model from being nudged into
# echoing a giant payload (e.g. exfiltrating a DB row through the args field).
MAX_STR_ARG = 4000


def scope_tool_args(
    args: dict[str, Any],
    *,
    tenant_id: str,
    user_id: str,
) -> tuple[dict[str, Any], str | None]:
    """Sanitise tool-call args before dispatch.

    Returns (scoped_args, refusal_reason). When refusal_reason is non-None the
    orchestrator must NOT execute the tool — it should surface the reason to
    the user and end the turn.

    Rules:
    - Drop `tenant_id` / `user_id` / `actor` from args (they come from session
      scope, never the model).
    - Refuse if any FORBIDDEN_KEYS appear (role-escalation attempt).
    - Truncate string values to MAX_STR_ARG.
    - Recursively walk dict / list values."""

    if not isinstance(args, dict):
        return ({}, "tool args must be an object")

    for k in args:
        if k in FORBIDDEN_KEYS:
            return ({}, f"tool args may not set {k!r}")

    cleaned: dict[str, Any] = {}
    for k, v in args.items():
        if k in SCOPE_OVERRIDE_KEYS:
            continue
        cleaned[k] = _scrub(v)

    cleaned["tenant_id"] = tenant_id
    cleaned["user_id"] = user_id
    return (cleaned, None)


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return value[:MAX_STR_ARG]
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k not in FORBIDDEN_KEYS}
    return value
