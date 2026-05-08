"""init schema: tenants, integrations, agent_deployments, invoices, audit_records

Revision ID: 0001
Revises:
Create Date: 2026-04-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("industry", sa.String(128), nullable=True),
        sa.Column("employee_count", sa.Integer(), nullable=True),
        sa.Column("venues_or_locations", sa.Integer(), nullable=True),
        sa.Column("regulated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "integrations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("category", sa.String(128), nullable=False),
        sa.Column("access_pattern", sa.String(8), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "category", name="uq_integration_per_tenant"),
    )

    op.create_table(
        "agent_deployments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "deployed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "agent_id", name="uq_agent_per_tenant"),
    )

    op.create_table(
        "invoices",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("vendor_name", sa.String(256), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("invoice_number", sa.String(128), nullable=True, index=True),
        sa.Column("po_reference", sa.String(128), nullable=True),
        sa.Column("line_items_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("validation_status", sa.String(32), nullable=False),
        sa.Column("approval_status", sa.String(32), nullable=False),
        sa.Column("posting_status", sa.String(32), nullable=False),
        sa.Column("posting_reference", sa.String(128), nullable=False, server_default=""),
        sa.Column("document_hash", sa.String(64), nullable=False, index=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "audit_records",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_resource", sa.String(256), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False, index=True),
        sa.Column("timestamp_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("chain_position", sa.Integer(), nullable=True),
        sa.Column("backfilled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("audit_records")
    op.drop_table("invoices")
    op.drop_table("agent_deployments")
    op.drop_table("integrations")
    op.drop_table("tenants")
