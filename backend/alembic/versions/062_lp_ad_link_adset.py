"""landing_page_ad_links: add ad_set_id for Google Search ad-group-level attribution

Revision ID: 062_lp_ad_link_adset
Revises: 061_hypothesis_combo_links
Create Date: 2026-07-15

Problem: Google Search campaigns often have 2 ad groups:
  - non-brand keywords → links to a landing page
  - brand keywords    → links directly to booking engine

Before this migration, landing_page_ad_links stored only campaign_id for these
campaigns. Metrics rollup joined at campaign-level, which double-counted spend
from the brand keyword ad group.

Fix: store ad_set_id on the link so the rollup can join at ad_set level
(metrics_cache WHERE ad_set_id = X AND ad_id IS NULL) to get only the spend
from the relevant ad group.

Also cleans up stale Google Search ad links that have ad_id set (Google does
not store ad-level metrics_cache rows, so those links attributed zero spend).
After deploying, re-run /api/internal/tasks/import-landing-pages to regenerate
Google Search links with ad_set_id set correctly.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "062_lp_ad_link_adset"
down_revision: Union[str, None] = "061_hypothesis_combo_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "landing_page_ad_links",
        sa.Column(
            "ad_set_id",
            sa.String(36),
            sa.ForeignKey("ad_sets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_lp_ad_links_ad_set",
        "landing_page_ad_links",
        ["ad_set_id"],
    )

    # Remove stale Google Search ad links that stored ad_id (Google has no
    # ad-level metrics_cache rows, so these contributed zero spend and blocked
    # campaign-level fallback). The importer will recreate them with ad_set_id.
    op.execute("""
        DELETE FROM landing_page_ad_links
        WHERE platform = 'google'
          AND ad_id IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_index("idx_lp_ad_links_ad_set", table_name="landing_page_ad_links")
    op.drop_column("landing_page_ad_links", "ad_set_id")
