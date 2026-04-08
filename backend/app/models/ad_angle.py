from sqlalchemy import Column, ForeignKey, String, Text

from app.models.base import Base, JSONType, TimestampMixin, UUIDType

# 13 fixed angle types — the strategic approach
ANGLE_TYPES = [
    "Measure the size of the claim",
    "Measure the speed of the claim",
    "Use an authority",
    "Before and After",
    "Compare the claim to its rival",
    "Remove limitations from the claim",
    "State the claim as a question",
    "Offer Information Directly in the claim",
    "Stress the newness of the claim",
    "Stress the exclusiveness of the claim",
    "Challenge your prospect's beliefs",
    "Call out a solution or product they're currently using",
    "Call out the person directly",
]


class AdAngle(TimestampMixin, Base):
    __tablename__ = "ad_angles"

    branch_id = Column(UUIDType, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=True, index=True)
    angle_id = Column(String(10), nullable=False, unique=True, index=True)  # ANG-001
    angle_type = Column(String(60), nullable=True, index=True)  # One of 13 fixed types
    angle_explain = Column(Text, nullable=True)  # Strategic explanation — WHY this approach works
    hook_examples = Column(JSONType, nullable=True)  # Array of hook lines — specific scroll-stoppers
    target_audience = Column(String(30), nullable=True, index=True)  # Legacy — kept for SQLite compatibility
    # Legacy columns kept for SQLite compatibility (NOT NULL constraint)
    angle_text = Column(Text, nullable=False, default="")
    hook = Column(String(60), nullable=True)
    status = Column(String(10), nullable=False, default="TEST", index=True)  # WIN | TEST | LOSE
    notes = Column(Text, nullable=True)
    created_by = Column(String(100), nullable=True)
