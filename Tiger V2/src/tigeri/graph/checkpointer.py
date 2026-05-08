"""Session-state checkpointing for LangGraph workflows.

Default: in-process MemorySaver (kept for the lifetime of the FastAPI worker).
Production: PostgresSaver, sharing the existing tigeri Postgres.

The checkpointer is keyed by ``thread_id``, which Tigeri composes from
``tenant_id:user_id:session_id`` so behaviour is namespaced per user.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from tigeri.core.config import get_settings


_memory_singleton: MemorySaver | None = None


def get_checkpointer() -> BaseCheckpointSaver:
    settings = get_settings()
    if settings.session_checkpointer == "memory":
        global _memory_singleton
        if _memory_singleton is None:
            _memory_singleton = MemorySaver()
        return _memory_singleton

    if settings.session_checkpointer == "postgres":
        # Lazy import — only required when explicitly enabled.
        from langgraph.checkpoint.postgres import PostgresSaver

        # PostgresSaver expects a sync DSN; convert from sqlalchemy+asyncpg form.
        dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        saver = PostgresSaver.from_conn_string(dsn)
        saver.setup()
        return saver

    raise ValueError(
        f"unknown session_checkpointer: {settings.session_checkpointer!r} (memory|postgres)"
    )


def thread_id_for(tenant_id: str, user_id: str, session_id: str) -> str:
    """Compose the per-user thread id used by the checkpointer."""

    return f"{tenant_id}:{user_id}:{session_id}"
