"""Creative Library ↔ hypothesis linking.

Covers the many-to-many link endpoint (add/remove + legacy combo_id promotion)
and the Creative Library coverage filters (search / has_hypothesis / has_keypoint).
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.main import app
from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.base import Base
from app.models.creative_hypothesis import CreativeHypothesis
from app.models.hypothesis_combo_link import HypothesisComboLink
from app.models.keypoint import BranchKeypoint
from app.models.user import User
from app.services.auth_service import create_access_token, hash_password


engine = create_engine("sqlite:///test_hypothesis_combo_links.db", connect_args={"check_same_thread": False})
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _admin():
    db = TestSession()
    user = User(
        id=str(uuid.uuid4()),
        email=f"admin_{uuid.uuid4().hex[:6]}@meander.com",
        full_name="Admin",
        password_hash=hash_password("pw"),
        roles=["admin"],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(user.id, user.roles or [])}"}


def _seed():
    """One account + three combos:
      CMB-801  "Sakura couple video"   keypoints: [kp]
      CMB-802  "Location first video"  keypoints: []
      CMB-803  "Rooftop bar image"     keypoints: None
    """
    db = TestSession()
    account = AdAccount(
        id=str(uuid.uuid4()), platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:8]}",
        account_name="Meander Osaka", currency="JPY",
    )
    db.add(account)
    db.flush()

    kp = BranchKeypoint(branch_id=account.id, category="location", title="5 min to station")
    db.add(kp)
    db.flush()

    for i, (cid, name, kps) in enumerate([
        ("CMB-801", "Sakura couple video", [kp.id]),
        ("CMB-802", "Location first video", []),
        ("CMB-803", "Rooftop bar image", None),
    ]):
        db.add(AdCopy(copy_id=f"CPY-80{i}", branch_id=account.id, target_audience="Couple",
                      headline=name, body_text=name))
        db.add(AdMaterial(branch_id=account.id, material_id=f"MAT-80{i}",
                          material_type="video", file_url="https://drive.example/v.mp4"))
        db.add(AdCombo(
            id=str(uuid.uuid4()), combo_id=cid, branch_id=account.id, ad_name=name,
            target_audience="Couple", country="TW", keypoint_ids=kps,
            copy_id=f"CPY-80{i}", material_id=f"MAT-80{i}", verdict="TEST",
        ))
    db.commit()
    db.close()
    return account


def _seed_hypothesis(hypothesis_id="HYP-801", *, combo_id=None):
    db = TestSession()
    db.add(CreativeHypothesis(
        hypothesis_id=hypothesis_id, branch_name="Meander Osaka",
        hypothesis="Location-first openings hold attention longer.",
        combo_id=combo_id, status="pending", primary_metric="hold_rate",
    ))
    db.commit()
    db.close()


def _combo_ids(params: str, user) -> set[str]:
    body = client.get(f"/api/combos?{params}", headers=_auth(user)).json()
    assert body["success"], body
    return {c["combo_id"] for c in body["data"]["items"]}


# ── Link endpoint ─────────────────────────────────────────────


def test_link_adds_multiple_combos_to_existing_hypothesis():
    _seed()
    _seed_hypothesis()
    admin = _admin()

    r = client.post("/api/hypotheses/HYP-801/combos",
                    json={"combo_ids": ["CMB-801"], "action": "add"}, headers=_auth(admin))
    assert r.json()["success"], r.json()
    r = client.post("/api/hypotheses/HYP-801/combos",
                    json={"combo_ids": ["CMB-802"], "action": "add"}, headers=_auth(admin))
    body = r.json()
    assert body["success"], body
    assert {c["combo_id"] for c in body["data"]["linked_combos"]} == {"CMB-801", "CMB-802"}


def test_link_add_promotes_legacy_combo_id_into_junction_table():
    """Pre-junction hypotheses carry one combo on creative_hypotheses.combo_id.
    Adding a second must not make the first disappear."""
    _seed()
    _seed_hypothesis(combo_id="CMB-803")
    admin = _admin()

    body = client.post("/api/hypotheses/HYP-801/combos",
                       json={"combo_ids": ["CMB-801"], "action": "add"},
                       headers=_auth(admin)).json()
    assert body["success"], body
    assert {c["combo_id"] for c in body["data"]["linked_combos"]} == {"CMB-801", "CMB-803"}

    db = TestSession()
    assert db.query(HypothesisComboLink).filter_by(combo_id="CMB-803").count() == 1
    db.close()


def test_link_remove_drops_link_and_clears_legacy_column():
    _seed()
    _seed_hypothesis(combo_id="CMB-803")
    admin = _admin()
    client.post("/api/hypotheses/HYP-801/combos",
                json={"combo_ids": ["CMB-801"], "action": "add"}, headers=_auth(admin))

    body = client.post("/api/hypotheses/HYP-801/combos",
                       json={"combo_ids": ["CMB-803"], "action": "remove"},
                       headers=_auth(admin)).json()
    assert body["success"], body
    assert {c["combo_id"] for c in body["data"]["linked_combos"]} == {"CMB-801"}

    db = TestSession()
    hyp = db.query(CreativeHypothesis).filter_by(hypothesis_id="HYP-801").first()
    assert hyp.combo_id is None  # legacy chip must not resurrect the unlinked combo
    db.close()


def test_link_add_is_idempotent():
    _seed()
    _seed_hypothesis()
    admin = _admin()
    for _ in range(2):
        client.post("/api/hypotheses/HYP-801/combos",
                    json={"combo_ids": ["CMB-801"], "action": "add"}, headers=_auth(admin))
    db = TestSession()
    assert db.query(HypothesisComboLink).filter_by(hypothesis_id="HYP-801").count() == 1
    db.close()


def test_link_unknown_hypothesis_returns_error():
    _seed()
    body = client.post("/api/hypotheses/HYP-999/combos",
                       json={"combo_ids": ["CMB-801"], "action": "add"},
                       headers=_auth(_admin())).json()
    assert body["success"] is False
    assert "not found" in (body["error"] or "").lower()


# ── Creative Library filters ──────────────────────────────────


def test_combos_search_matches_ad_name_and_combo_id():
    _seed()
    admin = _admin()
    assert _combo_ids("search=rooftop", admin) == {"CMB-803"}
    assert _combo_ids("search=CMB-802", admin) == {"CMB-802"}
    assert _combo_ids("search=video", admin) == {"CMB-801", "CMB-802"}
    assert _combo_ids("search=nothingmatches", admin) == set()


def test_combos_has_hypothesis_filter_covers_junction_and_legacy():
    _seed()
    _seed_hypothesis("HYP-801", combo_id="CMB-803")   # legacy link
    _seed_hypothesis("HYP-802")
    admin = _admin()
    client.post("/api/hypotheses/HYP-802/combos",
                json={"combo_ids": ["CMB-801"], "action": "add"}, headers=_auth(admin))

    assert _combo_ids("has_hypothesis=false", admin) == {"CMB-802"}
    assert _combo_ids("has_hypothesis=true", admin) == {"CMB-801", "CMB-803"}


def test_combos_has_keypoint_filter_treats_empty_list_as_missing():
    _seed()
    admin = _admin()
    assert _combo_ids("has_keypoint=false", admin) == {"CMB-802", "CMB-803"}
    assert _combo_ids("has_keypoint=true", admin) == {"CMB-801"}


def test_combos_list_reports_linked_hypothesis_ids():
    _seed()
    _seed_hypothesis("HYP-801")
    admin = _admin()
    client.post("/api/hypotheses/HYP-801/combos",
                json={"combo_ids": ["CMB-802"], "action": "add"}, headers=_auth(admin))

    body = client.get("/api/combos", headers=_auth(admin)).json()
    by_id = {c["combo_id"]: c for c in body["data"]["items"]}
    assert by_id["CMB-802"]["hypothesis_ids"] == ["HYP-801"]
    assert by_id["CMB-801"]["hypothesis_ids"] == []


def test_hypotheses_search_param_filters_by_id_and_text():
    _seed_hypothesis("HYP-801")
    admin = _admin()
    hit = client.get("/api/hypotheses?search=location-first", headers=_auth(admin)).json()
    assert [h["hypothesis_id"] for h in hit["data"]["items"]] == ["HYP-801"]
    miss = client.get("/api/hypotheses?search=HYP-999", headers=_auth(admin)).json()
    assert miss["data"]["items"] == []
