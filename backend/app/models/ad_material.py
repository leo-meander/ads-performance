from sqlalchemy import Column, DateTime, ForeignKey, String, Text

from app.models.base import Base, TimestampMixin, UUIDType


class AdMaterial(TimestampMixin, Base):
    __tablename__ = "ad_materials"

    branch_id = Column(UUIDType, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    material_id = Column(String(10), nullable=False, unique=True, index=True)  # MAT-001
    material_type = Column(String(20), nullable=False, index=True)  # image | video | carousel
    file_url = Column(Text, nullable=False)  # Drive/URL link — never uploaded to platform
    description = Column(Text, nullable=True)
    target_audience = Column(String(30), nullable=True, index=True)  # Solo | Couple | Family | Group
    derived_verdict = Column(String(10), nullable=True)  # WIN | TEST | LOSE — READ-ONLY from combos
    url_source = Column(String(10), nullable=False, default="auto", index=True)
    # url_source: 'auto' = synced from Meta (overwritable by sync task)
    #             'manual' = designer-input URL (sync task MUST skip)

    # Creative Intelligence Phase 1 — vision tagging.
    # NULL until the cron tagger scores this material. Re-runs after a model
    # upgrade are gated by comparing vision_model with the current SONNET_VISION
    # constant; mismatches trigger a re-tag.
    vision_analyzed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    vision_model = Column(String(40), nullable=True)

    # Creative Intelligence Phase 2 — embedding bookkeeping (see ad_combo.py).
    embedded_at = Column(DateTime(timezone=True), nullable=True, index=True)
    embedding_model = Column(String(40), nullable=True)

    # Figma source for the launch pipeline. When both are set, the meta
    # creative builder renders the frame via /v1/images instead of falling
    # back to file_url (Drive). file_url stays the canonical link the
    # designer maintains; this just lets us re-render on demand without
    # human intervention.
    figma_file_key = Column(String(80), nullable=True)
    figma_node_id = Column(String(80), nullable=True)

    # Meta /act_xxx/adimages returns a hash after the first upload of a
    # rendered PNG. We cache it here so subsequent launches of the same
    # material skip the render+upload roundtrip. Designers can null it out
    # via a future "force re-render" action when the underlying frame
    # changes.
    meta_image_hash = Column(String(128), nullable=True)
