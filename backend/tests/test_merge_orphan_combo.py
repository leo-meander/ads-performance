"""Tests for creative_sync.merge_orphan_combo — consolidating an orphaned combo
(no matching live Meta ad, per diagnose_orphan_combos) into its live twin.

Coverage:
  - dry_run (default) computes the plan and touches nothing
  - apply moves hypothesis_combo_links, direct creative_hypotheses.combo_id,
    winning_ad_months.combo_id, and figma_jobs.source_combo_id, then deletes
    the orphan row
  - a duplicate hypothesis_combo_link (target already linked to that
    hypothesis) is dropped rather than violating uq_hypothesis_combo
  - multiple twins (a split, not a simple rename) picks the higher-spend one
    and leaves the runner-up completely untouched
  - no twin at all is an error, not a guess
"""
from __future__ import annotations

import uuid

import app.models  # noqa: F401 — register every table before create_all
from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_material import AdMaterial
from app.models.creative_hypothesis import CreativeHypothesis
from app.models.figma import FigmaJob, FigmaTemplate
from app.models.hypothesis_combo_link import HypothesisComboLink
from app.models.winning_ad_month import WinningAdMonth
from app.services import creative_sync as mod
from tests.db import TestSession
from datetime import date


SHARED_URL = "https://cdn/shared-creative.jpg"


def _account(db) -> AdAccount:
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id="act_123",
        account_name="Oani", currency="TWD",
        access_token_enc="tok", is_active=True,
    )
    db.add(acc)
    return acc


def _combo(db, acc, combo_id: str, ad_name: str, spend, file_url=SHARED_URL, verdict="WIN") -> AdCombo:
    material = AdMaterial(
        id=str(uuid.uuid4()), material_id=f"MAT-{combo_id}", branch_id=acc.id,
        material_type="video", file_url=file_url, description=ad_name,
        url_source="auto",
    )
    db.add(material)
    combo = AdCombo(
        id=str(uuid.uuid4()), combo_id=combo_id, branch_id=acc.id,
        ad_name=ad_name, copy_id=f"CPY-{combo_id}", material_id=f"MAT-{combo_id}",
        verdict=verdict, verdict_source="auto", spend=spend,
    )
    db.add(combo)
    return combo


def test_dry_run_touches_nothing():
    db = TestSession()
    acc = _account(db)
    orphan = _combo(db, acc, "CMB-124", "KOL_dnvrchoi_locationtips", spend=24962)
    twin = _combo(db, acc, "CMB-137", "KOL_dnvrchoi_v2", spend=5000)
    db.commit()

    plan = mod.merge_orphan_combo(db, "CMB-124", dry_run=True)
    db.commit()

    assert plan["target_combo_id"] == "CMB-137"
    assert plan["dry_run"] is True
    assert "applied" not in plan

    # nothing changed
    assert db.query(AdCombo).filter(AdCombo.combo_id == "CMB-124").first() is not None
    db.close()


