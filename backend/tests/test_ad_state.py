"""Tests for the ad Status / Preview columns — the fields ride along on the
existing platform ad sync, and several ads sharing one name fold into one row.

Covers:
  - meta_client.fetch_ads maps effective_status + preview_shareable_link
  - the fold: any ACTIVE ad makes the row active, and the link prefers it
  - pre-migration rows (effective_status NULL) fall back to `status`
"""
from __future__ import annotations

from types import SimpleNamespace

from app.services import meta_client
from app.services.ad_state import NO_AD_STATE, summarize_states


def _ad(status=None, effective_status=None, preview_url=None):
    return SimpleNamespace(
        status=status, effective_status=effective_status, preview_url=preview_url
    )


class TestFetchAdsMapping:
    def test_maps_effective_status_and_preview(self, monkeypatch):
        raw = {
            "id": "a1", "adset_id": "s1", "campaign_id": "c1", "name": "Ad One",
            "status": "ACTIVE",
            # The ad is on but its ad set is not — only effective_status says so.
            "effective_status": "ADSET_PAUSED",
            "preview_shareable_link": "https://fb.com/p/a1",
            "creative": {"id": "cr1"},
        }

        class _FBAccount:
            def __init__(self, *a, **k):
                pass

            def get_ads(self, fields=None, **k):
                assert "effective_status" in fields
                assert "preview_shareable_link" in fields
                return [raw]

        monkeypatch.setattr(meta_client, "_init_api", lambda *a, **k: None)
        monkeypatch.setattr(meta_client, "AdAccount", _FBAccount)

        rows = meta_client.fetch_ads("act_1", "tok")
        assert rows[0]["status"] == "ACTIVE"
        assert rows[0]["effective_status"] == "ADSET_PAUSED"
        assert rows[0]["preview_url"] == "https://fb.com/p/a1"

    def test_missing_fields_do_not_break_the_sync(self, monkeypatch):
        # Meta omits preview_shareable_link on some ad types; the whole platform
        # sync must not blow up over an optional field.
        raw = {
            "id": "a1", "adset_id": "s1", "campaign_id": "c1", "name": "Ad One",
            "status": "PAUSED", "creative": None,
        }

        class _FBAccount:
            def __init__(self, *a, **k):
                pass

            def get_ads(self, **k):
                return [raw]

        monkeypatch.setattr(meta_client, "_init_api", lambda *a, **k: None)
        monkeypatch.setattr(meta_client, "AdAccount", _FBAccount)

        rows = meta_client.fetch_ads("act_1", "tok")
        assert rows[0]["effective_status"] is None
        assert rows[0]["preview_url"] is None
        assert rows[0]["creative_id"] is None


class TestSummarizeStates:
    def test_no_ads_is_unknown(self):
        assert summarize_states([]) == NO_AD_STATE

    def test_any_active_ad_makes_the_row_active(self):
        out = summarize_states([
            _ad(effective_status="PAUSED", preview_url="https://p/1"),
            _ad(effective_status="ACTIVE", preview_url="https://p/2"),
            _ad(effective_status="ADSET_PAUSED"),
        ])
        assert out["effective_status"] == "ACTIVE"
        assert out["active_count"] == 1
        assert out["state_count"] == 3
        # Links the ad that is actually running, not just the first with a URL.
        assert out["preview_url"] == "https://p/2"

    def test_all_off_reports_the_most_common_reason(self):
        out = summarize_states([
            _ad(effective_status="ADSET_PAUSED"),
            _ad(effective_status="ADSET_PAUSED"),
            _ad(effective_status="PAUSED", preview_url="https://p/3"),
        ])
        assert out["effective_status"] == "ADSET_PAUSED"
        assert out["active_count"] == 0
        # No live ad to prefer — fall back to any link we have.
        assert out["preview_url"] == "https://p/3"

    def test_falls_back_to_status_before_the_backfill(self):
        # Rows synced before migration 070 have effective_status NULL. Reading
        # them as "unknown" would blank the column for every branch until the
        # next platform sync.
        out = summarize_states([_ad(status="ACTIVE"), _ad(status="PAUSED")])
        assert out["effective_status"] == "ACTIVE"
        assert out["active_count"] == 1
        assert out["state_count"] == 2
