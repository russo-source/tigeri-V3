"""Phase 3b — rename chat_* tables to spec names + message_count trigger.

Atomic table renames in Postgres (DDL transaction). FK constraints and
indexes update automatically. Indexes named with the old prefix keep their
names — they still work; renaming them is cosmetic and we leave that for
later.

Python class names (ChatThread, ChatMessage, ChatFeedback) and column names
(thread_id) are unchanged — only the underlying table identifiers move.
``__tablename__`` is updated in src/tigeri/chat/models.py to match.

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    op.rename_table("chat_threads", "conversations")
    op.rename_table("chat_messages", "messages")
    op.rename_table("chat_feedback", "message_feedback")

    if _is_postgres():
        # Trigger function for message_count maintenance. Reuses the
        # update_updated_at() function from migration 0006 (assumed present).
        op.execute(
            "CREATE OR REPLACE FUNCTION increment_message_count() "
            "RETURNS TRIGGER AS $$ "
            "BEGIN "
            "  UPDATE conversations SET message_count = message_count + 1, "
            "    last_active_at = NOW() WHERE id = NEW.thread_id; "
            "  RETURN NEW; "
            "END; $$ LANGUAGE plpgsql"
        )
        op.execute("DROP TRIGGER IF EXISTS messages_count ON messages")
        op.execute(
            "CREATE TRIGGER messages_count AFTER INSERT ON messages "
            "FOR EACH ROW EXECUTE FUNCTION increment_message_count()"
        )

        # updated_at trigger on conversations (uses the function from 0006).
        op.execute("DROP TRIGGER IF EXISTS conversations_updated_at ON conversations")
        op.execute(
            "CREATE TRIGGER conversations_updated_at BEFORE UPDATE ON conversations "
            "FOR EACH ROW EXECUTE FUNCTION update_updated_at()"
        )


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP TRIGGER IF EXISTS conversations_updated_at ON conversations")
        op.execute("DROP TRIGGER IF EXISTS messages_count ON messages")
        op.execute("DROP FUNCTION IF EXISTS increment_message_count()")

    op.rename_table("message_feedback", "chat_feedback")
    op.rename_table("messages", "chat_messages")
    op.rename_table("conversations", "chat_threads")
