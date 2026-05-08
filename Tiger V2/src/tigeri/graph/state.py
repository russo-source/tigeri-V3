"""Shared LangGraph state types used by every Tigeri agent."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class SessionContext(TypedDict, total=False):
    """Per-user session memory persisted across agent runs.

    Stored under thread_id ``tenant_id:user_id:session_id`` by the
    checkpointer (see graph/checkpointer.py). Use this for behaviour signals
    the agent should remember between calls — e.g. "this user has had three
    rejections in a row" or "the last invoice they uploaded was a duplicate".
    """

    tenant_id: str
    user_id: str
    session_id: str
    invocations: int
    behaviour: dict[str, Any]


class BaseAgentState(TypedDict, total=False):
    """Top-level state for any agent graph."""

    # Conversation messages — used when the agent talks to the LLM.
    messages: Annotated[list[Any], add_messages]
    # Per-user session memory.
    session: SessionContext
    # Tigeri trace correlation id (mirrors the audit trace_id).
    trace_id: str
    # Result so far — agents append to this dict as nodes execute.
    result: dict[str, Any]
    # Surfaced error, if any node failed.
    error: str | None
