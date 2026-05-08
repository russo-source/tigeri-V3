"""Phase 2 — extend tenant_integrations with the spec's state-machine columns.

All additive, all nullable except `status` which gets server_default='active'
so existing rows (which were already connected) stay marked active.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_integrations",
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
    )
    op.add_column(
        "tenant_integrations",
        sa.Column("scopes_granted", sa.JSON(), nullable=True),
    )
    op.add_column(
        "tenant_integrations",
        sa.Column("authorized_by_user_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "tenant_integrations",
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenant_integrations",
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenant_integrations",
        sa.Column("last_health_status", sa.String(32), nullable=True),
    )
    op.add_column(
        "tenant_integrations",
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenant_integrations",
        sa.Column("xero_org_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "tenant_integrations",
        sa.Column("xero_org_name", sa.String(256), nullable=True),
    )

    if op.get_context().dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_tenant_integrations_authorized_by",
            "tenant_integrations",
            "users",
            ["authorized_by_user_id"],
            ["id"],
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS tenant_integrations_xero_org_idx "
            "ON tenant_integrations(tenant_id, xero_org_id) "
            "WHERE xero_org_id IS NOT NULL"
        )


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS tenant_integrations_xero_org_idx")
        op.drop_constraint(
            "fk_tenant_integrations_authorized_by",
            "tenant_integrations",
            type_="foreignkey",
        )

    op.drop_column("tenant_integrations", "xero_org_name")
    op.drop_column("tenant_integrations", "xero_org_id")
    op.drop_column("tenant_integrations", "last_sync_at")
    op.drop_column("tenant_integrations", "last_health_status")
    op.drop_column("tenant_integrations", "last_health_check_at")
    op.drop_column("tenant_integrations", "authorized_at")
    op.drop_column("tenant_integrations", "authorized_by_user_id")
    op.drop_column("tenant_integrations", "scopes_granted")
    op.drop_column("tenant_integrations", "status")
