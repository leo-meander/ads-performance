from sqlalchemy import Column, Date, ForeignKey, Numeric, String
from sqlalchemy.orm import validates

from app.core.name_fit import fit_name
from app.models.base import Base, JSONType, TimestampMixin, UUIDType


class AdSet(TimestampMixin, Base):
    __tablename__ = "ad_sets"

    campaign_id = Column(
        UUIDType,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id = Column(
        UUIDType,
        ForeignKey("ad_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform = Column(String(20), nullable=False, index=True)
    platform_adset_id = Column(String(100), nullable=False, unique=True)
    name = Column(String(500), nullable=False)
    status = Column(String(30), nullable=False, index=True)
    optimization_goal = Column(String(100), nullable=True)
    billing_event = Column(String(50), nullable=True)
    daily_budget = Column(Numeric(15, 2), nullable=True)
    lifetime_budget = Column(Numeric(15, 2), nullable=True)
    targeting = Column(JSONType, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    country = Column(String(8), nullable=True, index=True)  # Parsed: ISO 3166-1 alpha-2, or 'ALL' for multi-country adsets
    raw_data = Column(JSONType, nullable=True)

    # Platform-supplied names can exceed the column width (TikTok Smart+ builds
    # ad_name out of the whole caption). Postgres raises instead of truncating,
    # and that error aborts the entire sync transaction — see core/name_fit.py.
    @validates("name")
    def _fit_name_columns(self, key, value):
        return fit_name(value)
