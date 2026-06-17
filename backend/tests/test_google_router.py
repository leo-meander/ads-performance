"""Tests for Google Ads router endpoints."""

import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.account import AdAccount
from app.models.campaign import Campaign
from app.models.google_asset_group import GoogleAssetGroup
from app.models.google_asset import GoogleAsset
from app.models.metrics import MetricsCache
from app.models.user import User
from app.routers.google_campaigns import _campaign_health
from app.services.auth_service import create_access_token, hash_password

# Test DB setup
TEST_DB_URL = "sqlite:///./test_platform.db"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _create_account(db):
    account = AdAccount(
        id=str(uuid.uuid4()),
        platform="google",
        account_id=f"goog_{uuid.uuid4().hex[:8]}",
        account_name="Test Google Account",
        currency="USD",
        is_active=True,
    )
    db.add(account)
    db.commit()
    return account


def _create_campaign(db, account_id, objective="SEARCH", name="Test Search Campaign"):
    campaign = Campaign(
        id=str(uuid.uuid4()),
        account_id=account_id,
        platform="google",
        platform_campaign_id=f"camp_{uuid.uuid4().hex[:8]}",
        name=name,
        status="ACTIVE",
        objective=objective,
        daily_budget=50.00,
        ta="Solo",
        funnel_stage="TOF",
    )
    db.add(campaign)
    db.commit()
    return campaign


def _create_asset_group(db, campaign_id, account_id):
    group = GoogleAssetGroup(
        id=str(uuid.uuid4()),
        campaign_id=campaign_id,
        account_id=account_id,
        platform_asset_group_id=f"ag_{uuid.uuid4().hex[:8]}",
        name="Test Asset Group",
        status="ACTIVE",
        final_urls=["https://example.com"],
    )
    db.add(group)
    db.commit()
    return group


def _create_asset(db, asset_group_id, account_id, asset_type="HEADLINE", text="Test Headline"):
    asset = GoogleAsset(
        id=str(uuid.uuid4()),
        asset_group_id=asset_group_id,
        account_id=account_id,
        platform_asset_id=f"asset_{uuid.uuid4().hex[:8]}",
        asset_type=asset_type,
        text_content=text,
        performance_label="GOOD",
    )
    db.add(asset)
    db.commit()
    return asset


class TestListGoogleCampaigns:
    def test_empty(self):
        resp = client.get("/api/google/campaigns")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["campaigns"] == []
        assert data["data"]["total"] == 0

    def test_with_campaigns(self):
        db = TestSession()
        account = _create_account(db)
        _create_campaign(db, account.id, "SEARCH", "Search Camp 1")
        _create_campaign(db, account.id, "PERFORMANCE_MAX", "PMax Camp 1")
        db.close()

        resp = client.get("/api/google/campaigns")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["total"] == 2

    def test_filter_by_type(self):
        db = TestSession()
        account = _create_account(db)
        _create_campaign(db, account.id, "SEARCH", "Search Only")
        _create_campaign(db, account.id, "PERFORMANCE_MAX", "PMax Only")
        db.close()

        resp = client.get("/api/google/campaigns?campaign_type=SEARCH")
        data = resp.json()
        assert data["data"]["total"] == 1
        assert data["data"]["campaigns"][0]["campaign_type"] == "SEARCH"


