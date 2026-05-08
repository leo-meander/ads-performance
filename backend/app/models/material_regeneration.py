from sqlalchemy import Column, DateTime, ForeignKey, String, Text

from app.models.base import Base, JSONType, TimestampMixin, UUIDType


class MaterialRegeneration(TimestampMixin, Base):
    """One row per regenerate request from a winning ad.

    Workflow:
      PENDING   -> request received, queued
      RUNNING   -> Canva clone+edit in progress
      COMPLETED -> output_canva_url + output_design_id populated
      FAILED    -> error populated
    """
    __tablename__ = "material_regenerations"

    source_material_id = Column(
        String(10),
        ForeignKey("ad_materials.material_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_combo_id = Column(
        String(10),
        ForeignKey("ad_combos.combo_id", ondelete="SET NULL"),
        nullable=True,
    )
    comment = Column(Text, nullable=False)  # the user's idea / instructions
    overrides = Column(JSONType, nullable=True)  # {placeholder_name: value}
    status = Column(String(20), nullable=False, default="PENDING", index=True)
    output_canva_url = Column(Text, nullable=True)
    output_design_id = Column(String(50), nullable=True)
    output_material_id = Column(
        String(10),
        ForeignKey("ad_materials.material_id", ondelete="SET NULL"),
        nullable=True,
    )
    error = Column(Text, nullable=True)
    requested_by = Column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    requested_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
