"""Regression tests for the multi-day, multi-branch sync blackout.

On 2026-08-18 the dashboard lost every branch except Taipei/Oani. The crons
kept returning HTTP 202 and re-running them changed nothing, because:

  - `sync_all_platforms` iterated accounts with no per-account guard, so the
    first account that raised took every account after it down with it, and
  - nothing logged the failure: the cron discards the returned list, and the
    per-account `errors` key was only ever read by /sync/status.

The trigger was a ratio column overflow: `roas` is NUMERIC(8,4) (max
9999.9999) while revenue is stored in native currency, so one VND booking
attributed to a near-zero-spend ad produces a ROAS Postgres refuses — and a
DataError aborts the whole transaction, not just that row.

These tests pin the three behaviours that keep a single bad row from costing
days of data.
"""
from __future__ import annotations

import logging

from app.services.metric_bounds import (
    CTR_MAX,
    MONEY_RATIO_MAX,
    ROAS_MAX,
    clamp_metric,
    clamp_ratio_fields,
)


class _FakeAccount:
    def __init__(self, name, platform="meta"):
        self.id = name
        self.account_name = name
        self.platform = platform


class _FakeQuery:
    def __init__(self, accounts):
        self._accounts = accounts

    def filter(self, *a, **kw):
        return self

    def all(self):
        return self._accounts


class _FakeDB:
    def __init__(self, accounts):
        self._accounts = accounts
        self.rollbacks = 0

    def query(self, *a, **kw):
        return _FakeQuery(self._accounts)

    def rollback(self):
        self.rollbacks += 1


# --------------------------------------------------------------- clamping ---


def test_roas_beyond_column_limit_is_clamped_not_raised():
    # 28,080,000 VND of booking revenue on 2,000 VND of spend.
    fields = {"roas": 14040.0, "ctr": 0.04, "cpa": 1000.0, "cpc": 2.5, "frequency": 1.2}
    clamp_ratio_fields(fields, context="test")
    assert fields["roas"] == ROAS_MAX
    # Everything within range is untouched.
    assert fields["ctr"] == 0.04
    assert fields["cpa"] == 1000.0
    assert fields["frequency"] == 1.2


def test_clamp_handles_none_nan_and_missing_keys():
    assert clamp_metric(None, ROAS_MAX, field="roas") is None
    assert clamp_metric(float("nan"), ROAS_MAX, field="roas") is None
    assert clamp_metric(float("inf"), ROAS_MAX, field="roas") is None
    assert clamp_metric("not a number", ROAS_MAX, field="roas") is None
    # A dict without ratio keys comes back unchanged rather than gaining Nones.
    fields = {"spend": 100}
    assert clamp_ratio_fields(fields) == {"spend": 100}


def test_ctr_and_money_ratios_keep_their_own_limits():
    assert clamp_metric(1e9, CTR_MAX, field="ctr") == CTR_MAX
    assert clamp_metric(1e20, MONEY_RATIO_MAX, field="cpa") == MONEY_RATIO_MAX


def test_meta_upsert_clamps_before_writing():
    """The clamp has to sit in the upsert path, not just in the helper."""
    import uuid
    from datetime import date

    from app.models.account import AdAccount
    from app.models.campaign import Campaign
    from app.models.metrics import MetricsCache
    from app.services.sync_engine import _upsert_metrics_row
    from tests.db import TestSession

    db = TestSession()
    try:
        account = AdAccount(
            id=str(uuid.uuid4()), platform="meta", account_id="act_1",
            account_name="Meander Saigon", currency="VND", is_active=True,
        )
        campaign = Campaign(
            id=str(uuid.uuid4()), account_id=account.id, platform="meta",
            platform_campaign_id="c1", name="Mason_SG_[TOF] Test", status="ACTIVE",
        )
        db.add_all([account, campaign])
        db.flush()

        insight = {
            "spend": 2000, "impressions": 10, "clicks": 1, "conversions": 1,
            "revenue": 28080000, "roas": 14040.0, "cpa": 2000, "cpc": 2000,
            "frequency": 1.0, "ctr": 0.1,
        }
        _upsert_metrics_row(db, campaign.id, insight, date(2026, 8, 19))
        db.flush()

        row = db.query(MetricsCache).filter(MetricsCache.campaign_id == campaign.id).one()
        assert float(row.roas) == ROAS_MAX
        assert float(row.revenue) == 28080000  # money is never clamped
    finally:
        db.rollback()
        db.close()


# ------------------------------------------------------ per-account guard ---


def test_one_failing_account_does_not_starve_the_rest(monkeypatch, caplog):
    import app.services.sync_engine as mod

    accounts = [_FakeAccount("Taipei"), _FakeAccount("Saigon"), _FakeAccount("Osaka")]
    db = _FakeDB(accounts)
    synced = []

    def _fake_sync(db, account, date_from=None, date_to=None):
        if account.account_name == "Saigon":
            raise RuntimeError("numeric field overflow")
        synced.append(account.account_name)
        return {"metrics_synced": 3, "errors": []}

    monkeypatch.setattr(mod, "sync_meta_account", _fake_sync)
    monkeypatch.setattr(mod, "auto_classify_all_combos", lambda db: None)
    monkeypatch.setattr(mod, "assign_angles_for_new_combos", lambda db: {"updated": 0})
    monkeypatch.setattr(mod, "evaluate_all_rules", lambda db, tactics_filter=None: [])

    with caplog.at_level(logging.ERROR):
        results = mod.sync_all_platforms(db)

    # Osaka sits AFTER the account that blew up and still got synced.
    assert synced == ["Taipei", "Osaka"]
    assert db.rollbacks == 1
    assert len(results) == 3

    failed = [r for r in results if r.get("errors")]
    assert [r["account_name"] for r in failed] == ["Saigon"]
    # And the failure is loud — the cron only ever sees HTTP 202.
    assert "Saigon" in caplog.text


# ------------------------------------------------------------ /sync/health ---


def test_sync_health_flags_the_account_that_stopped_receiving_data():
    """The endpoint that turns "a branch vanished from the pie" into one call."""
    import uuid
    from datetime import date, timedelta

    from fastapi.testclient import TestClient

    from app.main import app
    from app.models.account import AdAccount
    from app.models.campaign import Campaign
    from app.models.metrics import MetricsCache
    from tests.db import TestSession

    db = TestSession()
    yesterday = date.today() - timedelta(days=1)
    try:
        for name, last_date in (("Meander Taipei", yesterday), ("Meander Saigon", yesterday - timedelta(days=3))):
            account = AdAccount(
                id=str(uuid.uuid4()), platform="meta", account_id=f"act_{name}",
                account_name=name, currency="VND", is_active=True,
            )
            campaign = Campaign(
                id=str(uuid.uuid4()), account_id=account.id, platform="meta",
                platform_campaign_id=f"c_{name}", name=name, status="ACTIVE",
            )
            db.add_all([account, campaign, MetricsCache(
                campaign_id=campaign.id, platform="meta", date=last_date,
                spend=1000, impressions=10, clicks=1, conversions=0, revenue=0,
            )])
        db.commit()

        res = TestClient(app).get("/api/sync/health")
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True, body["error"]
        data = body["data"]

        assert data["accounts_total"] == 2
        assert data["stale_accounts"] == ["Meander Saigon"]
        saigon = next(a for a in data["accounts"] if a["account_name"] == "Meander Saigon")
        assert saigon["days_behind"] == 3
        assert saigon["branch"] == "Saigon"
        taipei = next(a for a in data["accounts"] if a["account_name"] == "Meander Taipei")
        assert taipei["stale"] is False
    finally:
        db.close()
