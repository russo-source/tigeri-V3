"""Common scaffolding for LangGraph-based Tigeri agents."""

from __future__ import annotations

from abc import abstractmethod
from contextvars import ContextVar
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.agents.base import AgentRunContext, BaseAgent
from tigeri.graph.checkpointer import get_checkpointer, thread_id_for
from tigeri.graph.state import BaseAgentState, SessionContext
from tigeri.graph.tracing import configure_langsmith


# AsyncSession is not msgpack-serializable, so it cannot live inside the
# checkpointed graph state. Bind it to the running task via ContextVar instead.
_current_db_session: ContextVar[AsyncSession | None] = ContextVar(
    "_current_db_session", default=None
)


def current_db_session() -> AsyncSession:
    s = _current_db_session.get()
    if s is None:
        raise RuntimeError("no AsyncSession bound to this graph run")
    return s


class BaseGraphAgent(BaseAgent):
    """Agent that runs a LangGraph workflow.

    Subclasses implement :meth:`build_graph` and may extend the per-call state
    via a custom TypedDict. The base class wires:

    - LangSmith tracing (when configured)
    - Checkpointer for session memory (MemorySaver or PostgresSaver)
    - Audit logging at workflow start and end
    """

    state_schema: type = BaseAgentState

    def __init__(self, checkpointer: BaseCheckpointSaver | None = None) -> None:
        super().__init__()
        configure_langsmith()
        self._checkpointer = checkpointer or get_checkpointer()
        self._compiled = self.build_graph().compile(checkpointer=self._checkpointer)

    @abstractmethod
    def build_graph(self) -> StateGraph:
        """Return the uncompiled StateGraph defining this agent's workflow."""
        raise NotImplementedError

    @staticmethod
    def initial_session(ctx: AgentRunContext, session_id: str, user_id: str) -> SessionContext:
        return SessionContext(
            tenant_id=ctx.tenant_id,
            user_id=user_id,
            session_id=session_id,
            invocations=0,
            behaviour={},
        )

    async def run_graph(
        self,
        *,
        ctx: AgentRunContext,
        session_id: str,
        user_id: str,
        db_session: AsyncSession,
        initial: dict[str, Any],
    ) -> dict[str, Any]:
        thread_id = thread_id_for(ctx.tenant_id, user_id, session_id)
        config = {"configurable": {"thread_id": thread_id}}

        # Pull existing session state if any, so per-user behaviour persists.
        prior_state = await self._compiled.aget_state(config) if self._compiled else None
        prior_session = (
            prior_state.values.get("session")
            if prior_state and prior_state.values
            else None
        )
        session = prior_session or self.initial_session(ctx, session_id, user_id)
        session = dict(session)
        session["invocations"] = session.get("invocations", 0) + 1

        state: dict[str, Any] = {
            "messages": [],
            "session": session,
            "trace_id": ctx.trace_id,
            "result": {},
            "error": None,
            **initial,
        }
        token = _current_db_session.set(db_session)
        try:
            return await self._compiled.ainvoke(state, config=config)
        finally:
            _current_db_session.reset(token)

    @staticmethod
    def end() -> str:
        return END
