"""Chat persistence models.

Class names are unchanged from Slice 1 (ChatThread / ChatMessage /
ChatFeedback) for code-stability reasons; the underlying tables were
renamed in migration 0010 to match the Phase 3 spec
(``conversations`` / ``messages`` / ``message_feedback``).

Migration 0009 added the spec's metadata columns:
  - chat_messages: tenant_id (denorm), content_encrypted, content_redacted,
    agent_name, model, prompt_version, input_tokens, output_tokens,
    cost_micro_usd, latency_ms, grounding_verified
  - chat_threads: title, status, channel, context_json, message_count,
    last_active_at

Encryption: ``content`` is the legacy plaintext column kept for back-compat
with pre-0009 rows. New writes go to ``content_encrypted`` (Fernet via
``TIGERI_SECRET_ENCRYPTION_KEY``). The store layer in tigeri.chat.store
decrypts on read and falls back to ``content`` when no encrypted value is
present.
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from tigeri.core.db import Base


class ChatThread(Base):
    """One per (tenant, user, session). The DB table is `conversations`."""

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "session_id", name="uq_chat_thread"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)

    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="web")
    context_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ChatMessage(Base):
    """One row per turn. The DB table is `messages`.

    `actions_json` keeps the legacy embedded tool-call/result list so reload
    reproduces the chat view. The Phase 3 spec wants per-LLM-message rows
    (separate tool_call / tool_result entries); migrating to that shape is
    a future refactor and intentionally not part of 0009/0010.
    """

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Denormalised tenant_id so admin queries can filter without a join.
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)

    # Pre-0009 plaintext column. New writes leave this empty and populate
    # content_encrypted instead.
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)

    actions_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Provenance + cost (per spec).
    agent_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_micro_usd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grounding_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ChatFeedback(Base):
    """Thumbs up/down per assistant message. The DB table is `message_feedback`."""

    __tablename__ = "message_feedback"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    message_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # +1 / -1
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