def test_apply_moves_links_and_deletes_orphan():
    db = TestSession()
    acc = _account(db)
    orphan = _combo(db, acc, "CMB-124", "KOL_dnvrchoi_locationtips", spend=24962)
    target = _combo(db, acc, "CMB-137", "KOL_dnvrchoi_v2", spend=5000)

    hyp = CreativeHypothesis(
        id=str(uuid.uuid4()), hypothesis_id="HYP-001", branch_name="Meander 1948",
        combo_id="CMB-124", hypothesis="location tips drive bookings",
    )
    db.add(hyp)
    db.add(HypothesisComboLink(hypothesis_id="HYP-001", combo_id="CMB-124"))
    db.add(WinningAdMonth(
        id=str(uuid.uuid4()), account_id=acc.id, month=date(2026, 5, 1),
        ad_name="KOL_dnvrchoi_locationtips", combo_id="CMB-124",
    ))
    tmpl = FigmaTemplate(
        id=str(uuid.uuid4()), name="t", file_key="fk", node_id="n1",
        placeholder_schema={},
    )
    db.add(tmpl)
    db.flush()
    db.add(FigmaJob(id=str(uuid.uuid4()), template_id=tmpl.id, source_combo_id="CMB-124"))
    db.commit()

    result = mod.merge_orphan_combo(db, "CMB-124", dry_run=False)

    assert result["applied"] is True
    assert result["target_combo_id"] == "CMB-137"
    assert result["moved"]["hypothesis_links_moved"] == 1
    assert result["moved"]["direct_hypotheses_repointed"] == 1
    assert result["moved"]["winning_months_repointed"] == 1
    assert result["moved"]["figma_jobs_repointed"] == 1

    assert db.query(AdCombo).filter(AdCombo.combo_id == "CMB-124").first() is None

    link = db.query(HypothesisComboLink).filter(HypothesisComboLink.hypothesis_id == "HYP-001").first()
    assert link.combo_id == "CMB-137"

    hyp2 = db.query(CreativeHypothesis).filter(CreativeHypothesis.hypothesis_id == "HYP-001").first()
    assert hyp2.combo_id == "CMB-137"

    won = db.query(WinningAdMonth).filter(WinningAdMonth.ad_name == "KOL_dnvrchoi_locationtips").first()
    assert won.combo_id == "CMB-137"

    job = db.query(FigmaJob).first()
    assert job.source_combo_id == "CMB-137"
    db.close()


def test_duplicate_hypothesis_link_is_dropped_not_duplicated():
    db = TestSession()
    acc = _account(db)
    _combo(db, acc, "CMB-124", "KOL_old", spend=1000)
    _combo(db, acc, "CMB-137", "KOL_new", spend=5000)

    hyp = CreativeHypothesis(
        id=str(uuid.uuid4()), hypothesis_id="HYP-001", branch_name="Meander 1948",
        hypothesis="test",
    )
    db.add(hyp)
    # Both the orphan AND the target are already linked to the same hypothesis.
    db.add(HypothesisComboLink(hypothesis_id="HYP-001", combo_id="CMB-124"))
    db.add(HypothesisComboLink(hypothesis_id="HYP-001", combo_id="CMB-137"))
    db.commit()

    result = mod.merge_orphan_combo(db, "CMB-124", dry_run=False)

    assert result["moved"]["hypothesis_links_dropped_duplicate"] == 1
    assert result["moved"]["hypothesis_links_moved"] == 0

    links = db.query(HypothesisComboLink).filter(HypothesisComboLink.hypothesis_id == "HYP-001").all()
    assert len(links) == 1
    assert links[0].combo_id == "CMB-137"
    db.close()


def test_multiple_twins_picks_higher_spend_and_leaves_runner_up_alone():
    db = TestSession()
    acc = _account(db)
    orphan = _combo(db, acc, "CMB-124", "KOL_dnvrchoi_locationtips", spend=24962)
    weak_twin = _combo(db, acc, "CMB-142", "KOL_dnvrchoi_b", spend=1000)
    strong_twin = _combo(db, acc, "CMB-137", "KOL_dnvrchoi_a", spend=9000)
    db.commit()

    result = mod.merge_orphan_combo(db, "CMB-124", dry_run=False)

    assert result["target_combo_id"] == "CMB-137"
    assert result["declined_twins"] == ["CMB-142"]

    # runner-up untouched
    still_there = db.query(AdCombo).filter(AdCombo.combo_id == "CMB-142").first()
    assert still_there is not None
    assert float(still_there.spend) == 1000
    db.close()


def test_no_twin_is_an_error_not_a_guess():
    db = TestSession()
    acc = _account(db)
    _combo(db, acc, "CMB-999", "Lonely ad", spend=100, file_url="https://cdn/unique.jpg")
    db.commit()

    result = mod.merge_orphan_combo(db, "CMB-999", dry_run=True)

    assert "error" in result
    assert db.query(AdCombo).filter(AdCombo.combo_id == "CMB-999").first() is not None
    db.close()


def test_unknown_combo_is_an_error():
    db = TestSession()
    _account(db)
    db.commit()

    result = mod.merge_orphan_combo(db, "CMB-DOES-NOT-EXIST", dry_run=True)
    assert "error" in result
    db.close()
