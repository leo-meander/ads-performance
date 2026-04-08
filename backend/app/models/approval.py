from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.models.base import Base, TimestampMixin, UUIDType


class ComboApproval(Base, TimestampMixin):
    __tablename__ = "combo_approvals"

    combo_id = Column(
        UUIDType,
        ForeignKey("ad_combos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    round = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="PENDING_APPROVAL")  # PENDING_APPROVAL | APPROVED | REJECTED
    submitted_by = Column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    submitted_at = Column(DateTime(timezone=True), nullable=False)
    deadline = Column(DateTime(timezone=True), nullable=True)  # Review deadline
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    # Working file link
    working_file_url = Column(Text, nullable=True)
    working_file_label = Column(String(100), nullable=True)

    # Launch info (populated after launch)
    launch_campaign_id = Column(
        UUIDType,
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
    )
    launch_meta_ad_id = Column(String(100), nullable=True)
    launch_status = Column(String(20), nullable=True)  # LAUNCHED | LAUNCH_FAILED
    launch_error = Column(Text, nullable=True)
    launched_at = Column(DateTime(timezone=True), nullable=True)


class ApprovalReviewer(Base, TimestampMixin):
    __tablename__ = "approval_reviewers"

    approval_id = Column(
        UUIDType,
        ForeignKey("combo_approvals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reviewer_id = Column(
        UUIDType,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING | APPROVED | REJECTED
    decided_at = Column(DateTime(timezone=True), nullable=True)
    notified_email_at = Column(DateTime(timezone=True), nullable=True)
    notified_system_at = Column(DateTime(timezone=True), nullable=True)
