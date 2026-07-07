from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from app.models.base import Base, TimestampMixin, UUIDType


class ApprovalComment(Base):
    __tablename__ = "approval_comments"

    id = Column(UUIDType, primary_key=True, server_default=func.gen_random_uuid())
    # Either approval_id or batch_id is set, not both
    approval_id = Column(
        UUIDType,
        ForeignKey("combo_approvals.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    batch_id = Column(
        UUIDType,
        ForeignKey("approval_batches.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    user_id = Column(
        UUIDType,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    body = Column(Text, nullable=False)
    parent_id = Column(
        UUIDType,
        ForeignKey("approval_comments.id", ondelete="CASCADE"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ApprovalBatch(Base, TimestampMixin):
    """Groups multiple combo_approvals submitted together as versions of one
    review. Reviewers decide the whole batch at once (all-or-nothing): the
    decision is applied to every child combo_approval. Holds only the shared
    submission metadata; each version keeps its own combo_approval row (and
    its own launch lifecycle)."""

    __tablename__ = "approval_batches"

    submitted_by = Column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    round = Column(Integer, nullable=False, default=1)
    submitted_at = Column(DateTime(timezone=True), nullable=False)
    deadline = Column(DateTime(timezone=True), nullable=True)
    note = Column(Text, nullable=True)


class ComboApproval(Base, TimestampMixin):
    __tablename__ = "combo_approvals"

    # Set when this approval is one version inside a multi-version batch.
    # NULL = standalone single-version approval (legacy + 1-version submits).
    batch_id = Column(
        UUIDType,
        ForeignKey("approval_batches.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    combo_id = Column(
        UUIDType,
        ForeignKey("ad_combos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    round = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="ONGOING")  # ONGOING | APPROVED
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

    # Hypothesis being tested by this approval — optional link
    hypothesis_id = Column(
        String(20),
        ForeignKey("creative_hypotheses.hypothesis_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Free-text note from the submitter, shown to reviewers for extra context
    note = Column(Text, nullable=True)

    # Branch-manager sign-off (recorded offline, e.g. over chat). When set, the
    # combo was marked APPROVED via this evidence path instead of the in-app
    # reviewer round. bm_proof_image holds the screenshot as a base64 data URL
    # (the app has no blob storage, so the proof lives inline on the row).
    bm_approved_at = Column(DateTime(timezone=True), nullable=True)
    bm_approved_by = Column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    bm_proof_image = Column(Text, nullable=True)

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


class ApprovalReviewerHistory(Base):
    """Immutable snapshot of a reviewer's decision before a round reset."""
    __tablename__ = "approval_reviewer_history"

    id = Column(UUIDType, primary_key=True, server_default=func.gen_random_uuid())
    approval_id = Column(UUIDType, ForeignKey("combo_approvals.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer_id = Column(UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    round = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False)
    feedback = Column(Text, nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


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
    status = Column(String(20), nullable=False, default="ONGOING")  # ONGOING | APPROVED
    decided_at = Column(DateTime(timezone=True), nullable=True)
    feedback = Column(Text, nullable=True)  # Reviewer's free-text feedback on the ad copy / combo
    notified_email_at = Column(DateTime(timezone=True), nullable=True)
    notified_system_at = Column(DateTime(timezone=True), nullable=True)
