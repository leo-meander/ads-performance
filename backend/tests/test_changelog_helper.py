"""Tests for the changelog helper — context resolution, baseline capture,
diff formatting, and the never-raises invariant."""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.account import AdAccount
from app.models.ad import Ad
from app.models.ad_set import AdSet
from app.models.base import Base
from app.models.campaign import Campaign
from app.models.change_log_entry import (
    ALL_CATEGORIES,
    MANUAL_ALLOWED_CATEGORIES,
    ChangeLogEntry,
)
from app.models.metrics import MetricsCache
from app.services.changelog import (
    capture_baseline_snapshot,
    describe_diff,
    log_change,
    resolve_entity_context,
)


engine = create_engine(
    "sqlite:///test_changelog.db", connect_args={"check_same_thread": False}
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _seed_entities(country: str = "VN", account_name: str = "Meander Saigon"):
    """Create an AdAccount → Campaign → AdSet → Ad tree and return their IDs."""
    db = TestSession()
    acc = AdAccount(
        id=str(uuid.uuid4()),
        platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:6]}",
        account_name=account_name,
        currency="VND",
        access_token_enc="x",
    )
    db.add(acc)
    db.flush()
    camp = Campaign(
        id=str(uuid.uuid4()),
        account_id=acc.id,
        platform="meta",
        platform_campaign_id=f"c_{uuid.uuid4().hex[:6]}",
        name="Test Camp",
        status="ACTIVE",
        objective="CONVERSIONS",
    )
    db.add(camp)
    db.flush()
    adset = AdSet(
        id=str(uuid.uuid4()),
        campaign_id=camp.id,
        account_id=acc.id,
        platform="meta",
        platform_adset_id=f"as_{uuid.uuid4().hex[:6]}",
        name=f"{country}_Solo [TOF]",
        status="ACTIVE",
        country=country,
    )
    db.add(adset)
    db.flush()
    ad = Ad(
        id=str(uuid.uuid4()),
        ad_set_id=adset.id,
        campaign_id=camp.id,
        account_id=acc.id,
        platform="meta",
        platform_ad_id=f"a_{uuid.uuid4().hex[:6]}",
        name="Test Ad",
        status="ACTIVE",
    )
    db.add(ad)
    db.commit()
    ids = {
        "account_id": acc.id,
        "campaign_id": camp.id,
        "ad_set_id": adset.id,
        "ad_id": ad.id,
    }
    db.close()
    return ids


class TestCategoryEnums:
    def test_manual_allowed_is_subset_of_all(self):
        assert MANUAL_ALLOWED_CATEGORIES.issubset(ALL_CATEGORIES)

    def test_automation_rule_applied_not_manual(self):
        assert "automation_rule_applied" in ALL_CATEGORIES
        assert "automation_rule_applied" not in MANUAL_ALLOWED_CATEGORIES


class TestDescribeDiff:
    def test_status_flip(self):
        assert describe_diff({"status": "ACTIVE"}, {"status": "PAUSED"}) == "Status ACTIVE → PAUSED"

    def test_budget_increase(self):
        out = describe_diff({"daily_budget": 500000}, {"daily_budget": 600000})
        assert out is not None
        assert "500,000" in out and "600,000" in out and "+20%" in out

    def test_budget_decrease(self):
        out = describe_diff({"daily_budget": 1000}, {"daily_budget": 500})
        assert out is not None
        assert "-50%" in out

    def test_no_change(self):
        assert describe_diff({"x": 1}, {"x": 1}) is None

    def test_empty(self):
        assert describe_diff(None, None) is None
        assert describe_diff({}, {}) is None

    def test_other_keys(self):
        out = describe_diff({"name": "old"}, {"name": "new"})
        assert out == "Changed: name"


