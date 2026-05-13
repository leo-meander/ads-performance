from sqlalchemy import Column, ForeignKey, Numeric, String, UniqueConstraint

from app.models.base import Base, TimestampMixin


class CreativeVisualTag(TimestampMixin, Base):
    """One row per (material, tag_category, tag_value).

    Populated by creative_vision_tagger (Claude Sonnet vision over the material's
    thumbnail URL). Multiple values per category are allowed — e.g. a montage
    ad gets `scene_type=room` AND `scene_type=exterior`.

    Tag categories the tagger emits:
      - text_density    : minimal | medium | heavy
      - hook_type       : question | statistic | benefit | story | direct_offer | other
      - cta_visible     : yes | no
      - color_palette   : warm | cool | neutral | high_contrast | pastel | dark | other
      - human_presence  : solo | couple | group | none
      - scene_type      : room | exterior | food | activity | aerial | abstract | mixed
      - emotional_angle : aspirational | calm | urgency | informational | playful | luxe | other
    """
    __tablename__ = "creative_visual_tags"
    __table_args__ = (
        UniqueConstraint(
            "material_id", "tag_category", "tag_value",
            name="uq_creative_visual_tag",
        ),
    )

    material_id = Column(
        String(10),
        ForeignKey("ad_materials.material_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_category = Column(String(40), nullable=False, index=True)
    tag_value = Column(String(80), nullable=False)
    confidence = Column(Numeric(4, 3), nullable=True)  # 0.000-1.000
    model_version = Column(String(40), nullable=True)
