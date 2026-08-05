"""Tests for creative_sync.find_duplicate_named_combos / merge_duplicate_combo.

ad_combos has no unique constraint on (branch_id, ad_name), and the
application-level dedupe in sync_creative_library_for_account (a dict lookup
before insert) isn't atomic — a race (overlapping sync runs, or a manual
"+ New Combo" landing mid-lookup) can leave two combos under the identical
ad_name, splitting metrics/history across them. Coverage:
  - a genuine duplicate pair is found; distinct-name combos are not
  - merge picks the higher-spend combo as the keeper regardless of arg order
  - combos with different ad_name (or branch) are rejected, not guessed at
  - the FK-repoint/delete behavior is shared with merge_orphan_combo (already
    covered in test_merge_orphan_combo.py), so this file only checks the
    duplicate-specific wiring: discovery + target selection + validation
"""
from __future__ import annotations

import uuid

import app.models  # noqa: F401 — register every table before create_all
from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_material import AdMaterial
from app.services import creative_sync as mod
from tests.db import TestSession

SAME_NAME = "[Video] AI_F Social Vibe-Experience"


def _account(db) -> AdAccount:
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id="act_123",
        account_name="Meander Taipei", currency="TWD",
        access_token_enc="tok", is_active=True,
    )
    db.add(acc)
    return acc


def _combo(db, acc, combo_id: str, ad_name: str, spend, country=None) -> AdCombo:
    material = AdMaterial(
        id=str(uuid.uuid4()), material_id=f"MAT-{combo_id}", branch_id=acc.id,
        material_type="video", file_url=f"https://cdn/{combo_id}.jpg",
        description=ad_name, url_source="auto",
    )
    db.add(material)
    combo = AdCombo(
        id=str(uuid.uuid4()), combo_id=combo_id, branch_id=acc.id,
        ad_name=ad_name, copy_id=f"CPY-{combo_id}", material_id=f"MAT-{combo_id}",
        verdict="TEST", verdict_source="auto", spend=spend, country=country,
    )
    db.add(combo)
    return combo


def test_find_reports_duplicate_pair():
    db = TestSession()
    acc = _account(db)
    _combo(db, acc, "CMB-207", SAME_NAME, spend=9642, country="TW")
    _combo(db, acc, "CMB-197", SAME_NAME, spend=9839, country="PH")
    _combo(db, acc, "CMB-999", "Unrelated ad", spend=100)
    db.commit()

    groups = mod.find_duplicate_named_combos(db)

    assert len(groups) == 1
    assert groups[0]["ad_name"] == SAME_NAME
    assert groups[0]["account_name"] == "Meander Taipei"
    ids = {c["combo_id"] for c in groups[0]["combos"]}
    assert ids == {"CMB-207", "CMB-197"}
    db.close()


def test_find_ignores_distinct_names():
    db = TestSession()
    acc = _account(db)
    _combo(db, acc, "CMB-1", "Ad A", spend=100)
    _combo(db, acc, "CMB-2", "Ad B", spend=200)
    db.commit()

    groups = mod.find_duplicate_named_combos(db)
    assert groups == []
    db.close()


def test_merge_keeps_higher_spend_regardless_of_arg_order():
    db = TestSession()
    acc = _account(db)
    _combo(db, acc, "CMB-207", SAME_NAME, spend=9642, country="TW")
    _combo(db, acc, "CMB-197", SAME_NAME, spend=9839, country="PH")
    db.commit()

    result = mod.merge_duplicate_combo(db, "CMB-207", "CMB-197", dry_run=False)

    assert result["applied"] is True
    assert result["target_combo_id"] == "CMB-197"  # higher spend kept
    assert result["source_combo_id"] == "CMB-207"
    assert db.query(AdCombo).filter(AdCombo.combo_id == "CMB-207").first() is None
    assert db.query(AdCombo).filter(AdCombo.combo_id == "CMB-197").first() is not None
    db.close()


def test_merge_arg_order_reversed_still_keeps_higher_spend():
    db = TestSession()
    acc = _account(db)
    _combo(db, acc, "CMB-207", SAME_NAME, spend=9642)
    _combo(db, acc, "CMB-197", SAME_NAME, spend=9839)
    db.commit()

    # Pass the higher-spend combo_id first this time.
    result = mod.merge_duplicate_combo(db, "CMB-197", "CMB-207", dry_run=True)

    assert result["target_combo_id"] == "CMB-197"
    assert result["source_combo_id"] == "CMB-207"
    db.close()


def test_different_ad_name_is_rejected():
    db = TestSession()
    acc = _account(db)
    _combo(db, acc, "CMB-1", "Ad A", spend=100)
    _combo(db, acc, "CMB-2", "Ad B", spend=200)
    db.commit()

    result = mod.merge_duplicate_combo(db, "CMB-1", "CMB-2", dry_run=True)

    assert "error" in result
    assert db.query(AdCombo).filter(AdCombo.combo_id == "CMB-1").first() is not None
    assert db.query(AdCombo).filter(AdCombo.combo_id == "CMB-2").first() is not None
    db.close()


def test_unknown_combo_is_rejected():
    db = TestSession()
    acc = _account(db)
    _combo(db, acc, "CMB-1", "Ad A", spend=100)
    db.commit()

    result = mod.merge_duplicate_combo(db, "CMB-1", "CMB-DOES-NOT-EXIST", dry_run=True)
    assert "error" in result
    db.close()
