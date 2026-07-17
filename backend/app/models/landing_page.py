from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text

from app.models.base import Base, TimestampMixin, UUIDType

# Source types
SOURCE_EXTERNAL = "external"  # Discovered from existing ads' final_urls
SOURCE_MANAGED = "managed"    # Built inside our CMS (has versions)

# Statuses (superset for both sources)
STATUS_DRAFT = "DRAFT"
STATUS_PENDING_APPROVAL = "PENDING_APPROVAL"
STATUS_APPROVED = "APPROVED"
STATUS_PUBLISHED = "PUBLISHED"
STATUS_REJECTED = "REJECTED"
STATUS_DISCOVERED = "DISCOVERED"  # External pages imported from ads
STATUS_ARCHIVED = "ARCHIVED"


class LandingPage(TimestampMixin, Base):
    """One row per landing page, either CMS-managed or imported from live ads.

    The (domain, slug) pair is the canonical identifier of the public URL.
    For external pages we only store metadata + analytics joins; for managed
    pages we also have content in `landing_page_versions`.
    """

    __tablename__ = "landing_pages"

    source = Column(String(20), nullable=False, index=True)  # external | managed
    branch_id = Column(
        UUIDType,
        ForeignKey("ad_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title = Column(String(300), nullable=False)
    domain = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False)
    language = Column(String(10), nullable=True)
    ta = Column(String(20), nullable=True)  # Solo | Couple | Friend | Group | Business
    status = Column(String(30), nullable=False, default=STATUS_DRAFT, index=True)
    current_version_id = Column(UUIDType, nullable=True)  # FK created in migration
    published_at = Column(DateTime(timezone=True), nullable=True)
    clarity_project_id = Column(String(50), nullable=True)
    created_by = Column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes = Column(Text, nullable=True)
    ver = Column(String(30), nullable=True)  # manual version override ("Version 1", "Version 2", …); NULL = pattern heuristic
    is_active = Column(Boolean, nullable=False, default=True, index=True)
