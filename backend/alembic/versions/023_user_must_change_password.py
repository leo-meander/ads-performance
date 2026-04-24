"""Add must_change_password flag to users for admin-triggered password resets

Revision ID: 023_user_must_change_password
Revises: 022_change_log_entries
Create Date: 2026-04-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "023_user_must_change_password"
down_revision: Union[str, None] = "022_change_log_entries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("SET LOCAL statement_timeout = 0")
        op.execute(
            """
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;
            """
        )
    else:
        # SQLite test path — use batch_alter_table
        with op.batch_alter_table("users") as batch:
            batch.add_column(
                sa.Column(
                    "must_change_password",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS must_change_password;")
