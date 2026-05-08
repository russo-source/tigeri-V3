from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from tigeri.core.db import Base


class AuditLog(Base):
    """Tamper-evident, append-only audit log per the Phase 3 spec.

    Never UPDATE, never DELETE. The (signed_hash, prev_hash) chain makes
    after-the-fact mutation detectable.

    Heavy fields (full encrypted parameters, before/after diffs) live in
    object storage; the *_ref columns are S3/GCS keys.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("audit_logs_tenant_created_idx", "tenant_id", "created_at"),
        Index("audit_logs_tenant_event_idx", "tenant_id", "event_type"),
        Index("audit_logs_tenant_user_idx", "tenant_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id"), nullable=True
    )
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    capability: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    parameters_redacted: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parameters_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    diff_before_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    diff_after_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)

    xero_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    signed_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
