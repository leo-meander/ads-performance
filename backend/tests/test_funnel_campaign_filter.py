"""Campaign-scoped funnel: the `campaign_ids` filter on both funnel endpoints.

The dashboard's "Filter campaigns…" box narrows the Lead/Conversion funnel to
the matching campaigns. It sends campaign_ids to /dashboard/funnel, and — when
a country is also selected — to /dashboard/country/funnel, which had no such
param and silently returned every campaign in the branch.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest

import app.models  # noqa: F401 — register every table before create_all
from app.models.account import AdAccount
from app.models.campaign import Campaign
from app.models.metrics import MetricsCache
from app.models.user import User
from app.routers.campaigns import _aggregate_funnel
from app.routers.country import country_funnel
from tests.db import TestSession

D_FROM = date(2026, 8, 1)
D_TO = date(2026, 8, 7)


@pytest.fixture
def db():
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def admin(db):
    u = User(
        id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex[:8]}@staymeander.com",
        full_name="Admin", password_hash="x", roles=["admin"], is_active=True,
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def account(db):
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Meander Taipei", currency="TWD", is_active=True,
    )
    db.add(acc)
    db.flush()
    return acc


def _campaign(db, account, name, country, impressions, clicks, searches,
              add_to_cart, checkouts, conversions):
    c = Campaign(
        id=str(uuid.uuid4()), account_id=account.id, platform="meta",
        platform_campaign_id=f"c_{uuid.uuid4().hex[:8]}", name=name,
        status="ACTIVE", objective="OUTCOME_SALES", country=country,
    )
    db.add(c)
    db.flush()
    db.add(MetricsCache(
        id=str(uuid.uuid4()), campaign_id=c.id, platform="meta", date=D_FROM,
        ad_set_id=None, ad_id=None, spend=100, revenue=500,
        impressions=impressions, clicks=clicks, searches=searches,
        add_to_cart=add_to_cart, checkouts=checkouts, conversions=conversions,
    ))
    db.flush()
    return c


@pytest.fixture
def seeded(db, account):
    """Two US campaigns — the funnel must be able to show just one of them."""
    target = _campaign(db, account, "Mason_TPE_[TOF] Leads US", "US",
                       impressions=1000, clicks=100, searches=50,
                       add_to_cart=20, checkouts=10, conversions=5)
    other = _campaign(db, account, "Mason_TPE_[MOF] Remarketing US", "US",
                      impressions=9000, clicks=900, searches=450,
                      add_to_cart=180, checkouts=90, conversions=45)
    return target, other


class TestAggregateFunnelCampaignIds:
    def test_scopes_to_the_named_campaign(self, db, seeded):
        target, _other = seeded
        scoped = _aggregate_funnel(db, D_FROM, D_TO, None, campaign_ids=[target.id])
        assert scoped["impressions"] == 1000
        assert scoped["clicks"] == 100
        assert scoped["bookings"] == 5

    def test_unfiltered_sums_both(self, db, seeded):
        both = _aggregate_funnel(db, D_FROM, D_TO, None)
        assert both["impressions"] == 10000
        assert both["bookings"] == 50


class TestCountryFunnelCampaignIds:
    def test_scopes_to_the_named_campaign(self, db, admin, seeded):
        target, _other = seeded
        res = country_funnel(
            country="US", date_from=D_FROM.isoformat(), date_to=D_TO.isoformat(),
            campaign_ids=target.id, current_user=admin, db=db,
            ta=None, funnel_stage=None, platform=None, account_id=None,
            branches=None, campaign_type=None,
        )
        assert res["success"] is True
        by_name = {s["name"]: s["value"] for s in res["data"]["stages"]}
        assert by_name["Impression"] == 1000
        assert by_name["Booking"] == 5

    def test_unfiltered_sums_both(self, db, admin, seeded):
        res = country_funnel(
            country="US", date_from=D_FROM.isoformat(), date_to=D_TO.isoformat(),
            campaign_ids=None, current_user=admin, db=db,
            ta=None, funnel_stage=None, platform=None, account_id=None,
            branches=None, campaign_type=None,
        )
        by_name = {s["name"]: s["value"] for s in res["data"]["stages"]}
        assert by_name["Impression"] == 10000
        assert by_name["Booking"] == 50

    def test_emits_steps_with_keys(self, db, admin, seeded):
        """The dashboard reads `steps` (key + label) for leak highlighting and
        the funnel diagnosis — country funnel used to return `stages` only."""
        res = country_funnel(
            country="US", date_from=D_FROM.isoformat(), date_to=D_TO.isoformat(),
            campaign_ids=None, current_user=admin, db=db,
            ta=None, funnel_stage=None, platform=None, account_id=None,
            branches=None, campaign_type=None,
        )
        steps = res["data"]["steps"]
        assert [s["key"] for s in steps] == [
            "impressions", "clicks", "searches", "add_to_cart", "checkouts", "bookings",
        ]
        # Same numbers as `stages`, just keyed.
        assert [s["value"] for s in steps] == [s["value"] for s in res["data"]["stages"]]

    def test_no_data_response_still_carries_steps(self, db, admin, seeded):
        res = country_funnel(
            country="JP", date_from=D_FROM.isoformat(), date_to=D_TO.isoformat(),
            campaign_ids=None, current_user=admin, db=db,
            ta=None, funnel_stage=None, platform=None, account_id=None,
            branches=None, campaign_type=None,
        )
        assert res["data"]["stages"] == []
        assert res["data"]["steps"] == []
