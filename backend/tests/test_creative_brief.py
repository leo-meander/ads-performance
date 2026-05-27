"""Tests for AI brief service helpers: per-keypoint ROAS, top creatives, language."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register every table before create_all
from app.models.account import AdAccount
from app.models.ad_angle import AdAngle
from app.models.ad_combo import AdCombo
from app.models.ad_material import AdMaterial
from app.models.base import Base
from app.models.keypoint import BranchKeypoint
from app.services.creative_brief_service import (
    _angle_performance,
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


def _angle(branch_id, angle_id, angle_type):
    db = TestSession()
    db.add(AdAngle(
        id=str(uuid.uuid4()), branch_id=branch_id, angle_id=angle_id,
        angle_type=angle_type, angle_text="", status="WIN",
    ))
    db.commit()
    db.close()


def _combo(branch_id, sfx, *, roas=None, spend=0, revenue=0, conversions=0,
           verdict="WIN", ta="Solo", keypoint_ids=None, angle_id=None,
           material_type="image", hook_rate=None, thruplay_rate=None):
    db = TestSession()
    db.add(AdMaterial(
        branch_id=branch_id, material_id=f"MAT-{sfx}",
        material_type=material_type, file_url=f"https://drive/{sfx}.jpg", url_source="auto",
    ))
    db.add(AdCombo(
        id=str(uuid.uuid4()), combo_id=f"CMB-{sfx}", branch_id=branch_id,
        ad_name=f"Ad {sfx}", target_audience=ta, country="VN",
        copy_id=f"CPY-{sfx}", material_id=f"MAT-{sfx}",
        verdict=verdict, roas=roas, spend=spend, revenue=revenue, conversions=conversions,
        keypoint_ids=keypoint_ids, angle_id=angle_id,
        hook_rate=hook_rate, thruplay_rate=thruplay_rate,
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


def test_angle_performance_roas():
    acc = _account()
    _angle(acc.id, "ANG-1", "Use an authority")
    _combo(acc.id, "X", roas=3.0, spend=100, revenue=600, conversions=4, angle_id="ANG-1")
    _combo(acc.id, "Y", roas=1.0, spend=100, revenue=200, conversions=2, angle_id="ANG-1")

    db = TestSession()
    perf = _angle_performance(db, acc.id, None)
    db.close()

    assert "Use an authority" in perf
    assert perf["Use an authority"]["roas"] == 4.0  # (600+200) / (100+100)
    assert perf["Use an authority"]["combos"] == 2


def _empty_pattern():
    return {
        "sample_size": 1, "angle_distribution": {}, "keypoint_distribution": {},
        "visual_distribution": {}, "headline_examples": [], "samples": [],
    }


def test_build_user_prompt_includes_language():
    prompt = _build_user_prompt(
        branch_name="Meander Saigon", target_audience="Solo", country="VN",
        vibe=None, n_variants=2, language="vi", ad_format="image",
        pattern=_empty_pattern(),
    )
    assert "Vietnamese" in prompt


def test_build_user_prompt_video_instruction():
    prompt = _build_user_prompt(
        branch_name="Meander Saigon", target_audience="Solo", country="VN",
        vibe=None, n_variants=1, language="en", ad_format="video",
        pattern=_empty_pattern(),
    )
    assert "VIDEO" in prompt and "0-3s hook" in prompt


def test_gather_patterns_format_filter_video():
    acc = _account()
    _combo(acc.id, "IMG", roas=4.0, spend=100, revenue=400, material_type="image")
    _combo(acc.id, "VID", roas=2.0, spend=100, revenue=200, material_type="video", hook_rate=0.35)

    db = TestSession()
    pattern = _gather_patterns(
        db, branch_id=acc.id, target_audience=None, country=None,
        vibe=None, performance_goal="roas", ad_format="video",
    )
    db.close()

    ids = [s["combo_id"] for s in pattern["samples"]]
    assert ids == ["CMB-VID"]  # only the video winner seeds a video brief
    assert pattern["samples"][0]["hook_rate"] == 0.35
