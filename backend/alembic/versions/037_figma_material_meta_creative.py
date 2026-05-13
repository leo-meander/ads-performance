"""Wire Figma renders into the Meta launch pipeline.

Revision ID: 037_figma_material_meta_creative
Revises: 036_figma_templates_and_jobs
Create Date: 2026-05-13

Adds the columns the launch flow needs to publish a combo to Meta when the
creative lives in Figma instead of (or in addition to) a Drive URL:

  ad_accounts:
    - meta_page_id              The Facebook Page the ad is published from.
                                Required by Meta when creating an AdCreative
                                with link_data. Stored per-branch.
    - default_destination_url   Fallback landing URL used by AdCreative
                                link_data.link when the combo has no
                                explicit destination. Branch homepage.

  ad_materials:
    - figma_file_key            Figma file the master frame lives in.
    - figma_node_id             Frame/component node id. When both this and
                                figma_file_key are set, the builder renders
                                a PNG via /v1/images instead of reading
                                file_url (which is the Drive fallback).
    - meta_image_hash           Cached hash returned by Meta /adimages after
                                the first upload of this rendered PNG. Lets
                                us skip render+upload on subsequent launches
                                of the same material.

Idempotent: ADD COLUMN IF NOT EXISTS (PG) / batch_alter_table (SQLite).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "037_figma_material_meta_creative"
down_revision: Union[str, None] = "036_figma_templates_and_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("ALTER TABLE ad_accounts ADD COLUMN IF NOT EXISTS meta_page_id VARCHAR(50);")
        op.execute("ALTER TABLE ad_accounts ADD COLUMN IF NOT EXISTS default_destination_url TEXT;")
        op.execute("ALTER TABLE ad_materials ADD COLUMN IF NOT EXISTS figma_file_key VARCHAR(80);")
        op.execute("ALTER TABLE ad_materials ADD COLUMN IF NOT EXISTS figma_node_id VARCHAR(80);")
        op.execute("ALTER TABLE ad_materials ADD COLUMN IF NOT EXISTS meta_image_hash VARCHAR(128);")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_ad_materials_figma_node "
            "ON ad_materials (figma_file_key, figma_node_id) "
            "WHERE figma_file_key IS NOT NULL;"
        )
    else:
        with op.batch_alter_table("ad_accounts") as batch:
            batch.add_column(sa.Column("meta_page_id", sa.String(50), nullable=True))
            batch.add_column(sa.Column("default_destination_url", sa.Text(), nullable=True))
        with op.batch_alter_table("ad_materials") as batch:
            batch.add_column(sa.Column("figma_file_key", sa.String(80), nullable=True))
            batch.add_column(sa.Column("figma_node_id", sa.String(80), nullable=True))
            batch.add_column(sa.Column("meta_image_hash", sa.String(128), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("DROP INDEX IF EXISTS ix_ad_materials_figma_node;")
        op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS meta_image_hash;")
        op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS figma_node_id;")
        op.execute("ALTER TABLE ad_materials DROP COLUMN IF EXISTS figma_file_key;")
        op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS default_destination_url;")
        op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS meta_page_id;")
    else:
        with op.batch_alter_table("ad_materials") as batch:
            batch.drop_column("meta_image_hash")
            batch.drop_column("figma_node_id")
            batch.drop_column("figma_file_key")
        with op.batch_alter_table("ad_accounts") as batch:
            batch.drop_column("default_destination_url")
            batch.drop_column("meta_page_id")
