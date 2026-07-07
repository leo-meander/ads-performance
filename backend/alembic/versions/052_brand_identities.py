"""brand_identities table for Brand Intelligence module

Revision ID: 052_brand_identities
Revises: 051_approval_comments
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa

revision = "052_brand_identities"
down_revision = "051_approval_comments"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "brand_identities",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("branch_name", sa.String(100), nullable=False, unique=True),
        sa.Column("human_desires", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("brand_territory", sa.String(200), nullable=True),
        sa.Column("brand_promise", sa.Text(), nullable=True),
        sa.Column("emotional_themes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("never_say", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("always_say", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("feeling_target", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), onupdate=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brand_identities_branch_name", "brand_identities", ["branch_name"])

    # Seed data for 5 hotel brands
    op.execute("""
        INSERT INTO brand_identities
            (branch_name, human_desires, brand_territory, brand_promise, emotional_themes, never_say, always_say, feeling_target)
        VALUES
        (
            'Meander Taipei',
            '["Belonging", "Connection", "Friendship"]',
            'Human Connection',
            'Leave with friends, not just memories.',
            '["Shared Moment", "Community", "Adventure", "First Friend", "Late Night Talk"]',
            '["Cheap", "Budget", "Best Location", "Affordable", "Value"]',
            '["People", "Connection", "Stories", "Together", "Community"]',
            'After seeing this ad, the viewer should feel: there are people waiting to be part of my trip.'
        ),
        (
            'Oani',
            '["Recovery", "Calm", "Stillness"]',
            'Urban Retreat',
            'Your nervous system deserves a holiday too.',
            '["Slow Morning", "Breathing", "Urban Oasis", "Tiny Rituals", "Stillness"]',
            '["Luxury", "Premium", "Exclusive", "Five-star", "Party"]',
            '["Calm", "Breathe", "Still", "Slow", "Restore", "Oasis"]',
            'After seeing this ad, the viewer should feel: I need to slow down, and this place lets me.'
        ),
        (
            'Meander Osaka',
            '["Fulfillment", "Achievement", "Adventure"]',
            'Journey Companion',
            'The Japan trip you''ve always imagined.',
            '["Dream Trip", "Home Base", "Exploration", "Discovery", "Return"]',
            '["Cheap", "Budget", "Deal", "Discount", "Hostel"]',
            '["Journey", "Explore", "Japan", "Experience", "Home", "Return"]',
            'After seeing this ad, the viewer should feel: this is finally the Japan trip I''ve dreamed about.'
        ),
        (
            'Meander Saigon',
            '["Immersion", "Freedom", "Belonging"]',
            'Live Like a Local',
            'I didn''t visit Saigon. I lived there.',
            '["Local Life", "City Rhythm", "Neighborhood", "Authentic", "Everyday Saigon"]',
            '["Tourist", "Sightseeing", "Tour", "Visit", "Attraction"]',
            '["Live", "Local", "Real", "Neighborhood", "City", "Rhythm"]',
            'After seeing this ad, the viewer should feel: I can actually live in Saigon, not just visit it.'
        ),
        (
            'Meander 1948',
            '["Curiosity", "Discovery", "Wonder"]',
            'Heritage Discovery',
            'Every layer of this building has a story.',
            '["Hidden Story", "Slow Walk", "Architecture", "Layers", "Finding"]',
            '["Luxury", "Shopping", "Modern", "Convenience", "Shopping"]',
            '["Story", "Building", "History", "Discover", "Layer", "Find"]',
            'After seeing this ad, the viewer should feel: curious — like there''s something here I haven''t seen before.'
        )
    """)


def downgrade():
    op.drop_index("ix_brand_identities_branch_name", table_name="brand_identities")
    op.drop_table("brand_identities")
