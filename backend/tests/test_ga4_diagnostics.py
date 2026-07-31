"""Tests for the GA4 diagnostics probe.

The probe exists to answer three questions before we build the analytics
page: is the booking engine tracked cross-domain, do the funnel events fire,
and which conversion metric name does the property accept. Every GA4 call is
mocked — the tests assert on the shaping and the verdict, never on network.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.account import AdAccount
from app.models.user import User
from app.services.auth_service import create_access_token, hash_password
from tests.db import TestSession

client = TestClient(app)


def _admin_headers():
    db = TestSession()
    user = User(
        id=str(uuid.uuid4()),
        email=f"admin_{uuid.uuid4().hex[:8]}@meander.com",
        full_name="Admin",
        password_hash=hash_password("pass"),
        roles=["admin"],
    )
    db.add(user)
    db.commit()
    uid, roles = user.id, user.roles
    db.close()
    return {"Authorization": f"Bearer {create_access_token(uid, roles)}"}


def _account(db, name="Meander Saigon", property_id="123456"):
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id=f"act_{uuid.uuid4().hex[:6]}",
        account_name=name, currency="VND", access_token_enc="tok", is_active=True,
        ga4_property_id=property_id,
    )
    db.add(acc)
    db.commit()
    return acc


@pytest.fixture(autouse=True)
def _clean_accounts():
    db = TestSession()
    db.query(AdAccount).delete()
    db.commit()
    db.close()
    yield


# ── fake GA4 responses ─────────────────────────────────────────────────────

METADATA_MODERN = {
    "dimensions": ["hostName", "deviceCategory", "customEvent:room_type"],
    "metrics": ["sessions", "activeUsers", "newUsers", "screenPageViews",
                "engagedSessions", "engagementRate", "eventCount", "totalUsers",
                "keyEvents", "purchaseRevenue"],
}

METADATA_LEGACY = {
    **METADATA_MODERN,
    "metrics": [m for m in METADATA_MODERN["metrics"] if m != "keyEvents"] + ["conversions"],
}


def _fake_run_report(rows_by_shape):
    """Build a run_report stub that dispatches on the requested dimensions."""

    def _stub(property_id, *, date_from, date_to, dimensions, metrics, **kwargs):
        key = tuple(dimensions)
        return rows_by_shape.get(key, [])

    return _stub


FULL_ROWS = {
    (): [{"sessions": 1000, "activeUsers": 800, "newUsers": 600,
          "screenPageViews": 2500, "keyEvents": 40, "purchaseRevenue": 12000.0}],
    ("hostName",): [
        {"hostName": "staymeander.com", "sessions": 700},
        {"hostName": "hotels.cloudbeds.com", "sessions": 300},
    ],
    ("eventName",): [
        {"eventName": "page_view", "eventCount": 2500, "totalUsers": 800},
        {"eventName": "session_start", "eventCount": 1000, "totalUsers": 800},
        {"eventName": "begin_checkout", "eventCount": 120, "totalUsers": 110},
        {"eventName": "purchase", "eventCount": 40, "totalUsers": 38},
    ],
    ("deviceCategory",): [
        {"deviceCategory": "mobile", "sessions": 700, "engagedSessions": 400,
         "engagementRate": 0.57, "keyEvents": 20, "purchaseRevenue": 5000.0},
        {"deviceCategory": "desktop", "sessions": 300, "engagedSessions": 240,
         "engagementRate": 0.80, "keyEvents": 20, "purchaseRevenue": 7000.0},
    ],
    ("sessionDefaultChannelGroup",): [
        {"sessionDefaultChannelGroup": "Paid Social", "sessions": 500, "keyEvents": 15},
        {"sessionDefaultChannelGroup": "Organic Search", "sessions": 400, "keyEvents": 20},
    ],
}


def _patch(monkeypatch, *, metadata=METADATA_MODERN, rows=FULL_ROWS, metadata_error=None):
    import app.services.ga4_client as ga4_client

    def _meta(property_id):
        if metadata_error:
            raise RuntimeError(metadata_error)
        return metadata

    monkeypatch.setattr(ga4_client, "get_metadata", _meta)
    monkeypatch.setattr(ga4_client, "run_report", _fake_run_report(rows))


# ── tests ──────────────────────────────────────────────────────────────────


def test_properties_lists_configured_and_missing():
    db = TestSession()
    _account(db, name="Meander Saigon", property_id="111")
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id="act_none",
        account_name="Meander Osaka", currency="JPY", access_token_enc="tok",
        is_active=True, ga4_property_id=None,
    )
    db.add(acc)
    db.commit()
    db.close()

    resp = client.get("/api/ga4/properties", headers=_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert [p["property_id"] for p in data["properties"]] == ["111"]
    assert [a["account_name"] for a in data["accounts_without_property"]] == ["Meander Osaka"]


def test_properties_dedupes_shared_property():
    db = TestSession()
    _account(db, name="Meander Saigon", property_id="999")
    _account(db, name="Meander Saigon TikTok", property_id="999")
    db.close()

    resp = client.get("/api/ga4/properties", headers=_admin_headers())
    data = resp.json()["data"]
    assert len(data["properties"]) == 1
    assert sorted(data["properties"][0]["account_names"]) == [
        "Meander Saigon", "Meander Saigon TikTok"
    ]


def test_diagnostics_full_property(monkeypatch):
    db = TestSession()
    _account(db, name="Meander Saigon", property_id="111")
    db.close()
    _patch(monkeypatch)

    resp = client.get("/api/ga4/diagnostics?days=28", headers=_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    props = body["data"]["properties"]
    assert len(props) == 1
    p = props[0]

    assert p["ok"] is True
    assert p["errors"] == {}
    assert p["conversion_metric"] == "keyEvents"
    assert p["revenue_metric"] == "purchaseRevenue"
    assert p["custom_dimensions"] == ["customEvent:room_type"]

    # cross-domain: the booking engine host must be surfaced
    assert p["booking_engine_hosts"] == ["hotels.cloudbeds.com"]
    assert p["verdict"]["cross_domain_booking_tracked"] is True

    # funnel: present steps flagged, absent ones reported with count 0
    steps = {s["event"]: s for s in p["funnel_steps"]}
    assert steps["purchase"]["present"] is True
    assert steps["begin_checkout"]["count"] == 120
    assert steps["view_item"]["present"] is False
    assert p["verdict"]["funnel_ready"] is True
    assert p["verdict"]["conversion_source"] == "ga4_purchase"

    # device + channel splits, sorted by sessions desc
    assert [d["deviceCategory"] for d in p["devices"]] == ["mobile", "desktop"]
    assert p["verdict"]["device_split_ready"] is True
    assert [c["sessionDefaultChannelGroup"] for c in p["channels"]] == [
        "Paid Social", "Organic Search"
    ]
    assert p["verdict"]["traffic_source_ready"] is True


def test_diagnostics_legacy_property_uses_conversions_metric(monkeypatch):
    db = TestSession()
    _account(db, name="Meander Taipei", property_id="222")
    db.close()
    rows = {**FULL_ROWS, (): [{"sessions": 10, "activeUsers": 9, "newUsers": 5,
                               "screenPageViews": 20, "conversions": 3,
                               "purchaseRevenue": 100.0}]}
    _patch(monkeypatch, metadata=METADATA_LEGACY, rows=rows)

    resp = client.get("/api/ga4/diagnostics", headers=_admin_headers())
    p = resp.json()["data"]["properties"][0]
    assert p["conversion_metric"] == "conversions"


def test_diagnostics_no_purchase_falls_back_to_proxy_verdict(monkeypatch):
    """LP-only property: no booking engine host, no purchase event."""
    db = TestSession()
    _account(db, name="Meander 1948", property_id="333")
    db.close()

    rows = {
        (): [{"sessions": 500, "activeUsers": 400, "newUsers": 350,
              "screenPageViews": 900, "keyEvents": 0, "purchaseRevenue": 0.0}],
        ("hostName",): [{"hostName": "staymeander.com", "sessions": 500}],
        ("eventName",): [
            {"eventName": "page_view", "eventCount": 900, "totalUsers": 400},
            {"eventName": "click", "eventCount": 60, "totalUsers": 55},
        ],
        ("deviceCategory",): [{"deviceCategory": "mobile", "sessions": 500,
                               "engagedSessions": 200, "engagementRate": 0.4}],
        ("sessionDefaultChannelGroup",): [
            {"sessionDefaultChannelGroup": "Paid Social", "sessions": 500}
        ],
    }
    _patch(monkeypatch, rows=rows)

    resp = client.get("/api/ga4/diagnostics", headers=_admin_headers())
    p = resp.json()["data"]["properties"][0]
    assert p["booking_engine_hosts"] == []
    assert p["verdict"]["cross_domain_booking_tracked"] is False
    assert p["verdict"]["funnel_ready"] is False
    assert p["verdict"]["conversion_source"].startswith("none")
    # traffic + device still answerable without conversions
    assert p["verdict"]["traffic_source_ready"] is True
    assert p["verdict"]["device_split_ready"] is True


def test_diagnostics_one_failing_report_does_not_kill_the_rest(monkeypatch):
    db = TestSession()
    _account(db, name="Oani", property_id="444")
    db.close()

    import app.services.ga4_client as ga4_client

    def _stub(property_id, *, date_from, date_to, dimensions, metrics, **kwargs):
        if tuple(dimensions) == ("eventName",):
            raise RuntimeError("quota exhausted")
        return FULL_ROWS.get(tuple(dimensions), [])

    monkeypatch.setattr(ga4_client, "get_metadata", lambda pid: METADATA_MODERN)
    monkeypatch.setattr(ga4_client, "run_report", _stub)

    resp = client.get("/api/ga4/diagnostics", headers=_admin_headers())
    body = resp.json()
    assert body["success"] is True
    p = body["data"]["properties"][0]
    assert p["errors"]["events"] == "quota exhausted"
    assert p["events"] == []
    # everything else still shaped
    assert [d["deviceCategory"] for d in p["devices"]] == ["mobile", "desktop"]
    assert p["totals"]["sessions"] == 1000


def test_diagnostics_no_property_configured():
    resp = client.get("/api/ga4/diagnostics", headers=_admin_headers())
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["properties"] == []
    assert "ga4_property_id" in body["data"]["note"]
