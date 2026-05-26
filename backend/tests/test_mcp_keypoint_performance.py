"""Tests for the MCP get_keypoint_performance tool.

The tool aggregates combo metrics per keypoint. Because a combo carries a JSON
array of keypoint ids, the handler expands that array in Python — and must cope
with the array arriving either as a parsed list (Postgres/psycopg2) or as a raw
JSON string (other drivers, incl. SQLite under a raw text() query). These tests
lock in both the expansion math and that coercion.

The sibling get_angle_performance tool is Postgres-only SQL (::float / ROUND::
numeric / ILIKE) and is not exercisable on SQLite, so it is intentionally not
covered here.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register every table before create_all
from app.mcp.tools import _get_keypoint_performance
from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.base import Base
from app.models.keypoint import BranchKeypoint

engine = create_engine(
    "sqlite:///test_mcp_keypoint.db",
    connect_args={"check_same_thread": False},
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def seeded(db):
    """One branch, two keypoints (location + value), four combos.

    CMB-1 carries both keypoints; CMB-3 carries the value keypoint plus a ghost
    id that has no branch_keypoints row; CMB-4 has an empty array (contributes
    to nothing).
    """
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id="act_1",
        account_name="Meander Saigon", is_active=True,
    )
    db.add(acc)
    db.flush()
    bid = acc.id

    kp_loc = BranchKeypoint(id=str(uuid.uuid4()), branch_id=bid, category="location", title="Riverside view", is_active=True)
    kp_val = BranchKeypoint(id=str(uuid.uuid4()), branch_id=bid, category="value", title="Free breakfast", is_active=True)
    db.add_all([kp_loc, kp_val])
    db.flush()
    ghost = str(uuid.uuid4())  # referenced but never created -> "(deleted keypoint)"

    def combo(n, kps, spend, rev, ta="Solo", country="VN"):
        db.add(AdCopy(copy_id=f"CPY-{n}", branch_id=bid, target_audience=ta, headline="h", body_text="b", cta="Book", language="en"))
        db.add(AdMaterial(branch_id=bid, material_id=f"MAT-{n}", material_type="image", file_url=f"https://x/{n}.jpg", url_source="auto"))
        db.add(AdCombo(
            id=str(uuid.uuid4()), combo_id=f"CMB-{n}", branch_id=bid, ad_name=f"Ad {n}",
            target_audience=ta, country=country, copy_id=f"CPY-{n}", material_id=f"MAT-{n}",
            keypoint_ids=kps, spend=spend, revenue=rev, clicks=500, impressions=10000, conversions=10,
        ))

    combo(1, [kp_loc.id, kp_val.id], 100, 500)
    combo(2, [kp_loc.id], 100, 100)
    combo(3, [kp_val.id, ghost], 50, 300)
    combo(4, [], 999, 999)
    db.commit()
    return {"branch_id": bid, "ghost": ghost}


def _by_title(res):
    return {r["title"]: r for r in res["keypoints"]}


def test_aggregates_across_combos_and_keypoints(db, seeded):
    res = _get_keypoint_performance({}, db)
    rows = _by_title(res)

    # location: CMB-1 (100/500) + CMB-2 (100/100) = spend 200, rev 600
    assert rows["Riverside view"]["combos"] == 2
    assert rows["Riverside view"]["spend"] == 200
    assert rows["Riverside view"]["revenue"] == 600
    assert rows["Riverside view"]["roas"] == 3.0
    assert rows["Riverside view"]["category"] == "location"

    # value: CMB-1 (100/500) + CMB-3 (50/300) = spend 150, rev 800
    assert rows["Free breakfast"]["combos"] == 2
    assert rows["Free breakfast"]["spend"] == 150
    assert rows["Free breakfast"]["roas"] == 5.33


def test_empty_array_contributes_nothing(db, seeded):
    res = _get_keypoint_performance({}, db)
    # CMB-4's 999 spend must not appear under any keypoint.
    assert all(r["spend"] != 999 for r in res["keypoints"])


def test_deleted_keypoint_surfaced(db, seeded):
    res = _get_keypoint_performance({}, db)
    rows = _by_title(res)
    assert rows["(deleted keypoint)"]["combos"] == 1
    assert rows["(deleted keypoint)"]["spend"] == 50


def test_sorted_by_roas_desc(db, seeded):
    res = _get_keypoint_performance({}, db)
    roas = [r["roas"] for r in res["keypoints"]]
    assert roas == sorted(roas, reverse=True)


def test_category_filter(db, seeded):
    res = _get_keypoint_performance({"category": "value"}, db)
    assert {r["title"] for r in res["keypoints"]} == {"Free breakfast"}


def test_country_filter_excludes_all(db, seeded):
    res = _get_keypoint_performance({"country": "JP"}, db)
    assert res["keypoints"] == []


def test_target_audience_filter(db, seeded):
    res = _get_keypoint_performance({"target_audience": "Solo"}, db)
    # all seeded combos are Solo -> all three keypoints present
    assert len(res["keypoints"]) == 3


def test_raw_json_string_is_coerced(db, seeded):
    """Under SQLite a raw text() query returns keypoint_ids as a JSON string,
    not a list. The handler must still expand it — proves the json.loads
    fallback path, which is what protects non-psycopg2 drivers."""
    from sqlalchemy import text

    raw = db.execute(
        text("SELECT keypoint_ids FROM ad_combos WHERE combo_id = 'CMB-1'")
    ).scalar()
    assert isinstance(raw, str)  # guard: SQLite really does hand back a string

    res = _get_keypoint_performance({}, db)
    # If coercion failed, no keypoint would aggregate any spend.
    assert any(r["spend"] > 0 for r in res["keypoints"])
