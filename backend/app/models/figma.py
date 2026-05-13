from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)

from app.models.base import Base, JSONType, TimestampMixin, UUIDType


class FigmaTemplate(TimestampMixin, Base):
    """Designer-registered Figma master frame.

    placeholder_schema describes the named layers the backend can fill, e.g.:
      {
        "headline":  {"type": "text", "max_chars": 60},
        "subhead":   {"type": "text", "max_chars": 120},
        "cta":       {"type": "text", "max_chars": 24},
        "hero_image":{"type": "image"}
      }

    The Figma REST API can READ layer text and EXPORT renders, but cannot
    WRITE text content directly — variant generation produces a figma_jobs
    row + a deep-link the designer opens to apply the suggestions, plus
    (in a follow-up phase) optional Figma plugin auto-fill.
    """
    __tablename__ = "figma_templates"

    name = Column(String(200), nullable=False)
    file_key = Column(String(80), nullable=False)  # Figma file key
    node_id = Column(String(80), nullable=False)   # Frame/component node id
    branch_id = Column(
        UUIDType,
        ForeignKey("ad_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    platform = Column(String(20), nullable=False, default="meta", index=True)
    width = Column(Integer, nullable=False, default=1080)
    height = Column(Integer, nullable=False, default=1080)
    placeholder_schema = Column(JSONType, nullable=False, default=dict)
    preview_image_url = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_by = Column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class FigmaJob(TimestampMixin, Base):
    """One render/variant request.

    Lifecycle: PENDING → RUNNING → COMPLETED|FAILED. The cron poller
    /internal/tasks/figma-job-poll moves PENDING rows forward by exporting
    the template (and any future plugin-generated variant) to a PNG URL.
    """
    __tablename__ = "figma_jobs"

    template_id = Column(
        UUIDType,
        ForeignKey("figma_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_combo_id = Column(
        String(10),
        ForeignKey("ad_combos.combo_id", ondelete="SET NULL"),
        nullable=True,
    )
    request_payload = Column(JSONType, nullable=False, default=dict)
    # request_payload typically holds: {placeholder_name: value} (the
    # text/image overrides) plus any free-form notes the requester left.
    status = Column(String(20), nullable=False, default="PENDING", index=True)
    output_figma_url = Column(Text, nullable=True)
    output_image_url = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    requested_by = Column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    requested_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
