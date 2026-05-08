"""Phase 3b — additive columns on chat_messages + chat_threads.

Adds the spec's content/metadata columns *before* the rename in 0010.
All columns are nullable; existing plaintext content stays in `content`,
new writes populate `content_encrypted` (Fernet via TIGERI_SECRET_ENCRYPTION_KEY).
Reads check both — see tigeri.chat.store.

chat_threads gets the conversation-level metadata (title, status, channel,
context_json, message_count, last_active_at) that the spec calls for.
message_count is backfilled from a COUNT(*) on chat_messages so the trigger
in 0010 has a sane starting value.

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---------- chat_messages ----------
    op.add_column("chat_messages", sa.Column("tenant_id", sa.String(64), nullable=True))
    op.add_column("chat_messages", sa.Column("content_encrypted", sa.Text(), nullable=True))
    op.add_column("chat_messages", sa.Column("content_redacted", sa.Text(), nullable=True))
    op.add_column("chat_messages", sa.Column("agent_name", sa.String(64), nullable=True))
    op.add_column("chat_messages", sa.Column("model", sa.String(128), nullable=True))
    op.add_column("chat_messages", sa.Column("prompt_version", sa.String(64), nullable=True))
    op.add_column("chat_messages", sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column("chat_messages", sa.Column("output_tokens", sa.Integer(), nullable=True))
    op.add_column("chat_messages", sa.Column("cost_micro_usd", sa.Integer(), nullable=True))
    op.add_column("chat_messages", sa.Column("latency_ms", sa.Integer(), nullable=True))
    op.add_column(
        "chat_messages",
        sa.Column(
            "grounding_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Backfill tenant_id from the parent thread so existing rows aren't NULL.
    op.execute(
        "UPDATE chat_messages m SET tenant_id = t.tenant_id "
        "FROM chat_threads t WHERE m.thread_id = t.id AND m.tenant_id IS NULL"
    )
    op.create_index(
        "chat_messages_tenant_created_idx",
        "chat_messages",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "chat_messages_tenant_feedback_idx",
        "chat_messages",
        ["tenant_id"],
        postgresql_where="grounding_verified = false",
    )

    # ---------- chat_threads ----------
    op.add_column("chat_threads", sa.Column("title", sa.String(256), nullable=True))
    op.add_column(
        "chat_threads",
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
    )
    op.add_column(
        "chat_threads",
        sa.Column("channel", sa.String(16), nullable=False, server_default="web"),
    )
    op.add_column(
        "chat_threads",
        sa.Column(
            "context_json",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "chat_threads",
        sa.Column(
            "message_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "chat_threads",
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Backfill: align last_active_at with updated_at, and message_count with
    # the actual count of children. Future writes go through the trigger
    # added in 0010.
    op.execute("UPDATE chat_threads SET last_active_at = updated_at")
    op.execute(
        "UPDATE chat_threads t SET message_count = sub.cnt "
        "FROM (SELECT thread_id, COUNT(*) AS cnt FROM chat_messages GROUP BY thread_id) sub "
        "WHERE sub.thread_id = t.id"
    )


def downgrade() -> None:
    op.drop_column("chat_threads", "last_active_at")
    op.drop_column("chat_threads", "message_count")
    op.drop_column("chat_threads", "context_json")
    op.drop_column("chat_threads", "channel")
    op.drop_column("chat_threads", "status")
    op.drop_column("chat_threads", "title")

    op.drop_index("chat_messages_tenant_feedback_idx", table_name="chat_messages")
    op.drop_index("chat_messages_tenant_created_idx", table_name="chat_messages")
    op.drop_column("chat_messages", "grounding_verified")
    op.drop_column("chat_messages", "latency_ms")
    op.drop_column("chat_messages", "cost_micro_usd")
    op.drop_column("chat_messages", "output_tokens")
    op.drop_column("chat_messages", "input_tokens")
    op.drop_column("chat_messages", "prompt_version")
    op.drop_column("chat_messages", "model")
    op.drop_column("chat_messages", "agent_name")
    op.drop_column("chat_messages", "content_redacted")
    op.drop_column("chat_messages", "content_encrypted")
    op.drop_column("chat_messages", "tenant_id")
