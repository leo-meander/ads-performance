"""Tests for daily_ad_metrics_sync — the Meta pull behind Ad Name Performance.

Meta's get_insights is mocked. Coverage:
  - only spend > 0 rows are stored
  - omni_purchase -> conversions/revenue, lead action types -> leads
  - 3-level identity (campaign/adset/ad) + per-day grain is preserved
  - re-running is idempotent (delete-then-insert, no double counting)

Dates are relative to date.today() so the [since, today] delete window always
covers the seeded rows regardless of the test machine's clock.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register every table before create_all
from app.models.account import AdAccount
from app.models.ad_daily_metric import AdDailyMetric
from app.models.base import Base
from app.services import daily_ad_metrics_sync as mod

engine = create_engine(
    "sqlite:///test_ad_daily.db",
    connect_args={"check_same_thread": False},
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

D0 = date.today()
D1 = D0 - timedelta(days=1)
SINCE = D0 - timedelta(days=10)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _fake_fb(rows):
    class _FB:
        def __init__(self, *a, **k):
            pass

        def get_insights(self, **kwargs):
            return rows

    return _FB


def _patch_meta(monkeypatch, rows):
    monkeypatch.setattr(mod, "FacebookAdsApi", SimpleNamespace(init=lambda **k: None))
    monkeypatch.setattr(mod, "FBAdAccount", _fake_fb(rows))


def _seed_account(db) -> AdAccount:
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id="act_123",
        account_name="Saigon", currency="VND",
        access_token_enc="tok", is_active=True,
    )
    db.add(acc)
    db.commit()
    return acc


def _rows():
    return [
        {  # spend > 0, video + purchase + lead
            "campaign_id": "c1", "campaign_name": "Camp A",
            "adset_id": "s1", "adset_name": "Set A",
            "ad_id": "a1", "ad_name": "Ad One", "date_start": D1.isoformat(),
            "spend": "100.0", "impressions": "1000", "clicks": "50",
            "actions": [
                {"action_type": "omni_purchase", "value": "2"},
                {"action_type": "lead", "value": "3"},
                {"action_type": "onsite_conversion.lead_grouped", "value": "1"},
            ],
            "action_values": [{"action_type": "omni_purchase", "value": "500.0"}],
            "video_play_actions": [{"value": "800"}],
            "video_thruplay_watched_actions": [{"value": "400"}],
            "video_p100_watched_actions": [{"value": "200"}],
            "inline_post_engagement": "120",
        },
        {  # same ad, next day — also spend > 0
            "campaign_id": "c1", "campaign_name": "Camp A",
            "adset_id": "s1", "adset_name": "Set A",
            "ad_id": "a1", "ad_name": "Ad One", "date_start": D0.isoformat(),
            "spend": "50.0", "impressions": "400", "clicks": "10",
            "actions": [{"action_type": "omni_purchase", "value": "1"}],
            "action_values": [{"action_type": "omni_purchase", "value": "250.0"}],
        },
        {  # zero spend — must be skipped
            "campaign_id": "c1", "campaign_name": "Camp A",
            "adset_id": "s1", "adset_name": "Set A",
            "ad_id": "a2", "ad_name": "Ad Two", "date_start": D0.isoformat(),
            "spend": "0", "impressions": "5", "clicks": "0",
        },
    ]


def test_filters_zero_spend_and_parses_actions(monkeypatch):
    _patch_meta(monkeypatch, _rows())
    db = TestSession()
    acc = _seed_account(db)

    summary = mod.sync_daily_ad_metrics_for_account(db, acc, since_date=SINCE)
    db.commit()

    assert summary["rows_written"] == 2
    assert summary["rows_skipped_no_spend"] == 1

    stored = db.query(AdDailyMetric).order_by(AdDailyMetric.date).all()
    assert len(stored) == 2
    assert {s.ad_id for s in stored} == {"a1"}  # a2 (zero spend) skipped

    day1 = next(s for s in stored if s.date == D1)
    assert day1.campaign_name == "Camp A"
    assert day1.adset_name == "Set A"
    assert day1.ad_name == "Ad One"
    assert float(day1.spend) == 100.0
    assert day1.conversions == 2
    assert float(day1.revenue) == 500.0
    assert day1.leads == 4  # 3 (lead) + 1 (onsite_conversion.lead_grouped)
    assert day1.video_plays == 800
    assert day1.thruplay == 400
    assert day1.video_p100 == 200
    db.close()


def test_resync_is_idempotent(monkeypatch):
    _patch_meta(monkeypatch, _rows())
    db = TestSession()
    acc = _seed_account(db)

    mod.sync_daily_ad_metrics_for_account(db, acc, since_date=SINCE)
    db.commit()
    first = db.query(AdDailyMetric).count()

    # Re-run with the SAME data — delete-then-insert must not double-count.
    mod.sync_daily_ad_metrics_for_account(db, acc, since_date=SINCE)
    db.commit()
    second = db.query(AdDailyMetric).count()

    assert first == 2
    assert second == 2
    db.close()


def test_non_meta_account_is_noop(monkeypatch):
    _patch_meta(monkeypatch, _rows())
    db = TestSession()
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="google", account_id="g1",
        account_name="G", currency="USD", access_token_enc="tok", is_active=True,
    )
    db.add(acc)
    db.commit()

    summary = mod.sync_daily_ad_metrics_for_account(db, acc, since_date=SINCE)
    assert summary["rows_written"] == 0
    assert db.query(AdDailyMetric).count() == 0
    db.close()
