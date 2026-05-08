from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text

from app.models.base import Base, JSONType, TimestampMixin, UUIDType


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

    # Canva link captured the moment a combo using this material is APPROVED.
    # Source: combo_approvals.working_file_url. Persists across approval rounds
    # so winning ads can be cloned later without re-asking the designer.
    canva_url = Column(Text, nullable=True)
    canva_design_id = Column(String(50), nullable=True, index=True)
    canva_captured_at = Column(DateTime(timezone=True), nullable=True)
    canva_source_approval_id = Column(UUIDType, nullable=True)

    # Phase 2 — reusable template metadata. Designer wires named placeholders
    # (e.g. {"headline": "...", "bg_image": "...", "cta": "..."}) on a Canva
    # brand template; once is_template_ready=True, /regenerate can clone it
    # and apply per-comment overrides via the Canva Connect API.
    canva_template_id = Column(String(50), nullable=True)
    canva_placeholder_schema = Column(JSONType, nullable=True)
    is_template_ready = Column(Boolean, nullable=False, default=False)
