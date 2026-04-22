from sqlalchemy import Column, Date, ForeignKey, Integer, Numeric, String

from app.models.base import Base, JSONType, TimestampMixin, UUIDType


class LandingPageGA4Snapshot(TimestampMixin, Base):
    """Daily Google Analytics 4 metrics per landing page.

    Complements Clarity + Meta/Google ad metrics:
      - `sessions` is GA4's authoritative count (independent of Meta Pixel or
        Clarity JS — lets us cross-validate all three).
      - Ecommerce funnel (begin_checkout → add_payment_info → purchases) gives
        the granular drop-off numbers the Playbook §7.1 asks for.
      - Web Vitals (lcp / inp / cls p75) are pulled from the GA4 web-vitals
        event so we have honest §5.3 numbers instead of guessing page speed.

    Break-down columns (source / medium / campaign) come from GA4's
    `sessionSource / sessionMedium / sessionCampaign` dimensions. The
    aggregate row (source=medium=campaign=NULL) lets the dashboard sum
    totals without joining.
    """

    __tablename__ = "landing_page_ga4_snapshots"

    landing_page_id = Column(
        UUIDType,
        ForeignKey("landing_pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date = Column(Date, nullable=False, index=True)
    source = Column(String(100), nullable=True)
    medium = Column(String(100), nullable=True)
    campaign = Column(String(200), nullable=True)

    # Core traffic
    sessions = Column(Integer, nullable=False, default=0)
    engaged_sessions = Column(Integer, nullable=False, default=0)
    engagement_rate = Column(Numeric(6, 4), nullable=True)
    active_users = Column(Integer, nullable=False, default=0)
    new_users = Column(Integer, nullable=False, default=0)
    screen_page_views = Column(Integer, nullable=False, default=0)
    avg_session_duration_sec = Column(Numeric(10, 2), nullable=True)
    bounce_rate = Column(Numeric(6, 4), nullable=True)

    # Ecommerce funnel
    begin_checkout = Column(Integer, nullable=False, default=0)
    add_payment_info = Column(Integer, nullable=False, default=0)
    purchases = Column(Integer, nullable=False, default=0)
    purchase_revenue = Column(Numeric(15, 2), nullable=False, default=0)

    # Web Vitals (p75 — same percentile Google uses for Core Web Vitals pass/fail)
    lcp_p75_ms = Column(Integer, nullable=True)
    inp_p75_ms = Column(Integer, nullable=True)
    cls_p75 = Column(Numeric(6, 4), nullable=True)
    fcp_p75_ms = Column(Integer, nullable=True)

    raw_data = Column(JSONType, nullable=True)
