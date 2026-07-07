from sqlalchemy import Column, ForeignKey, String, Text

from app.models.base import Base, JSONType, TimestampMixin, UUIDType

HUMAN_DESIRES = [
    "Belonging", "Discovery", "Recovery", "Fulfillment", "Immersion",
    "Romance", "Freedom", "Calm", "Adventure", "Status",
    "Achievement", "Escape", "Curiosity", "Play", "Growth",
    "Security", "Nostalgia",
]

STORY_STRUCTURES = [
    "Curiosity Loop", "Slice of Life", "Hero Journey",
    "Before vs After", "Open Loop", "3 Act", "Conversation", "Voice Over",
]

VISUAL_PATTERN_OPTIONS = [
    "POV", "Interview", "Mini Documentary", "UGC",
    "Found Footage", "Vlog", "Static Camera", "Drone", "Timelapse",
]


class AdAngle(TimestampMixin, Base):
    __tablename__ = "ad_angles"

    branch_id = Column(UUIDType, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=True, index=True)
    angle_id = Column(String(20), nullable=False, unique=True, index=True)
    angle_type = Column(String(100), nullable=True, index=True)  # Creative Angle name
    angle_explain = Column(Text, nullable=True)
    hook_examples = Column(JSONType, nullable=True)
    # New framework columns
    human_desire = Column(String(100), nullable=True, index=True)
    emotional_theme = Column(String(200), nullable=True, index=True)
    applicable_to = Column(JSONType, nullable=True)  # ["Meander Taipei"] or null = universal
    story_structure = Column(String(50), nullable=True)
    visual_patterns = Column(JSONType, nullable=True)
    # Legacy
    target_audience = Column(String(30), nullable=True, index=True)
    angle_text = Column(Text, nullable=False, default="")
    hook = Column(String(60), nullable=True)
    status = Column(String(10), nullable=False, default="TEST", index=True)  # WIN | TEST | LOSE
    notes = Column(Text, nullable=True)
    created_by = Column(String(100), nullable=True)
