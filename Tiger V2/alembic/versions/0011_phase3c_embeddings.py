"""Phase 3c — vector extension + embeddings table.

pgvector is preferred for ANN search; we fall back to a JSONB embedding
column when the extension isn't available on the running Postgres (e.g.
the stock postgres:16-alpine Docker image used in dev). The migration
detects availability via pg_available_extensions BEFORE attempting
CREATE EXTENSION, so no transaction-poisoning error is raised.

To enable pgvector later:
  1. Switch the docker-compose postgres service to ``pgvector/pgvector:pg16``,
     OR install ``pgvector`` server-side (yum/apt) and restart Postgres.
  2. Run ``CREATE EXTENSION vector;`` and
     ``ALTER TABLE embeddings ALTER COLUMN embedding TYPE vector(1024)
       USING embedding::text::vector;`` (only safe if rows already conform).

Embedding dim 1024 matches Voyage AI's default models (voyage-3,
voyage-multilingual-2). Switch to 1536 for OpenAI ada-002 or 768 for
sentence-transformers MiniLM.

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def _pgvector_available(conn) -> bool:  # noqa: ANN001
    """Returns True when pg_available_extensions lists 'vector'.

    Probing this before CREATE EXTENSION avoids the FeatureNotSupportedError
    that poisons the migration's outer transaction.
    """
    row = conn.execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector' LIMIT 1")
    ).first()
    return row is not None


def upgrade() -> None:
    if not _is_postgres():
        # SQLite test path: plain JSON column.
        op.create_table(
            "embeddings",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
            sa.Column("source_type", sa.String(32), nullable=False),
            sa.Column("source_id", sa.String(64), nullable=False),
            sa.Column("embedding", sa.JSON(), nullable=False),
            sa.Column(
                "meta_json", sa.JSON(), nullable=False, server_default="{}"
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        return

    conn = op.get_bind()
    has_pgvector = _pgvector_available(conn)

    if has_pgvector:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute(
            "CREATE TABLE IF NOT EXISTS embeddings ("
            "  id            VARCHAR(64) PRIMARY KEY,"
            "  tenant_id     VARCHAR(64) NOT NULL REFERENCES tenants(id),"
            "  source_type   VARCHAR(32) NOT NULL,"
            "  source_id     VARCHAR(64) NOT NULL,"
            "  embedding     vector(1024) NOT NULL,"
            "  meta_json     JSONB NOT NULL DEFAULT '{}',"
            "  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            ")"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS embeddings_tenant_source_idx "
            "ON embeddings(tenant_id, source_type, source_id)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS embeddings_vector_idx "
            "ON embeddings USING ivfflat (embedding vector_cosine_ops) "
            "WITH (lists = 100)"
        )
    else:
        # Pgvector not installed — create the table with JSONB embedding so
        # the application can still write/read embeddings (slower KNN, but
        # functional for pilot until pgvector is enabled).
        op.execute(
            "CREATE TABLE IF NOT EXISTS embeddings ("
            "  id            VARCHAR(64) PRIMARY KEY,"
            "  tenant_id     VARCHAR(64) NOT NULL REFERENCES tenants(id),"
            "  source_type   VARCHAR(32) NOT NULL,"
            "  source_id     VARCHAR(64) NOT NULL,"
            "  embedding     JSONB NOT NULL,"
            "  meta_json     JSONB NOT NULL DEFAULT '{}',"
            "  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            ")"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS embeddings_tenant_source_idx "
            "ON embeddings(tenant_id, source_type, source_id)"
        )


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP INDEX IF EXISTS embeddings_vector_idx")
        op.execute("DROP INDEX IF EXISTS embeddings_tenant_source_idx")
        op.execute("DROP TABLE IF EXISTS embeddings")
        # Leave the vector extension installed if it was — other code may rely on it.
    else:
        op.drop_table("embeddings")
