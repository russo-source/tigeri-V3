"""Audit-driven security + integrity hardening.

Adds:
  - oauth_states — CSRF nonce table for the connect/callback flow.
  - telegram_link_codes — single-use codes for /connect <code>, replacing the
    old hijack-prone /connect <tenant_id>.
  - CHECK (end_at > start_at) on bookings, CHECK (period_end > period_start)
    on rosters — prevents poisoned scheduling rows.

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---------- oauth_states ----------
    op.create_table(
        "oauth_states",
        sa.Column("nonce", sa.String(128), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("oauth_states_expires_at_idx", "oauth_states", ["expires_at"])

    # ---------- telegram_link_codes ----------
    op.create_table(
        "telegram_link_codes",
        sa.Column("code", sa.String(16), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "telegram_link_codes_expires_at_idx", "telegram_link_codes", ["expires_at"]
    )

    # ---------- DB-level integrity constraints ----------
    # Audit findings: alembic 0002 didn't enforce that booking/roster windows
    # have end > start, which lets nonsense rows through and poisons the
    # conflict-detection logic.
    if op.get_context().dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE bookings ADD CONSTRAINT ck_bookings_window "
            "CHECK (end_at > start_at) NOT VALID"
        )
        # NOT VALID lets us add the constraint to existing tables without
        # scanning historical rows; new INSERTs/UPDATEs are checked.
        # Validate so future migrations can rely on it being clean (skip if
        # any rotten rows exist; admin can VALIDATE manually).
        try:
            op.execute("ALTER TABLE bookings VALIDATE CONSTRAINT ck_bookings_window")
        except Exception:  # noqa: BLE001
            pass

        op.execute(
            "ALTER TABLE rosters ADD CONSTRAINT ck_rosters_window "
            "CHECK (period_end > period_start) NOT VALID"
        )
        try:
            op.execute("ALTER TABLE rosters VALIDATE CONSTRAINT ck_rosters_window")
        except Exception:  # noqa: BLE001
            pass


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.execute("ALTER TABLE rosters DROP CONSTRAINT IF EXISTS ck_rosters_window")
        op.execute("ALTER TABLE bookings DROP CONSTRAINT IF EXISTS ck_bookings_window")

    op.drop_index(
        "telegram_link_codes_expires_at_idx", table_name="telegram_link_codes"
    )
    op.drop_table("telegram_link_codes")
    op.drop_index("oauth_states_expires_at_idx", table_name="oauth_states")
    op.drop_table("oauth_states")
