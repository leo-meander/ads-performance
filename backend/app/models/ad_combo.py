from sqlalchemy import Column, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint

from app.models.base import Base, JSONType, TimestampMixin, UUIDType


class AdCombo(TimestampMixin, Base):
    __tablename__ = "ad_combos"
    __table_args__ = (
        UniqueConstraint("copy_id", "material_id", name="uq_combo_copy_material"),
    )

    branch_id = Column(UUIDType, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    combo_id = Column(String(10), nullable=False, unique=True, index=True)  # CMB-001
    ad_name = Column(String(500), nullable=True, index=True)  # Meta Ad Name — the real identity
    target_audience = Column(String(30), nullable=True, index=True)  # Solo | Couple | Family | Group
    country = Column(String(10), nullable=True, index=True)  # PH, AU, JP, US, HK, etc.
    keypoint_ids = Column(JSONType, nullable=True)  # Array of keypoint UUIDs — multiple keypoints per combo
    angle_id = Column(String(10), ForeignKey("ad_angles.angle_id", ondelete="SET NULL"), nullable=True, index=True)
    copy_id = Column(String(10), ForeignKey("ad_copies.copy_id", ondelete="CASCADE"), nullable=False, index=True)
    material_id = Column(String(10), ForeignKey("ad_materials.material_id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id = Column(UUIDType, ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True)

    # Verdict
    verdict = Column(String(10), nullable=False, default="TEST", index=True)  # WIN | TEST | LOSE
    verdict_source = Column(String(10), nullable=False, default="manual")  # manual | auto
    verdict_notes = Column(Text, nullable=True)

    # Cached performance metrics
    spend = Column(Numeric(15, 2), nullable=True)
    impressions = Column(Integer, nullable=True)
    clicks = Column(Integer, nullable=True)
    conversions = Column(Integer, nullable=True)  # purchases/bookings
    revenue = Column(Numeric(15, 2), nullable=True)
    roas = Column(Numeric(8, 4), nullable=True)
    cost_per_purchase = Column(Numeric(15, 2), nullable=True)
    ctr = Column(Numeric(8, 6), nullable=True)
    engagement = Column(Integer, nullable=True)  # inline_post_engagement
    engagement_rate = Column(Numeric(8, 6), nullable=True)  # engagement / impressions
    # Video-specific
    video_plays = Column(Integer, nullable=True)
    thruplay = Column(Integer, nullable=True)  # video_thruplay_watched_actions
    video_p100 = Column(Integer, nullable=True)  # watched 100%
    hook_rate = Column(Numeric(8, 6), nullable=True)  # video_play / impressions (3s view rate)
    thruplay_rate = Column(Numeric(8, 6), nullable=True)  # thruplay / video_plays
    video_complete_rate = Column(Numeric(8, 6), nullable=True)  # p100 / video_plays
