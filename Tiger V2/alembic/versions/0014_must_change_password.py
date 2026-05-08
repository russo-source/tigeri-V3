"""Add users.must_change_password flag.

Set on every admin-initiated rotation (seed_admin.py / admin user-management
"reset password"). While the flag is true, the sign-in response surfaces it
and the API rejects every authed call except POST /auth/change-password.
After the user picks a new password the flag clears.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
