"""Tests for get_channel_monthly_vnd — the Growth Team sheet export feed.

Builds an in-memory SQLite DB with two branches in different currencies and
verifies allocate + spend are folded per (month, branch, channel) and
converted to VND via currency_rates.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.account import AdAccount
from app.models.campaign import Campaign
from app.models.currency_rate import CurrencyRate
from app.models.budget import BudgetPlan
from app.models.metrics import MetricsCache
from app.services.budget_service import get_channel_monthly_vnd


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _account(s, name, currency, platform="meta"):
    a = AdAccount(platform=platform, account_id=f"act_{name}", account_name=name, currency=currency)
    s.add(a)
    s.flush()
    return a


_camp_seq = [0]


def _campaign(s, account, platform="meta"):
    _camp_seq[0] += 1
    c = Campaign(
        account_id=account.id, platform=platform,
        platform_campaign_id=f"camp_{_camp_seq[0]}",
        name=f"{platform} camp", status="ACTIVE",
    )
    s.add(c)
    s.flush()
    return c


def _metric(s, campaign, platform, d, spend, ad_set_id=None, ad_id=None):
    s.add(MetricsCache(
        campaign_id=campaign.id, platform=platform, date=d, spend=spend,
        ad_set_id=ad_set_id, ad_id=ad_id,
    ))


def test_folds_and_converts_to_vnd(db):
    db.add(CurrencyRate(currency="JPY", rate_to_vnd=170))
    # Saigon = VND (rate 1), Osaka = JPY (rate 170)
    sg = _account(db, "Meander Saigon", "VND")
    os_ = _account(db, "Meander Osaka", "JPY")
    sg_c = _campaign(db, sg)
    os_c = _campaign(db, os_)

    # Allocate (native): Saigon Meta 10,000,000 VND; Osaka Meta 50,000 JPY
    db.add(BudgetPlan(name="sg meta", branch="Saigon", channel="meta",
                      month=date(2026, 3, 1), total_budget=10_000_000, currency="VND"))
    db.add(BudgetPlan(name="os meta", branch="Osaka", channel="meta",
                      month=date(2026, 3, 1), total_budget=50_000, currency="JPY"))

    # Spend (native, campaign-level): Saigon 6,000,000 VND across two days
    _metric(db, sg_c, "meta", date(2026, 3, 5), 4_000_000)
    _metric(db, sg_c, "meta", date(2026, 3, 9), 2_000_000)
    # Osaka 30,000 JPY -> 5,100,000 VND
    _metric(db, os_c, "meta", date(2026, 3, 10), 30_000)
    # Noise: an ad-set-level row must be ignored (anti double-count)
    _metric(db, sg_c, "meta", date(2026, 3, 5), 999_999, ad_set_id="ad-set-x")
    db.flush()

    rows = get_channel_monthly_vnd(db, 2026)
    by = {(r["branch"], r["channel"], r["month"]): r for r in rows}

    sg_row = by[("Saigon", "Meta", 3)]
    assert sg_row["allocate_vnd"] == 10_000_000
    assert sg_row["spend_vnd"] == 6_000_000  # ad-set row excluded
    assert sg_row["spend_pct"] == 60.0
    assert sg_row["currency"] == "VND"

    os_row = by[("Osaka", "Meta", 3)]
    assert os_row["allocate_vnd"] == 50_000 * 170  # 8,500,000
    assert os_row["spend_vnd"] == 30_000 * 170     # 5,100,000
    assert os_row["currency"] == "JPY"


def test_year_and_month_filter(db):
    sg = _account(db, "Meander Saigon", "VND")
    c = _campaign(db, sg)
    _metric(db, c, "meta", date(2026, 3, 5), 1_000_000)
    _metric(db, c, "meta", date(2026, 4, 5), 2_000_000)
    _metric(db, c, "meta", date(2025, 3, 5), 9_000_000)  # other year
    db.flush()

    # Year-wide: only 2026 rows, two months.
    rows = get_channel_monthly_vnd(db, 2026)
    months = sorted(r["month"] for r in rows)
    assert months == [3, 4]

    # Month filter narrows to March.
    march = get_channel_monthly_vnd(db, 2026, month=3)
    assert [r["month"] for r in march] == [3]
    assert march[0]["spend_vnd"] == 1_000_000


def test_excludes_non_ad_channels_and_empty_rows(db):
    sg = _account(db, "Meander Saigon", "VND")
    # A KOL plan must never surface here.
    db.add(BudgetPlan(name="sg kol", branch="Saigon", channel="kol",
                      month=date(2026, 3, 1), total_budget=5_000_000, currency="VND"))
    # A zero-everything meta plan should be dropped.
    db.add(BudgetPlan(name="sg meta", branch="Saigon", channel="meta",
                      month=date(2026, 3, 1), total_budget=0, currency="VND"))
    db.flush()

    rows = get_channel_monthly_vnd(db, 2026)
    assert rows == []


def test_branch_filter(db):
    db.add(CurrencyRate(currency="JPY", rate_to_vnd=170))
    sg = _account(db, "Meander Saigon", "VND")
    os_ = _account(db, "Meander Osaka", "JPY")
    _metric(db, _campaign(db, sg), "meta", date(2026, 3, 5), 1_000_000)
    _metric(db, _campaign(db, os_), "meta", date(2026, 3, 5), 1_000)
    db.flush()

    rows = get_channel_monthly_vnd(db, 2026, branch="Saigon")
    assert {r["branch"] for r in rows} == {"Saigon"}
