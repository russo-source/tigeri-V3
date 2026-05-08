"""Bring-Your-Own-App: per-tenant OAuth client credentials.

Adds the ``tenant_integration_credentials`` table so each tenant can register
their own client_id / client_secret per provider. The connect/callback flow
prefers the tenant row over the platform-default env credentials (see
``tigeri.integrations.tenant_creds.resolve``).

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_integration_credentials",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("client_id", sa.String(512), nullable=False),
        sa.Column("client_secret_enc", sa.String(2048), nullable=False),
        sa.Column("custom_redirect_uri", sa.String(512), nullable=True),
        sa.Column("custom_scopes", sa.JSON(), nullable=True),
        sa.Column(
            "extra_meta", sa.JSON(), nullable=False, server_default="{}"
        ),
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
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_tic_tenant"
        ),
        sa.UniqueConstraint(
            "tenant_id", "provider", name="uq_tenant_integration_credentials"
        ),
    )


def downgrade() -> None:
    op.drop_table("tenant_integration_credentials")
