from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text

from app.models.base import Base, JSONType, TimestampMixin, UUIDType


# Canonical category values. Validated by the changelog helper — the DB does
# not constrain them so we can add new categories without migrations.
CATEGORY_AD_MUTATION = "ad_mutation"
CATEGORY_AD_CREATION = "ad_creation"
CATEGORY_AUTOMATION_RULE_APPLIED = "automation_rule_applied"
CATEGORY_LANDING_PAGE = "landing_page"
CATEGORY_EXTERNAL_SEASONALITY = "external_seasonality"
CATEGORY_EXTERNAL_COMPETITOR = "external_competitor"
CATEGORY_EXTERNAL_ALGORITHM = "external_algorithm"
CATEGORY_TRACKING_INTEGRITY = "tracking_integrity"
CATEGORY_OTHER = "other"

ALL_CATEGORIES = {
    CATEGORY_AD_MUTATION,
    CATEGORY_AD_CREATION,
    CATEGORY_AUTOMATION_RULE_APPLIED,
    CATEGORY_LANDING_PAGE,
    CATEGORY_EXTERNAL_SEASONALITY,
    CATEGORY_EXTERNAL_COMPETITOR,
    CATEGORY_EXTERNAL_ALGORITHM,
    CATEGORY_TRACKING_INTEGRITY,
    CATEGORY_OTHER,
}

# Categories users can pick in the manual-entry form. Auto-only categories
# (automation_rule_applied) are excluded.
MANUAL_ALLOWED_CATEGORIES = {
    CATEGORY_AD_MUTATION,
    CATEGORY_AD_CREATION,
    CATEGORY_LANDING_PAGE,
    CATEGORY_EXTERNAL_SEASONALITY,
    CATEGORY_EXTERNAL_COMPETITOR,
    CATEGORY_EXTERNAL_ALGORITHM,
    CATEGORY_TRACKING_INTEGRITY,
    CATEGORY_OTHER,
}


class ChangeLogEntry(TimestampMixin, Base):
    """Unified change log: auto-emitted from system actions + manual entries for
    external factors (landing page, seasonality, competitor, algorithm, tracking).

    Surfaced on /country as the Activity Log tab + chart overlay markers."""

    __tablename__ = "change_log_entries"

    occurred_at = Column(DateTime(timezone=True), nullable=False, index=True)

    category = Column(String(40), nullable=False, index=True)
    source = Column(String(20), nullable=False, index=True)  # auto | manual
    triggered_by = Column(String(20), nullable=False)  # rule | manual | api | system

    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    country = Column(String(8), nullable=True, index=True)
    branch = Column(String(40), nullable=True, index=True)
    platform = Column(String(20), nullable=True, index=True)

    account_id = Column(
        UUIDType,
        ForeignKey("ad_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    campaign_id = Column(
        UUIDType,
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ad_set_id = Column(
        UUIDType,
        ForeignKey("ad_sets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ad_id = Column(
        UUIDType,
        ForeignKey("ads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    before_value = Column(JSONType, nullable=True)
    after_value = Column(JSONType, nullable=True)
    metrics_snapshot = Column(JSONType, nullable=True)

    source_url = Column(Text, nullable=True)
    author_user_id = Column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    action_log_id = Column(
        UUIDType,
        ForeignKey("action_logs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    rule_id = Column(
        UUIDType,
        ForeignKey("automation_rules.id", ondelete="SET NULL"),
        nullable=True,
    )

    is_deleted = Column(Boolean, nullable=False, default=False, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