class TestAssetGroups:
    def test_list_asset_groups(self):
        db = TestSession()
        account = _create_account(db)
        campaign = _create_campaign(db, account.id, "PERFORMANCE_MAX", "PMax Camp")
        _create_asset_group(db, campaign.id, account.id)
        db.close()

        resp = client.get("/api/google/asset-groups")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["total"] == 1
        assert data["data"]["asset_groups"][0]["name"] == "Test Asset Group"

    def test_get_asset_group_with_assets(self):
        db = TestSession()
        account = _create_account(db)
        campaign = _create_campaign(db, account.id, "PERFORMANCE_MAX", "PMax")
        group = _create_asset_group(db, campaign.id, account.id)
        _create_asset(db, group.id, account.id, "HEADLINE", "Book Now")
        _create_asset(db, group.id, account.id, "DESCRIPTION", "Best hotel in town")
        group_id = group.id
        db.close()

        resp = client.get(f"/api/google/asset-groups/{group_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["name"] == "Test Asset Group"
        assert len(data["data"]["assets"]) == 2

    def test_asset_group_not_found(self):
        resp = client.get("/api/google/asset-groups/nonexistent")
        assert resp.status_code == 404


class TestGoogleDashboard:
    def test_empty_dashboard(self):
        resp = client.get("/api/google/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["kpis"]["total_spend"] == 0
        assert data["data"]["campaign_counts"]["total"] == 0

    def test_campaign_counts(self):
        db = TestSession()
        account = _create_account(db)
        _create_campaign(db, account.id, "SEARCH", "Search 1")
        _create_campaign(db, account.id, "SEARCH", "Search 2")
        _create_campaign(db, account.id, "PERFORMANCE_MAX", "PMax 1")
        db.close()

        resp = client.get("/api/google/dashboard")
        data = resp.json()
        assert data["data"]["campaign_counts"]["search"] == 2
        assert data["data"]["campaign_counts"]["performance_max"] == 1
        assert data["data"]["campaign_counts"]["total"] == 3


# ── Overview / health triage ───────────────────────────────


def _admin_headers():
    """Persist an admin user and return a Bearer header. Admin role bypasses
    all branch/section scoping (see app.core.permissions)."""
    db = TestSession()
    user = User(
        id=str(uuid.uuid4()),
        email=f"admin_{uuid.uuid4().hex[:8]}@meander.com",
        full_name="Admin",
        password_hash=hash_password("pass"),
        roles=["admin"],
    )
    db.add(user)
    db.commit()
    uid, roles = user.id, user.roles
    db.close()
    return {"Authorization": f"Bearer {create_access_token(uid, roles)}"}


def _add_metric(db, campaign_id, *, days_ago=1, spend=0, impressions=0, clicks=0,
                conversions=0, revenue=0):
    db.add(MetricsCache(
        id=str(uuid.uuid4()),
        campaign_id=campaign_id,
        ad_set_id=None,
        ad_id=None,
        platform="google",
        date=date.today() - timedelta(days=days_ago),
        spend=spend,
        impressions=impressions,
        clicks=clicks,
        conversions=conversions,
        revenue=revenue,
    ))
    db.commit()


class TestCampaignHealth:
    """Pure-function tests for the triage classifier (no HTTP/DB)."""

    def _h(self, **kw):
        base = dict(
            spend=0, impressions=0, clicks=0, conversions=0, revenue=0,
            daily_budget=None, period_days=30, roas_target=3.0,
            campaign_status="ACTIVE",
        )
        base.update(kw)
        return _campaign_health(**base)

    def test_ok_above_target(self):
        r = self._h(spend=100, impressions=2000, clicks=120, conversions=10, revenue=500)
        assert r["status"] == "ok" and r["roas"] == 5.0

    def test_watch_just_below_target(self):
        r = self._h(spend=100, impressions=2000, clicks=120, conversions=5, revenue=250)
        assert r["status"] == "watch"  # 2.5x, between floor 1.8 and target 3

    def test_action_low_roas(self):
        r = self._h(spend=100, impressions=2000, clicks=120, conversions=2, revenue=80)
        assert r["status"] == "action"  # 0.8x

    def test_action_zero_conversions_with_traffic(self):
        r = self._h(spend=50, impressions=1000, clicks=60, conversions=0, revenue=0)
        assert r["status"] == "action"
        assert "conversion" in r["hint"].lower()

    def test_learning_low_traffic(self):
        r = self._h(spend=5, impressions=100, clicks=5, conversions=0, revenue=0)
        assert r["status"] == "learning"

    def test_learning_no_delivery(self):
        r = self._h(spend=0, impressions=0, clicks=0, conversions=0, revenue=0)
        assert r["status"] == "learning"

    def test_budget_limited_flag(self):
        # avg daily spend 100/10 = 10 >= 0.9 * 10 budget
        r = self._h(spend=100, impressions=2000, clicks=120, conversions=10,
                    revenue=500, daily_budget=10, period_days=10)
        assert r["budget_limited"] is True
        assert "budget" in r["hint"].lower()

    def test_currency_neutral_target(self):
        # Same ROAS, wildly different currency magnitudes -> same verdict.
        small = self._h(spend=100, impressions=2000, clicks=120, conversions=10, revenue=500)
        huge = self._h(spend=5_000_000, impressions=2000, clicks=120,
                       conversions=10, revenue=25_000_000)
        assert small["status"] == huge["status"] == "ok"


class TestGoogleOverview:
    def test_empty(self):
        resp = client.get("/api/google/overview", headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["summary"]["total"] == 0
        assert data["data"]["campaigns"] == []

    def test_classifies_and_counts(self):
        db = TestSession()
        account = _create_account(db)
        win = _create_campaign(db, account.id, "SEARCH", "Winner")
        lose = _create_campaign(db, account.id, "PERFORMANCE_MAX", "Loser")
        _add_metric(db, win.id, spend=100, impressions=2000, clicks=120,
                    conversions=10, revenue=500)   # ok (5x)
        _add_metric(db, lose.id, spend=100, impressions=2000, clicks=120,
                    conversions=2, revenue=80)      # action (0.8x)
        db.close()

        data = client.get(
            "/api/google/overview?roas_target=3", headers=_admin_headers()
        ).json()["data"]
        assert data["summary"]["ok"] == 1
        assert data["summary"]["action"] == 1
        # worst bubbles to the top
        assert data["campaigns"][0]["health"] == "action"
        assert data["campaigns"][0]["name"] == "Loser"

    def test_branch_rollup_currency_safe(self):
        db = TestSession()
        account = _create_account(db)  # USD
        c1 = _create_campaign(db, account.id, "SEARCH", "A")
        c2 = _create_campaign(db, account.id, "PERFORMANCE_MAX", "B")
        _add_metric(db, c1.id, spend=100, impressions=1000, clicks=50,
                    conversions=4, revenue=400)
        _add_metric(db, c2.id, spend=100, impressions=1000, clicks=50,
                    conversions=4, revenue=200)
        db.close()

        branches = client.get(
            "/api/google/overview", headers=_admin_headers()
        ).json()["data"]["branches"]
        assert len(branches) == 1
        b = branches[0]
        assert b["spend"] == 200 and b["revenue"] == 600
        assert b["roas"] == 3.0 and b["currency"] == "USD"
        assert b["needs_action"] >= 0
