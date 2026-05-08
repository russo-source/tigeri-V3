"""Phase 3 — pending_actions + audit_logs (hash-chain).

Net-new tables. The existing `audit_records` table is left untouched — the
old per-action event log used by the audit page is now legacy alongside the
new tamper-evident `audit_logs`.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    # ---------------------------------------------------------- pending_actions
    op.create_table(
        "pending_actions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("conversation_id", sa.String(64), nullable=True),
        sa.Column("capability", sa.String(128), nullable=False),
        sa.Column("parameters_encrypted", sa.Text(), nullable=False),
        sa.Column("diff_snapshot_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("confirmation_token", sa.String(128), nullable=False, unique=True),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="pending"
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False, server_default="web"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_pending_actions_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_pending_actions_user"
        ),
    )
    op.create_index(
        "pending_actions_token_idx",
        "pending_actions",
        ["confirmation_token"],
        unique=True,
    )
    op.create_index(
        "pending_actions_status_expires_idx",
        "pending_actions",
        ["status", "expires_at"],
    )

    if _is_postgres():
        # Idempotency: only successfully-executed actions carry the unique
        # constraint, so multiple pending rows for the same key are allowed
        # but only one can succeed.
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_actions_idempotency "
            "ON pending_actions(tenant_id, idempotency_key) "
            "WHERE status = 'executed'"
        )

    # ---------------------------------------------------------- audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=True),
        sa.Column("conversation_id", sa.String(64), nullable=True),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("capability", sa.String(128), nullable=True),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("parameters_redacted", sa.JSON(), nullable=True),
        sa.Column("parameters_ref", sa.String(512), nullable=True),
        sa.Column("diff_before_ref", sa.String(512), nullable=True),
        sa.Column("diff_after_ref", sa.String(512), nullable=True),
        sa.Column("xero_request_id", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("channel", sa.String(16), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("signed_hash", sa.String(64), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_audit_logs_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_audit_logs_user"
        ),
    )
    op.create_index(
        "audit_logs_tenant_created_idx", "audit_logs", ["tenant_id", "created_at"]
    )
    op.create_index(
        "audit_logs_tenant_event_idx", "audit_logs", ["tenant_id", "event_type"]
    )
    op.create_index(
        "audit_logs_tenant_user_idx", "audit_logs", ["tenant_id", "user_id"]
    )
    if _is_postgres():
        op.execute(
            "CREATE INDEX IF NOT EXISTS audit_logs_xero_request_idx "
            "ON audit_logs(xero_request_id) WHERE xero_request_id IS NOT NULL"
        )


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP INDEX IF EXISTS audit_logs_xero_request_idx")
    op.drop_index("audit_logs_tenant_user_idx", table_name="audit_logs")
    op.drop_index("audit_logs_tenant_event_idx", table_name="audit_logs")
    op.drop_index("audit_logs_tenant_created_idx", table_name="audit_logs")
    op.drop_table("audit_logs")

    if _is_postgres():
        op.execute("DROP INDEX IF EXISTS uq_pending_actions_idempotency")
    op.drop_index(
        "pending_actions_status_expires_idx", table_name="pending_actions"
    )
    op.drop_index("pending_actions_token_idx", table_name="pending_actions")
    op.drop_table("pending_actions")
