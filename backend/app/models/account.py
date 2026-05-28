from sqlalchemy import Boolean, Column, Numeric, String, Text

from app.models.base import Base, TimestampMixin


class AdAccount(TimestampMixin, Base):
    __tablename__ = "ad_accounts"

    platform = Column(String(20), nullable=False, index=True)  # meta | google | tiktok
    account_id = Column(String(100), nullable=False, unique=True)  # platform native ID
    account_name = Column(String(200), nullable=False)
    currency = Column(String(3), nullable=False, default="VND")
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    access_token_enc = Column(Text, nullable=True)  # encrypted OAuth token
    # GA4 property id for this branch. Format is just the numeric id
    # (e.g. "514380737") — the GA4 SDK expects "properties/{id}" which we
    # prefix at query time.
    ga4_property_id = Column(String(50), nullable=True)
    # Facebook Page the ads are published from. Required by Meta when
    # building an AdCreative with link_data — every link ad ships under a
    # Page. Stored per-branch because each property has its own Page.
    meta_page_id = Column(String(50), nullable=True)
    # Fallback landing URL used by AdCreative.link_data.link when the combo
    # has no explicit destination. Typically the branch homepage or default
    # booking page.
    default_destination_url = Column(Text, nullable=True)

    # ------------------- Per-branch budget mutation limits ------------------
    # Drive the Raise/Cut budget buttons on /action-needed. Defaults preserve
    # the legacy hardcoded behavior: +25% raise, -50% cut, no absolute cap.
    # Set max_*_per_click_abs to clamp the absolute change in account currency
    # (NT$, VND, JPY). NULL = no cap.
    #
    # Read by app/routers/action_needed.py:apply_action. Mutated only via
    # PATCH /accounts/{id}/budget-limits — both writes audit to change_log.
    raise_pct = Column(Numeric(5, 4), nullable=False, default=0.25)
    cut_pct = Column(Numeric(5, 4), nullable=False, default=0.50)
    max_raise_per_click_abs = Column(Numeric(15, 2), nullable=True)
    max_cut_per_click_abs = Column(Numeric(15, 2), nullable=True)
