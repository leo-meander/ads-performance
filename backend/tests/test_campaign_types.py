"""Sale / Lead / Engagement bucketing for the dashboard's campaign toggle.

The three buckets must partition every campaign — the dashboard shows them as
exclusive tabs, so a campaign counted twice (or dropped) silently corrupts the
Spend/ROAS headline.
"""
from __future__ import annotations

import uuid

import pytest

import app.models  # noqa: F401 — register every table before create_all
from app.core.campaign_types import apply_campaign_type
from app.models.account import AdAccount
from app.models.campaign import Campaign
from tests.db import TestSession


@pytest.fixture
def db():
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def account(db):
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Meander Osaka", currency="JPY",
    )
    db.add(acc)
    db.flush()
    return acc


def _campaign(db, account, name: str, objective: str | None) -> str:
    db.add(Campaign(
        id=str(uuid.uuid4()), account_id=account.id, platform="meta",
        platform_campaign_id=f"c_{uuid.uuid4().hex[:8]}", name=name,
        status="ACTIVE", objective=objective,
    ))
    db.flush()
    return name


def _names(db, campaign_type: str | None) -> set[str]:
    q = apply_campaign_type(db.query(Campaign), campaign_type)
    return {c.name for c in q.all()}


@pytest.fixture
def seeded(db, account):
    """One campaign per real-world shape we sync."""
    return {
        "sale": _campaign(db, account, "Mason_OSK_[TOF] Sale_202608 JP", "OUTCOME_SALES"),
        "sale_no_objective": _campaign(db, account, "Mason_OSK_[BOF] Booking_202608 JP", None),
        "lead": _campaign(db, account, "Mason_OSK_[TOF] Lead Gen_202608 JP", "OUTCOME_LEADS"),
        "tiktok_engagement": _campaign(db, account, "Mason_OSK_[TOF] Engagement_202608 AU", "ENGAGEMENT"),
        "meta_engagement": _campaign(db, account, "Mason_OSK_[TOF] Community_202608 JP", "OUTCOME_ENGAGEMENT"),
        "video_views": _campaign(db, account, "Video views20260617140207", "VIDEO_VIEWS"),
        "awareness": _campaign(db, account, "Mason_OSK_[TOF] Brand_202608 JP", "OUTCOME_AWARENESS"),
        # Objective never made it through sync — the name carries the intent.
        "engagement_by_name": _campaign(db, account, "Mason_TPE_[TOF] Engagement_202607 TW", None),
        # Real campaign names drop the second 'e' ("Engagment Store 1"), so the
        # name fallback matches the stem rather than the full word.
        "engagement_typo": _campaign(db, account, "Mason_BE_[TOF] Engagment Store 1 20260701", None),
    }


def test_engagement_matches_objective_and_name(db, seeded):
    assert _names(db, "engagement") == {
        seeded["tiktok_engagement"], seeded["meta_engagement"], seeded["video_views"],
        seeded["awareness"], seeded["engagement_by_name"], seeded["engagement_typo"],
    }


def test_sale_excludes_engagement(db, seeded):
    """Sale used to mean 'not Lead', so it swallowed engagement campaigns."""
    assert _names(db, "sale") == {seeded["sale"], seeded["sale_no_objective"]}


def test_lead_wins_over_engagement(db, account):
    """A campaign named Lead but carrying an engagement objective belongs to
    Lead — campaign names are the ops team's deliberate label."""
    name = _campaign(db, account, "Mason_OSK_[TOF] Lead Form_202608 JP", "OUTCOME_ENGAGEMENT")
    assert name in _names(db, "lead")
    assert name not in _names(db, "engagement")


def test_buckets_partition_all_campaigns(db, seeded):
    everything = _names(db, None)
    sale, lead, engagement = _names(db, "sale"), _names(db, "lead"), _names(db, "engagement")

    assert sale | lead | engagement == everything
    assert sale & lead == set()
    assert sale & engagement == set()
    assert lead & engagement == set()


def test_null_objective_does_not_vanish(db, account):
    """COALESCE guard: a NULL objective must still land in exactly one bucket
    (SQL three-valued logic would drop it from both sale and engagement)."""
    name = _campaign(db, account, "Mason_OSK_[MOF] Remarketing_202608 JP", None)
    assert name in _names(db, "sale")
    assert name not in _names(db, "engagement")


def test_unknown_campaign_type_is_treated_as_all(db, seeded):
    assert _names(db, "not-a-bucket") == _names(db, None)


class TestFunnelShape:
    def test_engagement_funnel_walks_watch_depth_and_keeps_purchase(self):
        from app.routers.campaigns import _funnel_shape
        keys, labels = _funnel_shape("engagement")
        assert keys == ["impressions", "video_3s_views", "video_thru_plays", "clicks", "bookings"]
        assert labels[-1] == "Booking"

    def test_sale_and_lead_shapes_unchanged(self):
        from app.routers.campaigns import _funnel_shape
        assert _funnel_shape("sale")[0] == [
            "impressions", "clicks", "searches", "add_to_cart", "checkouts", "bookings",
        ]
        assert _funnel_shape("lead")[0] == [
            "impressions", "clicks", "landing_page_views", "leads", "bookings",
        ]
        assert _funnel_shape(None)[0] == _funnel_shape("sale")[0]
