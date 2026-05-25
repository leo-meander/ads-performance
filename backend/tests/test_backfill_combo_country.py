"""Tests for _do_backfill_combo_country — fills AdCombo.country from the
synced Ad -> AdSet link, so the keypoints country filter has data.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register every table before create_all
from app.models.account import AdAccount
from app.models.ad import Ad
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.ad_set import AdSet
from app.models.base import Base
from app.routers.internal_tasks import _do_backfill_combo_country


engine = create_engine(
    "sqlite:///test_backfill_combo_country.db",
    connect_args={"check_same_thread": False},
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_n = 0  # monotonic counter for unique copy/material/combo ids across a test


@pytest.fixture(autouse=True)
def setup_db():
    global _n
    _n = 0
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _branch(db) -> str:
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Saigon", currency="VND",
    )
    db.add(acc)
    db.flush()
    return acc.id


def _ad(db, branch_id: str, ad_name: str, country: str | None):
    """An Ad in an AdSet whose name carries `country`."""
    campaign_id = str(uuid.uuid4())
    adset = AdSet(
        id=str(uuid.uuid4()), campaign_id=campaign_id, account_id=branch_id,
        platform="meta", platform_adset_id=f"as_{uuid.uuid4().hex[:8]}",
        name=f"{country or 'XX'}_Solo_TOF", status="ACTIVE", country=country,
    )
    db.add(adset)
    db.flush()
    db.add(Ad(
        id=str(uuid.uuid4()), ad_set_id=adset.id, campaign_id=campaign_id,
        account_id=branch_id, platform="meta",
        platform_ad_id=f"ad_{uuid.uuid4().hex[:8]}", name=ad_name, status="ACTIVE",
    ))


def _combo(db, branch_id: str, ad_name: str, country: str | None) -> str:
    global _n
    _n += 1
    n = _n
    db.add(AdCopy(
        copy_id=f"CPY-{n}", branch_id=branch_id, target_audience="Solo",
        headline="h", body_text="b", cta="Book", language="en",
    ))
    db.add(AdMaterial(
        branch_id=branch_id, material_id=f"MAT-{n}", material_type="image",
        file_url=f"https://x/{n}.jpg", url_source="auto",
    ))
    combo_id = f"CMB-{n}"
    db.add(AdCombo(
        id=str(uuid.uuid4()), combo_id=combo_id, branch_id=branch_id,
        ad_name=ad_name, target_audience="Solo", country=country,
        copy_id=f"CPY-{n}", material_id=f"MAT-{n}",
    ))
    return combo_id


def _country(db, combo_id: str):
    return db.query(AdCombo).filter(AdCombo.combo_id == combo_id).first().country


def test_backfill_fills_country_from_matching_ad():
    db = TestSession()
    branch = _branch(db)
    _ad(db, branch, "Ad Alpha", "JP")
    cid = _combo(db, branch, "Ad Alpha", None)  # no country yet
    db.commit()

    _do_backfill_combo_country(db)

    assert _country(db, cid) == "JP"
    db.close()


def test_backfill_respects_branch_when_ad_names_collide():
    """Same ad_name in two branches must map to each branch's own country."""
    db = TestSession()
    b1, b2 = _branch(db), _branch(db)
    _ad(db, b1, "Shared Ad", "JP")
    _ad(db, b2, "Shared Ad", "PH")
    c1 = _combo(db, b1, "Shared Ad", None)
    c2 = _combo(db, b2, "Shared Ad", None)
    db.commit()

    _do_backfill_combo_country(db)

    assert _country(db, c1) == "JP"
    assert _country(db, c2) == "PH"
    db.close()


def test_backfill_skips_unknown_and_leaves_existing_country():
    db = TestSession()
    branch = _branch(db)
    _ad(db, branch, "Ad Unknown", "Unknown")  # adset country is Unknown → skip
    _ad(db, branch, "Ad Done", "VN")
    c1 = _combo(db, branch, "Ad Unknown", None)  # stays None (no usable source)
    c2 = _combo(db, branch, "Ad Done", "TW")     # already set → untouched
    db.commit()

    _do_backfill_combo_country(db)

    assert _country(db, c1) is None
    assert _country(db, c2) == "TW"
    db.close()
