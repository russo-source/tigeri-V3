from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from tigeri.core.db import Base


class AuditRecord(Base):
    """Append-only audit record.

    Section 5.4 of TIGERI_AGENT_CATALOG_v1.md: every agent action emits one
    record. `chain_position` and `backfilled_at` remain NULL until Compliance
    & Audit Agent (Priority 12) is live and migrates this row into the
    immutable trail (Section 10 build-sequence gate criterion).
    """

    __tablename__ = "audit_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_resource: Mapped[str] = mapped_column(String(256), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    chain_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    backfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
