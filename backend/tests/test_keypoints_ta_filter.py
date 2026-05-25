"""Tests for the target_audience filter on GET /api/keypoints.

The endpoint aggregates combo metrics per keypoint. When target_audience is
set, only that audience's combos feed the metrics + verdict, so the same
keypoint can read WIN for one audience and LOSE for another. The benchmark
ROAS stays branch-wide (a stable cross-audience bar).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register every table before create_all
from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.base import Base
from app.models.keypoint import BranchKeypoint
from app.models.user import User
from app.routers.creative import keypoint_facets, list_keypoints


engine = create_engine(
    "sqlite:///test_keypoints_ta.db",
    connect_args={"check_same_thread": False},
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _admin() -> User:
    return User(
        id=str(uuid.uuid4()), email="a@x.com", full_name="Admin",
        password_hash="x", roles=["admin"], is_active=True,
    )


def _combo(branch_id: str, n: int, ta: str, kp_id: str, spend: float, revenue: float, country: str = "VN") -> AdCombo:
    db = TestSession()
    db.add(AdCopy(
        copy_id=f"CPY-{n}", branch_id=branch_id, target_audience=ta,
        headline="h", body_text="b", cta="Book", language="en",
    ))
    db.add(AdMaterial(
        branch_id=branch_id, material_id=f"MAT-{n}", material_type="image",
        file_url=f"https://x/{n}.jpg", url_source="auto",
    ))
    combo = AdCombo(
        id=str(uuid.uuid4()), combo_id=f"CMB-{n}", branch_id=branch_id,
        ad_name=f"Ad {n}", target_audience=ta, country=country,
        copy_id=f"CPY-{n}", material_id=f"MAT-{n}", keypoint_ids=[kp_id],
        spend=spend, revenue=revenue, clicks=5000, impressions=100000,
        conversions=10,
    )
    db.add(combo)
    db.commit()
    db.close()


def _seed():
    """One branch, one keypoint, two combos on it: a strong Solo combo and a
    weak Couple combo. Branch benchmark = 550/200 = 2.75x."""
    db = TestSession()
    account = AdAccount(
        id=str(uuid.uuid4()), platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Saigon", currency="VND",
    )
    db.add(account)
    db.flush()
    kp = BranchKeypoint(branch_id=account.id, category="amenity", title="Free breakfast")
    db.add(kp)
    db.commit()
    branch_id, kp_id = account.id, kp.id
    db.close()

    _combo(branch_id, 1, "Solo", kp_id, spend=100, revenue=500)    # roas 5.0 → WIN
    _combo(branch_id, 2, "Couple", kp_id, spend=100, revenue=50)   # roas 0.5 → LOSE
    return branch_id, kp_id


def _only(data: list, kp_id: str) -> dict:
    return next(r for r in data if r["id"] == kp_id)


def test_no_ta_filter_aggregates_all_audiences():
    branch_id, kp_id = _seed()
    db = TestSession()
    resp = list_keypoints(current_user=_admin(), db=db)
    kp = _only(resp["data"], kp_id)
    assert kp["combos"] == 2
    assert kp["roas"] == pytest.approx(2.75)  # 550 / 200
    assert kp["verdict"] == "WIN"  # 2.75 >= benchmark 2.75
    db.close()


def test_ta_filter_scopes_metrics_to_that_audience():
    branch_id, kp_id = _seed()
    db = TestSession()

    solo = _only(list_keypoints(target_audience="Solo", current_user=_admin(), db=db)["data"], kp_id)
    assert solo["combos"] == 1
    assert solo["roas"] == pytest.approx(5.0)
    assert solo["conversions"] == 10
    assert solo["verdict"] == "WIN"  # 5.0 >= branch benchmark 2.75
    # Benchmark stays branch-wide, not the Solo-only ROAS.
    assert solo["benchmark_roas"] == pytest.approx(2.75)

    couple = _only(list_keypoints(target_audience="Couple", current_user=_admin(), db=db)["data"], kp_id)
    assert couple["combos"] == 1
    assert couple["roas"] == pytest.approx(0.5)
    assert couple["verdict"] == "LOSE"  # 0.5 < 2.75 → same keypoint loses for Couple
    db.close()


def test_ta_with_no_combos_shows_keypoint_with_zero_metrics():
    branch_id, kp_id = _seed()
    db = TestSession()
    resp = list_keypoints(target_audience="Business", current_user=_admin(), db=db)
    kp = _only(resp["data"], kp_id)
    assert kp["combos"] == 0
    assert kp["verdict"] == "TEST"  # no data for this audience
    db.close()


def _seed_countries():
    """One branch + keypoint, two Solo combos in different countries:
    a strong JP combo and a weak PH combo. Branch benchmark = 550/200 = 2.75x."""
    db = TestSession()
    account = AdAccount(
        id=str(uuid.uuid4()), platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Saigon", currency="VND",
    )
    db.add(account)
    db.flush()
    kp = BranchKeypoint(branch_id=account.id, category="amenity", title="Free breakfast")
    db.add(kp)
    db.commit()
    branch_id, kp_id = account.id, kp.id
    db.close()

    _combo(branch_id, 1, "Solo", kp_id, spend=100, revenue=500, country="JP")  # roas 5.0
    _combo(branch_id, 2, "Solo", kp_id, spend=100, revenue=50, country="PH")   # roas 0.5
    return branch_id, kp_id


def test_country_filter_scopes_metrics_to_that_country():
    branch_id, kp_id = _seed_countries()
    db = TestSession()

    jp = _only(list_keypoints(country="JP", current_user=_admin(), db=db)["data"], kp_id)
    assert jp["combos"] == 1
    assert jp["roas"] == pytest.approx(5.0)
    assert jp["verdict"] == "WIN"  # 5.0 >= branch benchmark 2.75

    ph = _only(list_keypoints(country="PH", current_user=_admin(), db=db)["data"], kp_id)
    assert ph["combos"] == 1
    assert ph["roas"] == pytest.approx(0.5)
    assert ph["verdict"] == "LOSE"  # same keypoint loses for PH traffic
    db.close()


def test_ta_and_country_combine_as_and():
    branch_id, kp_id = _seed_countries()  # both combos are Solo
    db = TestSession()
    # Solo + JP narrows to the single JP combo
    kp = _only(list_keypoints(target_audience="Solo", country="JP", current_user=_admin(), db=db)["data"], kp_id)
    assert kp["combos"] == 1
    assert kp["roas"] == pytest.approx(5.0)
    # Solo + PH narrows to the single PH combo
    kp = _only(list_keypoints(target_audience="Solo", country="PH", current_user=_admin(), db=db)["data"], kp_id)
    assert kp["combos"] == 1
    assert kp["roas"] == pytest.approx(0.5)
    # Couple + JP → no combos match both
    kp = _only(list_keypoints(target_audience="Couple", country="JP", current_user=_admin(), db=db)["data"], kp_id)
    assert kp["combos"] == 0
    db.close()


def test_facets_returns_distinct_countries():
    branch_id, kp_id = _seed_countries()
    db = TestSession()
    resp = keypoint_facets(current_user=_admin(), db=db)
    assert resp["success"] is True
    assert resp["data"]["countries"] == ["JP", "PH"]  # sorted, distinct
    db.close()


def test_facets_lists_countries_even_without_keypoint_assignment():
    """The country dropdown must populate from all combos on the branch, not
    only keypoint-tagged ones — otherwise it stays empty until combos are
    tagged and the filter looks broken."""
    db = TestSession()
    account = AdAccount(
        id=str(uuid.uuid4()), platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Oani", currency="TWD",
    )
    db.add(account)
    db.flush()
    db.add(AdCopy(
        copy_id="CPY-X", branch_id=account.id, target_audience="Couple",
        headline="h", body_text="b", cta="Book", language="en",
    ))
    db.add(AdMaterial(
        branch_id=account.id, material_id="MAT-X", material_type="image",
        file_url="https://x/x.jpg", url_source="auto",
    ))
    db.add(AdCombo(  # country set, but NO keypoint_ids
        id=str(uuid.uuid4()), combo_id="CMB-X", branch_id=account.id,
        ad_name="Ad X", target_audience="Couple", country="TW",
        copy_id="CPY-X", material_id="MAT-X", keypoint_ids=None,
    ))
    db.commit()

    resp = keypoint_facets(current_user=_admin(), db=db)
    assert resp["data"]["countries"] == ["TW"]
    db.close()
