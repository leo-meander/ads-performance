"""Tests for AI brief service helpers: per-keypoint ROAS, top creatives, language."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register every table before create_all
from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_material import AdMaterial
from app.models.base import Base
from app.models.keypoint import BranchKeypoint
from app.services.creative_brief_service import (
    _build_user_prompt,
    _gather_patterns,
    _keypoint_performance,
)

engine = create_engine(
    "sqlite:///test_creative_brief.db", connect_args={"check_same_thread": False}
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _account():
    db = TestSession()
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}", account_name="Meander Saigon", currency="VND",
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    db.close()
    return acc


def _keypoint(branch_id, title):
    db = TestSession()
    kp = BranchKeypoint(id=str(uuid.uuid4()), branch_id=branch_id, category="experience", title=title)
    db.add(kp)
    db.commit()
    kid = kp.id
    db.close()
    return kid


def _combo(branch_id, sfx, *, roas=None, spend=0, revenue=0, conversions=0,
           verdict="WIN", ta="Solo", keypoint_ids=None):
    db = TestSession()
    db.add(AdMaterial(
        branch_id=branch_id, material_id=f"MAT-{sfx}",
        material_type="image", file_url=f"https://drive/{sfx}.jpg", url_source="auto",
    ))
    db.add(AdCombo(
        id=str(uuid.uuid4()), combo_id=f"CMB-{sfx}", branch_id=branch_id,
        ad_name=f"Ad {sfx}", target_audience=ta, country="VN",
        copy_id=f"CPY-{sfx}", material_id=f"MAT-{sfx}",
        verdict=verdict, roas=roas, spend=spend, revenue=revenue, conversions=conversions,
        keypoint_ids=keypoint_ids,
    ))
    db.commit()
    db.close()


def test_keypoint_performance_roas():
    acc = _account()
    kid = _keypoint(acc.id, "Indoor slide")
    _combo(acc.id, "1", roas=3.0, spend=100, revenue=300, conversions=5, keypoint_ids=[kid])
    _combo(acc.id, "2", roas=1.0, spend=100, revenue=100, conversions=3, keypoint_ids=[kid])

    db = TestSession()
    perf = _keypoint_performance(db, acc.id, None)
    db.close()

    assert "Indoor slide" in perf
    assert perf["Indoor slide"]["roas"] == 2.0   # (300+100) / (100+100)
    assert perf["Indoor slide"]["combos"] == 2
    assert perf["Indoor slide"]["conversions"] == 8


def test_keypoint_performance_ta_filter():
    acc = _account()
    kid = _keypoint(acc.id, "Rooftop")
    _combo(acc.id, "S", roas=4.0, spend=100, revenue=400, keypoint_ids=[kid], ta="Solo")
    _combo(acc.id, "C", roas=1.0, spend=100, revenue=100, keypoint_ids=[kid], ta="Couple")

    db = TestSession()
    perf = _keypoint_performance(db, acc.id, "Solo")
    db.close()

    assert perf["Rooftop"]["roas"] == 4.0  # only the Solo combo counted
    assert perf["Rooftop"]["combos"] == 1


def test_gather_patterns_top_creatives_sorted_with_links():
    acc = _account()
    _combo(acc.id, "A", roas=2.0, spend=100, revenue=200, verdict="WIN")
    _combo(acc.id, "B", roas=5.0, spend=100, revenue=500, verdict="WIN")
    _combo(acc.id, "C", roas=3.0, spend=100, revenue=300, verdict="WIN")

    db = TestSession()
    pattern = _gather_patterns(
        db, branch_id=acc.id, target_audience=None, country=None,
        vibe=None, performance_goal="roas",
    )
    db.close()

    tops = pattern["top_creatives"]
    assert [t["combo_id"] for t in tops] == ["CMB-B", "CMB-C", "CMB-A"]  # roas desc
    assert tops[0]["roas"] == 5.0
    assert all(t["file_url"] for t in tops)  # creative link attached


def test_build_user_prompt_includes_language():
    prompt = _build_user_prompt(
        branch_name="Meander Saigon", target_audience="Solo", country="VN",
        vibe=None, n_variants=2, language="vi",
        pattern={
            "sample_size": 1, "angle_distribution": {}, "keypoint_distribution": {},
            "visual_distribution": {}, "headline_examples": [],
        },
    )
    assert "Vietnamese" in prompt
