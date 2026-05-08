"""add phase 1 agent tables: expenses, card_transactions, workflow_instances, rosters, staff_members, bookings

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "expenses",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("submitter_id", sa.String(64), nullable=False, index=True),
        sa.Column("merchant", sa.String(256), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("category", sa.String(128), nullable=False),
        sa.Column("policy_status", sa.String(32), nullable=False),
        sa.Column("reconciliation_status", sa.String(32), nullable=False),
        sa.Column("matched_card_txn_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("image_hash", sa.String(64), nullable=False, index=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "card_transactions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("merchant", sa.String(256), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("matched_expense_id", sa.String(64), nullable=True),
    )
    op.create_table(
        "workflow_instances",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("workflow_template_id", sa.String(64), nullable=False),
        sa.Column("subject_type", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.String(64), nullable=False),
        sa.Column("current_step", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("documents", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("communications", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "rosters",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open_gap_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shifts_json", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_table(
        "staff_members",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("skills_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("venue_id", sa.String(64), nullable=True),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "bookings",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("venue_id", sa.String(64), nullable=False, index=True),
        sa.Column("booking_type", sa.String(32), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("notifications_dispatched", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    for table in (
        "bookings",
        "staff_members",
        "rosters",
        "workflow_instances",
        "card_transactions",
        "expenses",
    ):
        op.drop_table(table)
