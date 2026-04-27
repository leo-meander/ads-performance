"""Add country column to campaigns (Google country derived from campaign name).

Revision ID: 024_campaigns_country
Revises: 023_user_must_change_password
Create Date: 2026-04-27

For Google campaigns the country code lives in the trailing 2 chars of the
campaign name (convention `..._VN`, `..._TW`). Storing it on the campaign row
lets the country dashboard render PMax (which has no AdSet) and avoids
re-parsing at query time. Meta keeps using AdSet.country.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "024_campaigns_country"
down_revision: Union[str, None] = "023_user_must_change_password"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        op.execute("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS country VARCHAR(8)")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_campaigns_country ON campaigns (country)"
        )
    else:
        with op.batch_alter_table("campaigns") as batch:
            batch.add_column(sa.Column("country", sa.String(length=8), nullable=True))
            batch.create_index("ix_campaigns_country", ["country"])


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        op.execute("DROP INDEX IF EXISTS ix_campaigns_country")
        op.execute("ALTER TABLE campaigns DROP COLUMN IF EXISTS country")
    else:
        with op.batch_alter_table("campaigns") as batch:
            batch.drop_index("ix_campaigns_country")
            batch.drop_column("country")
