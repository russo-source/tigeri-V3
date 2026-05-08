"""add phase 1 priority 6-8 tables: financial_reports, contracts, onboardings

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "financial_reports",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("report_type", sa.String(32), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revenue_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("expense_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("net_income", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("cash_in", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("cash_out", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("kpis_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("rendered_artifact_ref", sa.String(256), nullable=False, server_default=""),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "contracts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("counterparty", sa.String(256), nullable=False),
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expiry_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("auto_renewal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("contract_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("key_terms_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("lifecycle_state", sa.String(32), nullable=False),
        sa.Column("document_hash", sa.String(64), nullable=False, index=True),
        sa.Column("uploader_id", sa.String(64), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "onboardings",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("client_legal_name", sa.String(256), nullable=False),
        sa.Column("registration_id", sa.String(128), nullable=False),
        sa.Column("primary_contact_name", sa.String(128), nullable=False),
        sa.Column("primary_contact_email", sa.String(256), nullable=False),
        sa.Column("signed_contract_ref", sa.String(512), nullable=False),
        sa.Column("kyc_status", sa.String(32), nullable=False),
        sa.Column("kyb_status", sa.String(32), nullable=False),
        sa.Column("project_plan_ref", sa.String(512), nullable=False, server_default=""),
        sa.Column("kickoff_meeting_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("plan_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in ("onboardings", "contracts", "financial_reports"):
        op.drop_table(table)
