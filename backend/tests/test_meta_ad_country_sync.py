"""Regression tests for the Meta ad x country breakdown written at sync time.

The bug these pin: sync_meta_metrics_window used to skip any adset whose
parsed country was the catch-all "ALL", so an `ALL_*` adset produced ZERO
ad_country_metrics rows. Booking-from-Ads reads only that table, so every
Meta `[MOF] ... Remarketing All` campaign showed 0 matched bookings while
reporting real revenue (Saigon alone lost ~53M VND across two campaigns).

Country is a *preference* in the matcher, never a filter — "ALL" simply means
"no country hint", and the matcher falls back to matching on value + date. So
the row must exist. Only a genuinely unparseable country stays skipped.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest

import app.models  # noqa: F401 — register every table before create_all
from app.models.account import AdAccount
from app.models.ad import Ad
from app.models.ad_country_metric import AdCountryMetric
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.services import sync_engine
from tests.db import TestSession

D = date(2026, 6, 10)


@pytest.fixture()
def db():
    s = TestSession()
    try:
        yield s
    finally:
        s.close()


def _seed_ad(db, acc, *, adset_country: str, platform_ad_id: str) -> Ad:
    """One campaign -> one adset (with the given parsed country) -> one ad."""
    camp = Campaign(
        id=str(uuid.uuid4()), account_id=acc.id, platform="meta",
        platform_campaign_id=str(uuid.uuid4()),
        name=f"Mason_SGN_[MOF] Sales Remarketing {adset_country}", status="ACTIVE",
    )
    db.add(camp)
    db.flush()
    adset = AdSet(
        id=str(uuid.uuid4()), campaign_id=camp.id, account_id=acc.id, platform="meta",
        platform_adset_id=str(uuid.uuid4()), name=f"{adset_country}_Broad",
        status="ACTIVE", country=adset_country,
    )
    db.add(adset)
    db.flush()
    ad = Ad(
        id=str(uuid.uuid4()), ad_set_id=adset.id, campaign_id=camp.id,
        account_id=acc.id, platform="meta", platform_ad_id=platform_ad_id,
        name=f"ad-{platform_ad_id}", status="ACTIVE",
    )
    db.add(ad)
    db.flush()
    return ad


def _run_sync(db, monkeypatch, acc, ad_insights):
    """Drive sync_meta_metrics_window with only the ad-level insights stubbed."""
    monkeypatch.setattr(sync_engine, "fetch_campaign_insights", lambda *a, **kw: [])
    monkeypatch.setattr(sync_engine, "fetch_ad_set_insights", lambda *a, **kw: [])
    monkeypatch.setattr(sync_engine, "fetch_ad_insights", lambda *a, **kw: ad_insights)
    return sync_engine.sync_meta_metrics_window(db, acc, D, D)


def _insight(ad: Ad, *, revenue: float, conversions: int) -> dict:
    return {
        "entity_id": ad.platform_ad_id,
        "date": D.isoformat(),
        "spend": 100,
        "impressions": 1000,
        "clicks": 10,
        "ctr": 0.01,
        "conversions": conversions,
        "revenue": revenue,
        "revenue_website": revenue,
        "revenue_offline": 0,
        "conversions_offline": 0,
        "roas": 1.0,
        "cpa": 1.0,
        "cpc": 1.0,
        "frequency": 1.0,
    }


@pytest.fixture()
def account(db) -> AdAccount:
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id="act_12345",
        account_name="Meander Saigon", currency="VND", access_token_enc="token",
    )
    db.add(acc)
    db.flush()
    return acc


def test_all_country_adset_still_writes_a_country_row(db, monkeypatch, account):
    """The regression: an `ALL_*` adset must NOT vanish from the breakdown."""
    ad = _seed_ad(db, account, adset_country="ALL", platform_ad_id="ad_all")

    _run_sync(db, monkeypatch, account, [_insight(ad, revenue=36_011_250, conversions=16)])

    rows = db.query(AdCountryMetric).filter(AdCountryMetric.ad_id == ad.id).all()
    assert len(rows) == 1
    assert rows[0].country == "ALL"
    assert float(rows[0].revenue_website) == 36_011_250
    assert rows[0].conversions_website == 16


def test_country_specific_adset_keeps_its_iso(db, monkeypatch, account):
    ad = _seed_ad(db, account, adset_country="VN", platform_ad_id="ad_vn")

    _run_sync(db, monkeypatch, account, [_insight(ad, revenue=5000, conversions=2)])

    rows = db.query(AdCountryMetric).filter(AdCountryMetric.ad_id == ad.id).all()
    assert len(rows) == 1
    assert rows[0].country == "VN"


def test_unparseable_country_is_still_skipped(db, monkeypatch, account):
    """"Unknown" carries no signal at all — it stays out of the breakdown."""
    ad = _seed_ad(db, account, adset_country="Unknown", platform_ad_id="ad_unknown")

    _run_sync(db, monkeypatch, account, [_insight(ad, revenue=5000, conversions=2)])

    assert db.query(AdCountryMetric).filter(AdCountryMetric.ad_id == ad.id).count() == 0
