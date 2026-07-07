"""extend ad_angles with Creative Intelligence framework columns

Revision ID: 053_angles_new_framework
Revises: 052_brand_identities
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa

revision = "053_angles_new_framework"
down_revision = "052_brand_identities"
branch_labels = None
depends_on = None


def upgrade():
    # human_desire: which emotional territory this angle belongs to
    op.add_column("ad_angles", sa.Column("human_desire", sa.String(100), nullable=True))
    # emotional_theme: middle layer (e.g. "Shared Meal", "Community Ritual")
    op.add_column("ad_angles", sa.Column("emotional_theme", sa.String(200), nullable=True))
    # applicable_to: ["Taipei", "Saigon"] or null = universal
    op.add_column("ad_angles", sa.Column("applicable_to", sa.JSON(), nullable=True))
    # story_structure: recommended narrative structure for this angle
    op.add_column("ad_angles", sa.Column("story_structure", sa.String(50), nullable=True))
    # visual_patterns: recommended visual formats ["POV", "Interview", "UGC"]
    op.add_column("ad_angles", sa.Column("visual_patterns", sa.JSON(), nullable=True))

    op.create_index("ix_ad_angles_human_desire", "ad_angles", ["human_desire"])
    op.create_index("ix_ad_angles_emotional_theme", "ad_angles", ["emotional_theme"])

    # Seed initial Creative Angles for each brand territory
    # These replace the old copywriting-framework angles and represent
    # territory-specific creative angles per the new framework.
    op.execute("""
        INSERT INTO ad_angles
            (angle_id, angle_type, angle_explain, human_desire, emotional_theme,
             applicable_to, story_structure, visual_patterns, hook_examples, status)
        VALUES
        -- Belonging angles (Meander Taipei focus)
        ('ANG-T01', 'Strangers Become Friends',
         'Show the moment two strangers connect — breakfast table, common area, spontaneous conversation. The hostel is the catalyst, not the subject.',
         'Belonging', 'First Friend',
         '["Meander Taipei", "Meander Saigon"]',
         'Curiosity Loop',
         '["POV", "Slice of Life", "UGC"]',
         '["The person sitting next to you at breakfast wasn''t in your plan.", "Nobody arrives as a stranger here.", "Your travel story starts before you leave the hostel."]',
         'TEST'),

        ('ANG-T02', 'Community Ritual',
         'Capture a recurring ritual that only happens here — game night, communal cooking, rooftop hangout. Rituals signal belonging.',
         'Belonging', 'Community Ritual',
         '["Meander Taipei"]',
         'Slice of Life',
         '["Static Camera", "Mini Documentary", "UGC"]',
         '["Every Tuesday. Same table. Different strangers.", "This wasn''t on TripAdvisor.", "The ritual nobody tells you about."]',
         'TEST'),

        ('ANG-T03', 'Found Family',
         'The feeling of traveling alone but never being lonely. Show a group that formed organically during a stay.',
         'Belonging', 'Found Family',
         '["Meander Taipei", "Meander Saigon"]',
         'Hero Journey',
         '["Mini Documentary", "Interview", "Vlog"]',
         '["I came alone. I didn''t leave that way.", "We met on Monday. By Friday we were planning the next trip.", "Solo travel doesn''t mean traveling alone."]',
         'TEST'),

        -- Recovery angles (Oani focus)
        ('ANG-O01', 'Slow Morning',
         'A single slow morning — light through the window, coffee, no plans. The antidote to the overscheduled trip.',
         'Recovery', 'Slow Morning',
         '["Oani"]',
         'Slice of Life',
         '["Static Camera", "Timelapse", "POV"]',
         '["Your nervous system deserves a holiday too.", "Not every morning needs a plan.", "This is what rest actually looks like."]',
         'TEST'),

        ('ANG-O02', 'Urban Oasis',
         'Contrast city noise with the quiet inside. The city is still there — but here, you can''t hear it.',
         'Recovery', 'Urban Oasis',
         '["Oani"]',
         'Before vs After',
         '["Drone", "Static Camera", "POV"]',
         '["Taipei outside. Silence inside.", "The city doesn''t have to follow you in.", "An oasis doesn''t need to be far away."]',
         'TEST'),

        ('ANG-O03', 'Tiny Ritual',
         'Small, intentional moments — a scent, a shadow, a specific chair. The details that signal this place cares about how you feel.',
         'Recovery', 'Tiny Rituals',
         '["Oani"]',
         'Curiosity Loop',
         '["Static Camera", "Macro", "POV"]',
         '["You''ll notice things here you never notice anywhere else.", "The chair by the window. Always empty. Always yours.", "Recovery isn''t a destination. It''s a feeling."]',
         'TEST'),

        -- Discovery angles (Meander 1948 focus)
        ('ANG-101', 'Hidden Story',
         'Every corner of the building holds something unexpected. Invite the viewer to find it themselves.',
         'Curiosity', 'Hidden Story',
         '["Meander 1948"]',
         'Curiosity Loop',
         '["POV", "Mini Documentary", "Found Footage"]',
         '["Nobody told us about the third floor.", "This building is older than your grandparents. Ask it something.", "Taipei hides its best stories in plain sight."]',
         'TEST'),

        ('ANG-102', 'Walk Slowly',
         'This neighborhood rewards slow walkers. Show what you find when you stop rushing.',
         'Curiosity', 'Slow Walk',
         '["Meander 1948"]',
         'Slice of Life',
         '["Vlog", "POV", "Mini Documentary"]',
         '["The tourists missed everything on this street.", "Five minutes from the night market. A different century.", "You have to slow down to see it."]',
         'TEST'),

        -- Fulfillment angles (Meander Osaka focus)
        ('ANG-OS01', 'Dream Trip',
         'The Japan trip they''ve been planning for years. The hotel is the home base that makes everything else possible.',
         'Fulfillment', 'Dream Trip',
         '["Meander Osaka"]',
         'Hero Journey',
         '["Vlog", "Mini Documentary", "Interview"]',
         '["You''ve been saving this trip for three years.", "Every great Japan day deserves somewhere to come home to.", "The trip you imagined. Finally."]',
         'TEST'),

        ('ANG-OS02', 'Coming Home',
         'The moment of return — tired, full of the day, walking back through the door. The hotel as emotional anchor.',
         'Fulfillment', 'Return',
         '["Meander Osaka"]',
         'Slice of Life',
         '["POV", "Static Camera", "Vlog"]',
         '["Kyoto in the morning. Namba at night. This in between.", "The best part of a full day is coming back.", "Not just a bed. A place to land."]',
         'TEST'),

        -- Immersion angles (Meander Saigon focus)
        ('ANG-S01', 'Live Here',
         'Not visiting. Not sightseeing. Actually living in the city for a few days.',
         'Immersion', 'Local Life',
         '["Meander Saigon"]',
         'Slice of Life',
         '["Vlog", "POV", "UGC"]',
         '["I didn''t visit Saigon. I lived there.", "The locals don''t know you''re a tourist here.", "Your morning coffee came from the alley, not the lobby."]',
         'TEST'),

        ('ANG-S02', 'City Rhythm',
         'The energy of Saigon — motorbikes, noise, street food, chaos — but experienced from the inside, not as a spectator.',
         'Immersion', 'City Rhythm',
         '["Meander Saigon"]',
         'Curiosity Loop',
         '["POV", "Mini Documentary", "Found Footage"]',
         '["Saigon has a sound. You''ll know it by day two.", "This isn''t a tour. It''s a neighborhood.", "The city pulls you in if you let it."]',
         'TEST')
    """)


def downgrade():
    op.drop_index("ix_ad_angles_emotional_theme", table_name="ad_angles")
    op.drop_index("ix_ad_angles_human_desire", table_name="ad_angles")
    op.drop_column("ad_angles", "visual_patterns")
    op.drop_column("ad_angles", "story_structure")
    op.drop_column("ad_angles", "applicable_to")
    op.drop_column("ad_angles", "emotional_theme")
    op.drop_column("ad_angles", "human_desire")
