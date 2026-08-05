"""Tests for apply_ad_renames — following a Meta ad rename in the creative library.

ad_name is the creative library's identity key (combo_metrics_sync and
material_url_sync both look combos up by name), so a rename on Meta's side used
to fork the combo: the old row froze with stale metrics and a new row appeared
with no verdict/angle/hypothesis history. Coverage:
  - a complete, unambiguous rename moves the combo in place
  - the material description and Winning-by-Month rows follow
  - partial renames (old name still in use) are left alone
  - splits, merges, and name clashes are skipped rather than guessed at
"""
from __future__ import annotations

import uuid
from datetime import date

import app.models  # noqa: F401 — register every table before create_all
from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_material import AdMaterial
from app.models.winning_ad_month import WinningAdMonth
from app.services import creative_sync as mod
from tests.db import TestSession

OLD = "[Video] KOL_oldname"
NEW = "[Video] KOL_newname"


def _seed(db, ad_name: str = OLD) -> tuple[AdAccount, AdCombo]:
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id="act_123",
        account_name="Oani", currency="TWD",
        access_token_enc="tok", is_active=True,
    )
    db.add(acc)
    material = AdMaterial(
        id=str(uuid.uuid4()), material_id="MAT-001", branch_id=acc.id,
        material_type="video", file_url="https://cdn/x.jpg", description=ad_name,
        url_source="auto",
    )
    db.add(material)
    combo = AdCombo(
        id=str(uuid.uuid4()), combo_id="CMB-001", branch_id=acc.id,
        ad_name=ad_name, copy_id="CPY-001", material_id="MAT-001",
        verdict="WIN", verdict_source="manual",
    )
    db.add(combo)
    db.commit()
    return acc, combo


def test_complete_rename_moves_combo_in_place():
    db = TestSession()
    acc, combo = _seed(db)
    combo_pk = combo.id

    summary = mod.apply_ad_renames(db, acc, {(OLD, NEW)}, names_seen={NEW})
    db.commit()
    db.refresh(combo)

    assert summary["combos_renamed"] == 1
    assert combo.ad_name == NEW
    assert combo.id == combo_pk  # same row — verdict/angle/links survive
    assert combo.verdict == "WIN"

    material = db.query(AdMaterial).filter(AdMaterial.material_id == "MAT-001").first()
    assert material.description == NEW
    db.close()


def test_winning_month_rows_follow_the_rename():
    db = TestSession()
    acc, _ = _seed(db)
    db.add(WinningAdMonth(
        id=str(uuid.uuid4()), account_id=acc.id, month=date(2026, 5, 1),
        ad_name=OLD, combo_id="CMB-001",
    ))
    db.commit()

    mod.apply_ad_renames(db, acc, {(OLD, NEW)}, names_seen={NEW})
    db.commit()

    rows = db.query(WinningAdMonth).filter(WinningAdMonth.account_id == acc.id).all()
    assert [r.ad_name for r in rows] == [NEW]
    db.close()


def test_winning_month_collision_is_left_alone():
    """A month that already has a row under the new name would violate
    uq_winning_ad_month — leave that row on the old name."""
    db = TestSession()
    acc, _ = _seed(db)
    db.add(WinningAdMonth(
        id=str(uuid.uuid4()), account_id=acc.id, month=date(2026, 5, 1),
        ad_name=OLD, combo_id="CMB-001",
    ))
    db.add(WinningAdMonth(
        id=str(uuid.uuid4()), account_id=acc.id, month=date(2026, 5, 1),
        ad_name=NEW, combo_id=None,
    ))
    db.commit()

    mod.apply_ad_renames(db, acc, {(OLD, NEW)}, names_seen={NEW})
    db.commit()

    names = sorted(
        r.ad_name for r in db.query(WinningAdMonth).filter(
            WinningAdMonth.month == date(2026, 5, 1)
        ).all()
    )
    assert names == sorted([OLD, NEW])
    db.close()


def test_partial_rename_is_skipped():
    """Another ad still carries the old name — two distinct creative groups now
    exist, so the new name must get its own combo from the normal sync path."""
    db = TestSession()
    acc, combo = _seed(db)

    summary = mod.apply_ad_renames(db, acc, {(OLD, NEW)}, names_seen={OLD, NEW})
    db.commit()
    db.refresh(combo)

    assert summary["combos_renamed"] == 0
    assert summary["renames_skipped"] == 1
    assert combo.ad_name == OLD
    db.close()


def test_split_rename_is_skipped():
    db = TestSession()
    acc, combo = _seed(db)

    summary = mod.apply_ad_renames(
        db, acc, {(OLD, NEW), (OLD, NEW + "_b")}, names_seen={NEW, NEW + "_b"},
    )
    db.commit()
    db.refresh(combo)

    assert summary["combos_renamed"] == 0
    assert combo.ad_name == OLD
    db.close()


def test_merge_rename_is_skipped():
    db = TestSession()
    acc, combo = _seed(db)

    summary = mod.apply_ad_renames(
        db, acc, {(OLD, NEW), ("[Video] KOL_other", NEW)}, names_seen={NEW},
    )
    db.commit()
    db.refresh(combo)

    assert summary["combos_renamed"] == 0
    assert combo.ad_name == OLD
    db.close()


def test_clash_with_existing_combo_is_skipped():
    db = TestSession()
    acc, combo = _seed(db)
    db.add(AdCombo(
        id=str(uuid.uuid4()), combo_id="CMB-002", branch_id=acc.id,
        ad_name=NEW, copy_id="CPY-002", material_id="MAT-002",
    ))
    db.commit()

    summary = mod.apply_ad_renames(db, acc, {(OLD, NEW)}, names_seen={NEW})
    db.commit()
    db.refresh(combo)

    assert summary["combos_renamed"] == 0
    assert summary["renames_skipped"] == 1
    assert combo.ad_name == OLD
    db.close()


def test_no_renames_is_a_noop():
    db = TestSession()
    acc, combo = _seed(db)

    summary = mod.apply_ad_renames(db, acc, set(), names_seen={OLD})

    assert summary == {"combos_renamed": 0, "renames_skipped": 0}
    assert combo.ad_name == OLD
    db.close()


def test_hand_edited_material_description_is_preserved():
    db = TestSession()
    acc, combo = _seed(db)
    material = db.query(AdMaterial).filter(AdMaterial.material_id == "MAT-001").first()
    material.description = "Hand-written note about this creative"
    db.commit()

    mod.apply_ad_renames(db, acc, {(OLD, NEW)}, names_seen={NEW})
    db.commit()
    db.refresh(combo)
    db.refresh(material)

    assert combo.ad_name == NEW
    assert material.description == "Hand-written note about this creative"
    db.close()
