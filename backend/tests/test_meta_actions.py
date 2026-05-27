"""Regression tests for meta_actions budget writes.

Guards the unit round-trip: budgets are stored verbatim from Meta (sync_engine)
and must be written back verbatim — no `* 100` rescale. A prior bug multiplied
the value by 100 inside update_campaign_budget / update_ad_set_budget, sending
~125x the intended budget (and bypassing the 25% guard, which runs before the
write).
"""

import pytest

from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.campaign import Campaign

from app.services import meta_actions


def test_update_campaign_budget_writes_value_verbatim(monkeypatch):
    monkeypatch.setattr(meta_actions, "_init_api", lambda token: None)
    captured: dict = {}

    def fake_remote_update(self, *args, **kwargs):
        captured["daily_budget"] = self[Campaign.Field.daily_budget]
        return self

    monkeypatch.setattr(Campaign, "remote_update", fake_remote_update)

    meta_actions.update_campaign_budget(
        "tok", "c_1", current_daily_budget=100.0, new_daily_budget=125.0,
    )
    # 125, NOT 12500 — the value Meta receives must match the native unit it
    # returned on read.
    assert captured["daily_budget"] == 125


def test_update_campaign_budget_guard_blocks_before_write(monkeypatch):
    monkeypatch.setattr(meta_actions, "_init_api", lambda token: None)
    called = {"remote": False}

    def fake_remote_update(self, *args, **kwargs):
        called["remote"] = True
        return self

    monkeypatch.setattr(Campaign, "remote_update", fake_remote_update)

    with pytest.raises(meta_actions.BudgetGuardError):
        meta_actions.update_campaign_budget(
            "tok", "c_1", current_daily_budget=100.0, new_daily_budget=150.0,
        )
    # Guard must reject before any write reaches Meta.
    assert called["remote"] is False


def test_update_ad_set_budget_writes_value_verbatim(monkeypatch):
    monkeypatch.setattr(meta_actions, "_init_api", lambda token: None)
    captured: dict = {}

    def fake_remote_update(self, *args, **kwargs):
        captured["daily_budget"] = self[AdSet.Field.daily_budget]
        return self

    monkeypatch.setattr(AdSet, "remote_update", fake_remote_update)

    meta_actions.update_ad_set_budget(
        "tok", "as_1", current_daily_budget=50.0, new_daily_budget=60.0,
    )
    assert captured["daily_budget"] == 60
