"""Tests for the ad_daily_metrics cron task.

The table behind /winning-ads had no scheduled sync — only the manual "Sync
from Meta" button — while cron-freeze-winning-ads ran daily regardless. Since a
verdict freezes once and an ad is judged once ever, freezing against a stale
table can stamp an ad into the wrong month permanently.

What's worth pinning here is the substance, not the FastAPI plumbing:
  - the rolling window is `today - days_back`, so the nightly run stays cheap
    while still overlapping enough to absorb Meta's late attribution
  - per-account failures are LOGGED, since sync_all_daily_ad_metrics collects
    them instead of raising and would otherwise look identical to a branch
    that simply didn't spend
  - days_back is bounded, so a typo can't turn the nightly job into a
    full-history refetch
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers import internal_tasks

client = TestClient(app)


def _patch_sync(monkeypatch, result=None, captured=None):
    """Stand in for the Meta-hitting sync, recording the window it was given."""
    import app.services.daily_ad_metrics_sync as mod

    def _fake(db, since_date=None, until_date=None, account_ids=None):
        if captured is not None:
            captured["since_date"] = since_date
            captured["until_date"] = until_date
        return result if result is not None else {
            "accounts": 1, "rows_written": 5, "errors": [],
        }

    monkeypatch.setattr(mod, "sync_all_daily_ad_metrics", _fake)


def test_rolling_window_starts_days_back_from_today(monkeypatch):
    captured: dict = {}
    _patch_sync(monkeypatch, captured=captured)

    internal_tasks._do_sync_daily_ad_metrics(db=None, days_back=14)

    assert captured["since_date"] == date.today() - timedelta(days=14)
    # until_date left to the sync's own default (today), not pinned here.
    assert captured["until_date"] is None


def test_per_account_failures_are_logged_not_swallowed(monkeypatch, caplog):
    _patch_sync(monkeypatch, result={
        "accounts": 2, "rows_written": 0,
        "errors": ["Meander Taipei: fetch insights: rate limit"],
    })

    with caplog.at_level(logging.ERROR):
        internal_tasks._do_sync_daily_ad_metrics(db=None, days_back=7)

    assert "Meander Taipei" in caplog.text
    assert "rate limit" in caplog.text


def test_clean_run_logs_no_error(monkeypatch, caplog):
    _patch_sync(monkeypatch)

    with caplog.at_level(logging.ERROR):
        internal_tasks._do_sync_daily_ad_metrics(db=None, days_back=7)

    assert "[ad-daily-cron]" not in caplog.text


def test_endpoint_rejects_out_of_range_days_back(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_TASK_SECRET", "test-secret")
    headers = {"X-Internal-Secret": "test-secret"}

    for bad in (0, -1, 366):
        r = client.post(
            f"/api/internal/tasks/sync-daily-ad-metrics?days_back={bad}", headers=headers
        )
        assert r.status_code == 400, bad
        assert "days_back" in r.json()["detail"]


def test_endpoint_requires_the_secret(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_TASK_SECRET", "test-secret")

    assert client.post("/api/internal/tasks/sync-daily-ad-metrics").status_code == 401
    assert client.post(
        "/api/internal/tasks/sync-daily-ad-metrics",
        headers={"X-Internal-Secret": "wrong"},
    ).status_code == 401


def test_endpoint_reports_the_window_it_started(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_TASK_SECRET", "test-secret")
    started: dict = {}
    monkeypatch.setattr(
        internal_tasks, "_run_in_thread",
        lambda target, label, **kw: started.update({"label": label, **kw}),
    )

    r = client.post(
        "/api/internal/tasks/sync-daily-ad-metrics?days_back=21",
        headers={"X-Internal-Secret": "test-secret"},
    )

    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "started"
    assert data["days_back"] == 21
    assert data["since"] == (date.today() - timedelta(days=21)).isoformat()
    assert started["label"] == "sync-daily-ad-metrics"
    assert started["days_back"] == 21
