"""Contain context builder backend logic."""
from __future__ import annotations
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_MAX_MEMORY_CHARS    = 6400
_MAX_KNOWLEDGE_CHARS = 4000
_MAX_TASK_CHARS      = 1200
_MAX_ENTITY_CHARS    = 1600


def build_context(
    memory:    Optional[str] = None,
    knowledge: Optional[str] = None,
    task:      Optional[str] = None,
    client_id: Optional[str] = None,
    entity:    Optional[str] = None,
) -> dict:
    """Build context."""
    ctx: dict = {
        "client_id":   client_id or "",
        "memory":      _truncate(memory    or "", _MAX_MEMORY_CHARS),
        "knowledge":   _truncate(knowledge or "", _MAX_KNOWLEDGE_CHARS),
        "task":        _truncate(task      or "", _MAX_TASK_CHARS),
        "entity":      "",
        "entity_risk": "",
        "persona_line":"",
    }

    if client_id and entity:
        ctx["entity"]      = _get_entity_context(client_id, entity)
        ctx["entity_risk"] = _get_entity_risk_line(client_id, entity)

    if client_id:
        ctx["persona_line"] = _get_persona_line(client_id)

    return ctx


def format_for_llm(context: dict) -> str:
    """Execute format for llm."""
    parts: list[str] = []

    if context.get("persona_line"):
        parts.append(context["persona_line"])

    if context.get("memory"):
        parts.append(f"## Relevant History\n{context['memory']}")

    if context.get("entity"):
        parts.append(f"## Entity Context\n{context['entity']}")

    if context.get("entity_risk"):
        parts.append(f"## Risk Signal\n{context['entity_risk']}")

    if context.get("knowledge"):
        parts.append(f"## Relevant Knowledge\n{context['knowledge']}")

    if context.get("task"):
        parts.append(f"## Current Task\n{context['task']}")

    return "\n\n".join(parts)


def _get_entity_context(client_id: str, entity: str) -> str:
    """Return entity context."""
    try:
        from memory.entity_graph import get_entity_profile, format_entity_context
        profile = get_entity_profile(client_id, entity)
        raw     = format_entity_context(profile)
        return _truncate(raw, _MAX_ENTITY_CHARS)
    except Exception as exc:
        logger.debug("_get_entity_context non-fatal client=%s entity=%s: %s",
                     client_id, entity, exc)
        return ""


def _get_entity_risk_line(client_id: str, entity: str) -> str:
    """Return entity risk line."""
    try:
        from memory.entity_graph import get_entity_risk_score
        risk = get_entity_risk_score(client_id, entity)
        if risk > 0.35:
            pct = round(risk * 100)
            return f"Entity risk for {entity}: {pct}% probability of late payment (Bayesian estimate based on historical interactions)"
        return ""
    except Exception:
        return ""


def _get_persona_line(client_id: str) -> str:
    """Return persona line."""
    try:
        from core.intelligence_loop import get_client_persona, format_persona_for_prompt
        return format_persona_for_prompt(get_client_persona(client_id))
    except Exception as exc:
        logger.debug("_get_persona_line non-fatal client=%s: %s", client_id, exc)
        return ""


def _truncate(text: str, max_chars: int) -> str:
    """Execute truncate."""
    if len(text) > max_chars:
        return text[:max_chars] + "...[truncated]"
    return text