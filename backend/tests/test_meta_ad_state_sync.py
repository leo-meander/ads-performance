"""Tests for meta_ad_state_sync — the per-ad status + preview-link pull.

Meta's get_ads is mocked. Coverage:
  - status / effective_status / preview_shareable_link land on meta_ad_states
  - re-running replaces rather than duplicates (delete-then-insert)
  - a failing Meta call leaves the existing rows alone (no half-wipe)
  - non-Meta accounts are a no-op
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import app.models  # noqa: F401 — register every table before create_all
from app.models.account import AdAccount
from app.models.meta_ad_state import MetaAdState
from app.services import meta_ad_state_sync as mod
from tests.db import TestSession


def _fake_fb(rows, raises=False):
    class _FB:
        def __init__(self, *a, **k):
            pass

        def get_ads(self, **kwargs):
            if raises:
                raise RuntimeError("token expired")
            return rows

    return _FB


def _patch_meta(monkeypatch, rows, raises=False):
    monkeypatch.setattr(mod, "FacebookAdsApi", SimpleNamespace(init=lambda **k: None))
    monkeypatch.setattr(mod, "FBAdAccount", _fake_fb(rows, raises=raises))


def _seed_account(db, platform="meta") -> AdAccount:
    acc = AdAccount(
        id=str(uuid.uuid4()), platform=platform, account_id="act_123",
        account_name="Saigon", currency="VND",
        access_token_enc="tok", is_active=True,
    )
    db.add(acc)
    db.commit()
    return acc


def _rows():
    return [
        {
            "id": "a1", "name": "Ad One", "status": "ACTIVE",
            "effective_status": "ACTIVE",
            "preview_shareable_link": "https://fb.com/ads/preview/a1",
        },
        {
            "id": "a2", "name": "Ad Two", "status": "ACTIVE",
            # Ad is on, its ad set is not — the case worth naming in the UI.
            "effective_status": "ADSET_PAUSED",
            "preview_shareable_link": "https://fb.com/ads/preview/a2",
        },
        {"id": "a3", "name": "Ad Three", "status": "PAUSED", "effective_status": "PAUSED"},
    ]


def test_stores_status_and_preview(monkeypatch):
    _patch_meta(monkeypatch, _rows())
    db = TestSession()
    acc = _seed_account(db)

    summary = mod.sync_meta_ad_states_for_account(db, acc)
    db.commit()

    assert summary["rows_written"] == 3
    by_id = {s.ad_id: s for s in db.query(MetaAdState).all()}
    assert by_id["a1"].effective_status == "ACTIVE"
    assert by_id["a1"].preview_url == "https://fb.com/ads/preview/a1"
    assert by_id["a2"].status == "ACTIVE"
    assert by_id["a2"].effective_status == "ADSET_PAUSED"
    assert by_id["a3"].preview_url is None
    assert by_id["a3"].ad_name == "Ad Three"
    db.close()


def test_resync_replaces_rather_than_duplicates(monkeypatch):
    _patch_meta(monkeypatch, _rows())
    db = TestSession()
    acc = _seed_account(db)

    mod.sync_meta_ad_states_for_account(db, acc)
    db.commit()

    # Same ad, now paused, and the other two are gone from the account.
    _patch_meta(monkeypatch, [
        {"id": "a1", "name": "Ad One", "status": "PAUSED", "effective_status": "PAUSED"},
    ])
    mod.sync_meta_ad_states_for_account(db, acc)
    db.commit()

    rows = db.query(MetaAdState).all()
    assert len(rows) == 1
    assert rows[0].ad_id == "a1"
    assert rows[0].effective_status == "PAUSED"
    db.close()


def test_failed_fetch_keeps_previous_rows(monkeypatch):
    _patch_meta(monkeypatch, _rows())
    db = TestSession()
    acc = _seed_account(db)
    mod.sync_meta_ad_states_for_account(db, acc)
    db.commit()

    # A dead token must not leave the branch with an empty status column.
    _patch_meta(monkeypatch, [], raises=True)
    summary = mod.sync_meta_ad_states_for_account(db, acc)
    db.commit()

    assert summary["rows_written"] == 0
    assert summary["errors"]
    assert db.query(MetaAdState).count() == 3
    db.close()


def test_non_meta_account_is_noop(monkeypatch):
    _patch_meta(monkeypatch, _rows())
    db = TestSession()
    acc = _seed_account(db, platform="google")

    summary = mod.sync_meta_ad_states_for_account(db, acc)
    assert summary["rows_written"] == 0
    assert db.query(MetaAdState).count() == 0
    db.close()
