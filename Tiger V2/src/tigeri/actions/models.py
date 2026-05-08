from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from tigeri.core.db import Base


class PendingAction(Base):
    """A write action proposed by the AI but not yet executed.

    Lifecycle: pending -> confirmed -> executed (success path)
                       -> cancelled / expired / failed (error paths)

    The `confirmation_token` UNIQUE constraint guarantees a token can be used
    at most once. The partial unique index on
    (tenant_id, idempotency_key) WHERE status='executed' prevents the same
    capability invocation from being executed twice (handles double-click,
    network retry).
    """

    __tablename__ = "pending_actions"
    __table_args__ = (
        Index(
            "uq_pending_actions_idempotency",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where="status = 'executed'",
        ),
        Index("pending_actions_status_expires_idx", "status", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id"), nullable=False
    )
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    capability: Mapped[str] = mapped_column(String(128), nullable=False)
    parameters_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    diff_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    confirmation_token: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="web")

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
