"""Drop spurious write tool_use calls when the user clearly asked a
read-only question.

Background: Gemini 2.5 Flash (and to a lesser extent Claude) routinely
chains write tools onto an unrelated read intent. Concretely, "find me a
restaurant in Kerala" was producing send_gmail + create_calendar_event +
find_place in one round — the user never asked to email or schedule
anything, but the model carries forward context from the previous turn
and re-invokes those tools.

The system prompt tells the model not to do this. Real-world behaviour
shows that's not enough. So we add a deterministic post-filter: if the
user's message looks read-only AND the model emitted at least one
read-only tool call, drop any write tool calls from the same round.

This is heuristic, not perfect. It deliberately errs on the side of
suppressing extras — the worst case is the user has to repeat their
write request, which is trivially recoverable. The opposite failure
(executing a side effect they didn't ask for) is much worse."""

from __future__ import annotations

import re

# Tools that are explicitly read-only — calling these is always free of
# side effects. Mirror this list with the orchestrator's WRITE_TOOLS so
# the inverse stays obvious. Keep this in sync if new tools are added.
READ_TOOLS: set[str] = {
    "list_agents",
    "list_recent_audit",
    "list_integrations_status",
    "get_connect_url",
    "list_calendar_events",
    "geocode_address",
    "find_place",
    "compute_travel_time",
    "get_weather",
    "read_sheet",
    "invoke_financial_reporting_agent",  # P&L roll-up: read-only by design
}


# Phrasings that strongly imply a read-only question. These are the
# common openings users actually type. We match the start of the
# (lower-cased) message rather than substrings — "send me a find" is too
# pathological to worry about.
_READ_INTENT = re.compile(
    r"^\s*(?:also,?\s+)?(?:please\s+|can you\s+|could you\s+)?"
    r"(?:find|show|list|where|what'?s|what is|look ?up|search|check|"
    r"do i have|how (?:long|far|many)|how's the weather|"
    r"is there|tell me about|give me|fetch|see|view)\b",
    re.IGNORECASE,
)


def _looks_read_only(user_message: str) -> bool:
    """True iff the user's message reads like a question / lookup, not a
    request to do a write side-effect. False on anything ambiguous —
    we'd rather let the model decide than over-suppress."""
    if not user_message:
        return False
    return bool(_READ_INTENT.match(user_message))


def filter_tool_calls(
    *,
    user_message: str,
    tool_names: list[str],
    write_tools: set[str],
) -> tuple[list[int], str | None]:
    """Decide which of the model's tool calls to actually run.

    Returns (kept_indices, suppression_reason). `kept_indices` is a list of
    indices into ``tool_names`` that should be honoured; anything outside
    the list is dropped. ``suppression_reason`` is a string that explains
    the drop in operator-friendly terms — None when no suppression
    occurred.

    Rules:
      1. If the message is NOT obviously read-only → keep all calls.
      2. If the message IS read-only AND no read tools were called →
         keep all calls (we can't infer a safer alternative).
      3. If the message IS read-only AND at least one read tool was
         called → drop any write tools."""

    if not tool_names:
        return ([], None)

    if not _looks_read_only(user_message):
        return (list(range(len(tool_names))), None)

    has_read = any(t in READ_TOOLS for t in tool_names)
    has_write = any(t in write_tools for t in tool_names)
    if not has_read or not has_write:
        return (list(range(len(tool_names))), None)

    kept = [i for i, t in enumerate(tool_names) if t not in write_tools]
    dropped = [t for i, t in enumerate(tool_names) if i not in kept]
    return (
        kept,
        f"Dropped write tool(s) {dropped} — user message reads as a read-only "
        "lookup, write tools require explicit user intent.",
    )
