from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.orm import validates

from app.core.name_fit import fit_name
from app.models.base import Base, JSONType, TimestampMixin, UUIDType


class GoogleAssetGroup(TimestampMixin, Base):
    __tablename__ = "google_asset_groups"

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
    platform_asset_group_id = Column(String(100), nullable=False, unique=True)
    name = Column(String(500), nullable=False)
    status = Column(String(30), nullable=False, index=True)  # ACTIVE | PAUSED | ARCHIVED
    final_urls = Column(JSONType, nullable=True)  # List of landing page URLs
    raw_data = Column(JSONType, nullable=True)

    # Platform-supplied names can exceed the column width (TikTok Smart+ builds
    # ad_name out of the whole caption). Postgres raises instead of truncating,
    # and that error aborts the entire sync transaction — see core/name_fit.py.
    @validates("name")
    def _fit_name_columns(self, key, value):
        return fit_name(value)
