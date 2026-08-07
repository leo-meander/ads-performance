"""TikTok sync must roll adgroup country up to Campaign.country.

Campaign-level metric rows don't join an AdSet, so the country dashboard falls
back to Campaign.country. TikTok campaign names carry no country token — with
Campaign.country NULL the dashboard drops every TikTok row and the branch
reads zero spend.
"""
from __future__ import annotations

import uuid

import pytest

import app.models  # noqa: F401 — register every table before create_all
from app.config import settings
from app.models.account import AdAccount
from app.models.campaign import Campaign
from app.services import tiktok_sync_engine
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
        id=str(uuid.uuid4()), platform="tiktok",
        account_id="7566923025061527568",
        account_name="Meander Osaka TikTok", currency="JPY",
    )
    db.add(acc)
    db.commit()
    return acc


def _campaign(cid: str, name: str) -> dict:
    return {
        "platform_campaign_id": cid, "name": name, "status": "ACTIVE",
        "objective": "ENGAGEMENT", "daily_budget": None, "lifetime_budget": None,
        "start_date": None, "end_date": None, "raw_data": {},
    }


def _adgroup(agid: str, campaign_id: str, name: str) -> dict:
    return {
        "platform_adset_id": agid, "campaign_id": campaign_id, "name": name,
        "status": "ACTIVE", "optimization_goal": None, "billing_event": None,
        "daily_budget": None, "lifetime_budget": None, "targeting": {},
        "start_date": None, "end_date": None, "raw_data": {},
    }


@pytest.fixture
def stub_tiktok(monkeypatch):
    """Patch the TikTok API surface; caller supplies campaigns + adgroups."""
    monkeypatch.setattr(settings, "TIKTOK_ACCESS_TOKEN", "test-token")

    def _install(campaigns, adgroups):
        monkeypatch.setattr(tiktok_sync_engine, "fetch_campaigns", lambda _a: campaigns)
        monkeypatch.setattr(tiktok_sync_engine, "fetch_adgroups", lambda _a: adgroups)
        monkeypatch.setattr(tiktok_sync_engine, "fetch_ads", lambda _a: [])
        for fn in ("fetch_campaign_metrics", "fetch_adgroup_metrics", "fetch_ad_metrics"):
            monkeypatch.setattr(tiktok_sync_engine, fn, lambda _a, _f, _t: [])

    return _install


def _country_of(db, platform_campaign_id: str) -> str | None:
    return (
        db.query(Campaign)
        .filter(Campaign.platform_campaign_id == platform_campaign_id)
        .first()
        .country
    )


def test_single_country_adgroup_sets_campaign_country(db, account, stub_tiktok):
    stub_tiktok(
        [_campaign("c1", "Mason_OSK_[TOF] Engagement_202608 AU")],
        [_adgroup("ag1", "c1", "AU_25-44")],
    )

    tiktok_sync_engine.sync_tiktok_account(db, account)

    assert _country_of(db, "c1") == "AU"


def test_multi_country_adgroups_roll_up_to_all(db, account, stub_tiktok):
    stub_tiktok(
        [_campaign("c2", "Mason_OSK_[TOF] Engagement_202608")],
        [_adgroup("ag2", "c2", "AU_25-44"), _adgroup("ag3", "c2", "TW_25-44")],
    )

    tiktok_sync_engine.sync_tiktok_account(db, account)

    assert _country_of(db, "c2") == "ALL"


def test_unknown_adgroup_country_is_ignored_in_rollup(db, account, stub_tiktok):
    """A single unparseable adgroup must not turn a one-country campaign into
    'ALL' — the dashboard would lose per-country attribution for it."""
    stub_tiktok(
        [_campaign("c3", "Mason_OSK_[TOF] Engagement_202608")],
        [_adgroup("ag4", "c3", "AU_25-44"), _adgroup("ag5", "c3", "")],
    )

    tiktok_sync_engine.sync_tiktok_account(db, account)

    assert _country_of(db, "c3") == "AU"


def test_no_parseable_country_leaves_campaign_untouched(db, account, stub_tiktok):
    stub_tiktok(
        [_campaign("c4", "Video views20260617140207")],
        [],
    )

    tiktok_sync_engine.sync_tiktok_account(db, account)

    assert _country_of(db, "c4") is None
