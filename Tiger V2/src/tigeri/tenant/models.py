from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from tigeri.core.db import Base


class Tenant(Base):
    """One company workspace. Outermost tenant-isolation boundary.

    Migration 0006 added slug/region/plan/status/settings/updated_at on top of
    the original Slice 1 columns and backfilled defaults for existing rows
    (slug = id, region = 'sg', plan = 'pilot', status = 'active'). Treat slug
    as immutable after first use — changing it breaks bookmarked URLs.
    """

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    region: Mapped[str] = mapped_column(String(8), nullable=False, default="sg")
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="pilot")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Activation-time facts (kept from the original Slice 1 schema).
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    employee_count: Mapped[int | None] = mapped_column(nullable=True)
    venues_or_locations: Mapped[int | None] = mapped_column(nullable=True)
    regulated: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class Integration(Base):
    """Capability-category metadata for a tenant. NOT the OAuth tokens table —
    that lives in tigeri.integrations.models.TenantIntegration.
    """

    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("tenant_id", "category", name="uq_integration_per_tenant"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    access_pattern: Mapped[str] = mapped_column(String(8), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class AgentDeployment(Base):
    __tablename__ = "agent_deployments"
    __table_args__ = (UniqueConstraint("tenant_id", "agent_id", name="uq_agent_per_tenant"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    deployed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