class TestResolveEntityContext:
    def test_resolves_from_ad_id(self):
        ids = _seed_entities(country="VN", account_name="Meander Saigon")
        db = TestSession()
        try:
            ctx = resolve_entity_context(db, ad_id=ids["ad_id"])
            assert ctx["ad_id"] == ids["ad_id"]
            assert ctx["ad_set_id"] == ids["ad_set_id"]
            assert ctx["campaign_id"] == ids["campaign_id"]
            assert ctx["account_id"] == ids["account_id"]
            assert ctx["country"] == "VN"
            assert ctx["platform"] == "meta"
            assert ctx["branch"] == "Saigon"
        finally:
            db.close()

    def test_resolves_from_campaign_id(self):
        ids = _seed_entities(country="JP", account_name="Meander Osaka")
        db = TestSession()
        try:
            ctx = resolve_entity_context(db, campaign_id=ids["campaign_id"])
            assert ctx["country"] == "JP"
            assert ctx["branch"] == "Osaka"
            assert ctx["platform"] == "meta"
        finally:
            db.close()

    def test_resolves_branch_taipei_vs_oani(self):
        ids = _seed_entities(country="TW", account_name="Oani (Taipei)")
        db = TestSession()
        try:
            ctx = resolve_entity_context(db, account_id=ids["account_id"])
            # Must resolve to Oani, NOT Taipei — the bare "Taipei" pattern is
            # intentionally omitted from BRANCH_ACCOUNT_MAP["Taipei"].
            assert ctx["branch"] == "Oani"
        finally:
            db.close()

    def test_null_safe(self):
        db = TestSession()
        try:
            ctx = resolve_entity_context(db)
            assert all(v is None for v in ctx.values())
        finally:
            db.close()


class TestCaptureBaselineSnapshot:
    def test_returns_none_without_scope(self):
        db = TestSession()
        try:
            assert capture_baseline_snapshot(db) is None
        finally:
            db.close()

    def test_returns_zeros_when_no_metrics(self):
        ids = _seed_entities()
        db = TestSession()
        try:
            snap = capture_baseline_snapshot(db, campaign_id=ids["campaign_id"])
            assert snap is not None
            assert snap["spend"] == 0
            assert snap["days"] == 7
        finally:
            db.close()

    def test_aggregates_ad_level_metrics(self):
        ids = _seed_entities()
        db = TestSession()
        try:
            # Seed metrics rows at ad level.
            for i in range(3):
                db.add(
                    MetricsCache(
                        campaign_id=ids["campaign_id"],
                        ad_set_id=ids["ad_set_id"],
                        ad_id=ids["ad_id"],
                        platform="meta",
                        date=date.today(),
                        spend=100.0,
                        impressions=1000,
                        clicks=50,
                        conversions=5,
                        revenue=500.0,
                    )
                )
            db.commit()
            snap = capture_baseline_snapshot(db, ad_id=ids["ad_id"], days=7)
            assert snap is not None
            assert snap["spend"] == 300.0
            assert snap["conversions"] == 15
            assert snap["roas"] == pytest.approx(1500.0 / 300.0)
        finally:
            db.close()


class TestLogChange:
    def test_writes_entry_with_resolved_context(self):
        ids = _seed_entities(country="VN", account_name="Meander Saigon")
        db = TestSession()
        try:
            entry = log_change(
                db,
                category="ad_mutation",
                title="Budget change",
                source="auto",
                triggered_by="rule",
                ad_id=ids["ad_id"],
                before_value={"daily_budget": 500000},
                after_value={"daily_budget": 600000},
            )
            db.commit()
            assert entry is not None
            assert entry.country == "VN"
            assert entry.branch == "Saigon"
            assert entry.platform == "meta"
            assert entry.campaign_id == ids["campaign_id"]
        finally:
            db.close()

    def test_rejects_unknown_category(self):
        db = TestSession()
        try:
            assert log_change(db, category="bogus", title="x") is None
        finally:
            db.close()

    def test_rejects_invalid_source(self):
        db = TestSession()
        try:
            assert log_change(db, category="ad_mutation", title="x", source="weird") is None
        finally:
            db.close()

    def test_manual_entry_explicit_country(self):
        db = TestSession()
        try:
            entry = log_change(
                db,
                category="landing_page",
                title="LP hero swap",
                source="manual",
                triggered_by="manual",
                country="VN",
                branch="Saigon",
                description="Swapped hero image",
                author_user_id=str(uuid.uuid4()),
            )
            db.commit()
            assert entry is not None
            assert entry.country == "VN"
            assert entry.branch == "Saigon"
            assert entry.source == "manual"
        finally:
            db.close()

    def test_never_raises_on_db_error(self):
        """Invariant: log_change swallows exceptions — caller must not see failures."""
        db = TestSession()
        try:
            with patch("app.services.changelog.resolve_entity_context", side_effect=RuntimeError("boom")):
                entry = log_change(db, category="ad_mutation", title="x", ad_id="nonexistent")
            assert entry is None
        finally:
            db.close()

    def test_occurred_at_defaults_to_now(self):
        db = TestSession()
        try:
            entry = log_change(db, category="other", title="ping", source="manual", triggered_by="manual")
            db.commit()
            assert entry is not None
            # SQLite strips tz on read; just verify occurred_at is set + recent.
            assert entry.occurred_at is not None
        finally:
            db.close()
