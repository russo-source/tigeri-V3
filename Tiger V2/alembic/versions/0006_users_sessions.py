"""Phase 1 — extend tenants, add users + sessions, add updated_at trigger.

Additive only. Existing rows are preserved:
  - tenants.slug is backfilled from tenants.id (which is already URL-safe).
  - tenants gets region='sg', plan='pilot', status='active', settings='{}',
    updated_at=NOW() server defaults so existing rows fill in automatically.
  - users and sessions are net-new.
  - update_updated_at() pgsql function + triggers on tenants and users —
    Postgres only; SQLite test runs skip them.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    # ---------------------------------------------------------------- tenants
    # Add new columns. `slug` starts nullable so we can backfill, then locked
    # to NOT NULL UNIQUE in a follow-up step.
    op.add_column("tenants", sa.Column("slug", sa.String(128), nullable=True))
    op.add_column(
        "tenants",
        sa.Column("region", sa.String(8), nullable=False, server_default="sg"),
    )
    op.add_column(
        "tenants",
        sa.Column("plan", sa.String(32), nullable=False, server_default="pilot"),
    )
    op.add_column(
        "tenants",
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
    )
    op.add_column(
        "tenants",
        sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Backfill slug = id for every pre-Phase-1 row. id is already URL-safe
    # (tnt_demo, tnt_acme_xyz123). New rows from POST /auth/sign-up will pick
    # a slug from the tenant name via _slugify().
    op.execute("UPDATE tenants SET slug = id WHERE slug IS NULL")
    op.alter_column("tenants", "slug", existing_type=sa.String(128), nullable=False)

    op.create_index("tenants_slug_idx", "tenants", ["slug"], unique=True)
    op.create_index("tenants_status_idx", "tenants", ["status"])

    # ---------------------------------------------------------------- users
    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("email", sa.String(256), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="member"),
        sa.Column("status", sa.String(32), nullable=False, server_default="invited"),
        sa.Column("password_hash", sa.String(256), nullable=True),
        sa.Column(
            "email_verified", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invited_by", sa.String(64), nullable=True),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_users_tenant"),
        sa.ForeignKeyConstraint(
            ["invited_by"], ["users.id"], name="fk_users_invited_by"
        ),
        sa.UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
    )
    op.create_index("users_tenant_status_idx", "users", ["tenant_id", "status"])

    # ---------------------------------------------------------------- sessions
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_sessions_user"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_sessions_tenant"
        ),
    )
    op.create_index("sessions_expires_at_idx", "sessions", ["expires_at"])

    # ---------------------------------------------------------------- triggers
    if _is_postgres():
        # asyncpg can't prepare multi-statement strings, so each DDL command
        # is its own op.execute().
        op.execute(
            "CREATE OR REPLACE FUNCTION update_updated_at() RETURNS TRIGGER "
            "AS $$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$ "
            "LANGUAGE plpgsql"
        )
        op.execute("DROP TRIGGER IF EXISTS tenants_updated_at ON tenants")
        op.execute(
            "CREATE TRIGGER tenants_updated_at BEFORE UPDATE ON tenants "
            "FOR EACH ROW EXECUTE FUNCTION update_updated_at()"
        )
        op.execute("DROP TRIGGER IF EXISTS users_updated_at ON users")
        op.execute(
            "CREATE TRIGGER users_updated_at BEFORE UPDATE ON users "
            "FOR EACH ROW EXECUTE FUNCTION update_updated_at()"
        )


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP TRIGGER IF EXISTS users_updated_at ON users")
        op.execute("DROP TRIGGER IF EXISTS tenants_updated_at ON tenants")
        # update_updated_at() left in place — Phase 2/3 will reuse it.

    op.drop_index("sessions_expires_at_idx", table_name="sessions")
    op.drop_table("sessions")

    op.drop_index("users_tenant_status_idx", table_name="users")
    op.drop_table("users")

    op.drop_index("tenants_status_idx", table_name="tenants")
    op.drop_index("tenants_slug_idx", table_name="tenants")
    op.drop_column("tenants", "updated_at")
    op.drop_column("tenants", "settings")
    op.drop_column("tenants", "status")
    op.drop_column("tenants", "plan")
    op.drop_column("tenants", "region")
    op.drop_column("tenants", "slug")
