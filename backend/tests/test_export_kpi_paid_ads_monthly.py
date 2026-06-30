"""Tests for GET /api/export/kpi/paid-ads-monthly (X-API-Key).

Locks in that this endpoint mirrors the /dashboard/country headline aggregate:
campaign-level rows only (ad_id IS NULL AND ad_set_id IS NULL), valid country
only, native ROAS, and FX_TO_VND conversion — so the Growth Team KPI sheet shows
the same numbers Mason sees on the dashboard.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — register every table before create_all
from app.database import get_db
from app.main import app
from app.models.account import AdAccount
from app.models.api_key import ApiKey
from app.models.base import Base
from app.models.campaign import Campaign
from app.models.metrics import MetricsCache
from app.services.export_auth import generate_api_key

engine = create_engine(
    "sqlite:///test_export_kpi_paid_ads_monthly.db",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    prev = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    if prev is not None:
        app.dependency_overrides[get_db] = prev
    else:
        app.dependency_overrides.pop(get_db, None)


def _api_key(db) -> str:
    plaintext, key_hash, key_prefix = generate_api_key()
    db.add(ApiKey(id=str(uuid.uuid4()), name="KPI sheet", key_hash=key_hash, key_prefix=key_prefix))
    db.commit()
    return plaintext


def _account(db, name="Meander Osaka", currency="JPY") -> AdAccount:
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}", account_name=name,
        currency=currency, is_active=True,
    )
    db.add(acc)
    db.flush()
    return acc


def _campaign(db, account, country="JP") -> Campaign:
    c = Campaign(
        id=str(uuid.uuid4()), account_id=account.id, platform="meta",
        platform_campaign_id=f"c_{uuid.uuid4().hex[:8]}", name="Osaka_Couple_TOF",
        status="ACTIVE", country=country,
    )
    db.add(c)
    db.flush()
    return c


def _metric(db, campaign, *, d, spend, revenue, conv, ad_set_id=None, ad_id=None):
    db.add(MetricsCache(
        id=str(uuid.uuid4()), campaign_id=campaign.id, platform="meta", date=d,
        spend=spend, revenue=revenue, conversions=conv,
        ad_set_id=ad_set_id, ad_id=ad_id,
    ))


def test_campaign_level_valid_country_aggregates_and_converts():
    db = TestSession()
    key = _api_key(db)
    acc = _account(db, "Meander Osaka", "JPY")
    camp = _campaign(db, acc, country="JP")
    # June: campaign-level row that SHOULD count.
    _metric(db, camp, d=date(2026, 6, 5), spend=100000, revenue=330000, conv=20)
    # June noise that must be EXCLUDED:
    _metric(db, camp, d=date(2026, 6, 6), spend=999, revenue=999, conv=9, ad_set_id=str(uuid.uuid4()))  # adset-level
    _metric(db, camp, d=date(2026, 6, 7), spend=999, revenue=999, conv=9, ad_id=str(uuid.uuid4()))      # ad-level
    db.commit()
    db.close()

    r = client.get("/api/export/kpi/paid-ads-monthly?year=2026&branch=osaka",
                   headers={"X-API-Key": key})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    branches = body["data"]["branches"]
    assert len(branches) == 1
    osaka = branches[0]
    assert osaka["branch"] == "Osaka"
    assert osaka["currency"] == "JPY"

    june = next(m for m in osaka["months"] if m["month"] == 6)
    assert june["spend_native"] == 100000.0
    assert june["revenue_native"] == 330000.0
    assert june["conversions"] == 20
    assert june["roas"] == 3.3  # 330000 / 100000, native — matches dashboard
    assert june["spend_vnd"] == 100000 * 170
    assert june["revenue_vnd"] == 330000 * 170

    # A month with no data is zero-filled with roas=None.
    jan = next(m for m in osaka["months"] if m["month"] == 1)
    assert jan["spend_native"] == 0.0
    assert jan["roas"] is None


def test_unknown_country_row_is_dropped():
    db = TestSession()
    key = _api_key(db)
    acc = _account(db, "Meander Osaka", "JPY")
    camp = _campaign(db, acc, country="Unknown")  # invalid → excluded
    _metric(db, camp, d=date(2026, 6, 5), spend=50000, revenue=150000, conv=10)
    db.commit()
    db.close()

    r = client.get("/api/export/kpi/paid-ads-monthly?year=2026&branch=osaka",
                   headers={"X-API-Key": key})
    june = next(m for m in r.json()["data"]["branches"][0]["months"] if m["month"] == 6)
    assert june["spend_native"] == 0.0
    assert june["roas"] is None


def test_all_country_marker_counts():
    db = TestSession()
    key = _api_key(db)
    acc = _account(db, "Meander Osaka", "JPY")
    camp = _campaign(db, acc, country="ALL")  # multi-country rollup → valid
    _metric(db, camp, d=date(2026, 6, 5), spend=10000, revenue=40000, conv=4)
    db.commit()
    db.close()

    r = client.get("/api/export/kpi/paid-ads-monthly?year=2026&branch=osaka",
                   headers={"X-API-Key": key})
    june = next(m for m in r.json()["data"]["branches"][0]["months"] if m["month"] == 6)
    assert june["revenue_native"] == 40000.0
    assert june["roas"] == 4.0


def test_requires_api_key():
    assert client.get("/api/export/kpi/paid-ads-monthly?year=2026").status_code == 422


def test_unknown_branch_errors():
    db = TestSession()
    key = _api_key(db)
    db.close()
    r = client.get("/api/export/kpi/paid-ads-monthly?year=2026&branch=nope",
                   headers={"X-API-Key": key})
    assert r.json()["success"] is False
