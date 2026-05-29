from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String

from app.models.base import Base, JSONType, TimestampMixin, UUIDType


# Preset type vocabulary — keep in sync with tactic_presets.PRESETS.
PRESET_STOP_LOSS_AD = "stop_loss_ad"
PRESET_STOP_LOSS_ADSET = "stop_loss_adset"
PRESET_SURF_ADSET = "surf_adset"
PRESET_SURF_CAMPAIGN = "surf_campaign"
PRESET_REVIVE_AD = "revive_ad"
PRESET_REVIVE_ADSET = "revive_adset"
PRESET_PAUSE_TODAY = "pause_today"
PRESET_PAUSE_PERMANENT = "pause_permanent"
PRESET_SUNSETTING = "sunsetting"
PRESET_SCALE_WINNING_ADSET = "scale_winning_adset"
PRESET_SCALE_WINNING_CAMPAIGN = "scale_winning_campaign"
PRESET_CUSTOM_RULE = "custom_rule"
# Madgicx-style intraday SURF: 15-min cron, spend-threshold triggers, tier
# bands, Double Check, end-of-day timezone-aware revert. Lives in its own
# service package (app/services/surf_intraday/) — does NOT route through
# rule_engine.evaluate. See engine.poll_active_surfs for the entry point.
PRESET_SURF_INTRADAY_CAMPAIGN = "surf_intraday_campaign"

ALL_PRESETS = {
    PRESET_STOP_LOSS_AD,
    PRESET_STOP_LOSS_ADSET,
    PRESET_SURF_ADSET,
    PRESET_SURF_CAMPAIGN,
    PRESET_REVIVE_AD,
    PRESET_REVIVE_ADSET,
    PRESET_PAUSE_TODAY,
    PRESET_PAUSE_PERMANENT,
    PRESET_SUNSETTING,
    PRESET_SCALE_WINNING_ADSET,
    PRESET_SCALE_WINNING_CAMPAIGN,
    PRESET_CUSTOM_RULE,
    PRESET_SURF_INTRADAY_CAMPAIGN,
}


class Tactic(TimestampMixin, Base):
    """A bundled automation strategy (Madgicx-style preset).

    Each Tactic owns 1+ AutomationRules. Toggling tactic.is_active cascades
    to the linked rules via the daily-tactics cron, so users get one switch
    per strategy instead of managing N raw rules.
    """

    __tablename__ = "tactics"

    name = Column(String(200), nullable=False)
    preset_type = Column(String(50), nullable=False, index=True)
    platform = Column(String(20), nullable=False, default="meta", index=True)
    account_id = Column(
        UUIDType,
        ForeignKey("ad_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    config = Column(JSONType, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String(100), nullable=True)
