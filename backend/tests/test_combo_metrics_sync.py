"""Tests for combo_metrics_sync — the Meta pull behind the Creative Library.

Meta's get_insights is mocked. Coverage:
  - hook_rate uses 3-second plays (actions:video_view) / impressions,
    NOT video_play_actions (which counts every autoplay start and used to
    inflate hook rate to 80-90%)
  - same-named ads are summed into one combo
  - omni_purchase -> conversions/revenue
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register every table before create_all
from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.base import Base
from app.services import combo_metrics_sync as mod

engine = create_engine(
    "sqlite:///test_combo_metrics.db",
    connect_args={"check_same_thread": False},
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


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


def _seed(db) -> tuple[AdAccount, AdCombo]:
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id="act_123",
        account_name="Oani", currency="TWD",
        access_token_enc="tok", is_active=True,
    )
    db.add(acc)
    combo = AdCombo(
        id=str(uuid.uuid4()), combo_id="CMB-001", branch_id=acc.id,
        ad_name="[Video] KOL_test", copy_id="CPY-001", material_id="MAT-001",
    )
    db.add(combo)
    db.commit()
    return acc, combo


def _row(**overrides):
    row = {
        "ad_name": "[Video] KOL_test",
        "spend": "100.0", "impressions": "1000", "clicks": "50",
        "actions": [
            {"action_type": "omni_purchase", "value": "2"},
            # 3-second plays — the real hook-rate numerator
            {"action_type": "video_view", "value": "180"},
        ],
        "action_values": [{"action_type": "omni_purchase", "value": "500.0"}],
        # Near-1:1 with impressions (autoplay) — must NOT drive hook_rate
        "video_play_actions": [{"value": "900"}],
        "video_thruplay_watched_actions": [{"value": "300"}],
        "video_p100_watched_actions": [{"value": "90"}],
        "inline_post_engagement": "120",
    }
    row.update(overrides)
    return row


def test_hook_rate_uses_3s_plays_not_video_plays(monkeypatch):
    _patch_meta(monkeypatch, [_row()])
    db = TestSession()
    acc, combo = _seed(db)

    summary = mod.sync_combo_metrics_for_account(db, acc)
    db.commit()
    db.refresh(combo)

    assert summary["combos_updated"] == 1
    assert combo.video_plays == 900  # raw any-play count still stored
    assert float(combo.hook_rate) == pytest.approx(180 / 1000)  # 18%, not 90%
    assert combo.conversions == 2
    assert float(combo.revenue) == 500.0
    db.close()


def test_hook_rate_none_without_video_view(monkeypatch):
    _patch_meta(monkeypatch, [_row(actions=[{"action_type": "omni_purchase", "value": "1"}])])
    db = TestSession()
    acc, combo = _seed(db)

    mod.sync_combo_metrics_for_account(db, acc)
    db.commit()
    db.refresh(combo)

    assert combo.hook_rate is None
    db.close()


def test_same_named_ads_are_summed(monkeypatch):
    _patch_meta(monkeypatch, [
        _row(),
        _row(spend="50.0", impressions="500",
             actions=[{"action_type": "video_view", "value": "70"}]),
    ])
    db = TestSession()
    acc, combo = _seed(db)

    mod.sync_combo_metrics_for_account(db, acc)
    db.commit()
    db.refresh(combo)

    assert combo.impressions == 1500
    # Numeric(8,6) column rounds to 6 decimal places
    assert float(combo.hook_rate) == pytest.approx((180 + 70) / 1500, abs=1e-6)
    db.close()
