from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from tigeri.core.db import Base


class TenantIntegration(Base):
    """One per (tenant, provider). Stores OAuth tokens encrypted at rest.

    Phase 2 added the state-machine columns from the spec
    (status, scopes_granted, authorized_by_user_id, last_health_check_at,
    last_health_status, last_sync_at, plus Xero-specific xero_org_id /
    xero_org_name) on top of the original Slice 1 schema. All new columns are
    nullable so pre-Phase-2 rows keep working.
    """

    __tablename__ = "tenant_integrations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_tenant_provider"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)

    # Encrypted access + refresh tokens (Fernet via TIGERI_SECRET_ENCRYPTION_KEY).
    access_token_enc: Mapped[str] = mapped_column(String(2048), nullable=False)
    refresh_token_enc: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    access_token_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Provider-specific metadata, e.g. Xero tenant_id, scope, identity.
    meta_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Phase 2 spec columns ------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active"
    )  # pending | active | token_expired | scope_insufficient | disconnected | error
    scopes_granted: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True
    )  # JSON array — works on both Postgres and SQLite for tests
    authorized_by_user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id"), nullable=True
    )
    authorized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_health_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Xero-specific. The same column names work for QuickBooks (realm id) etc.
    # if we generalise later; for now keep them xero-prefixed per spec.
    xero_org_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    xero_org_name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) >= self.access_token_expires_at


__all__ = ["TenantIntegration"]
