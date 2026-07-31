"""Tests for the live /analytics GA4 endpoints.

The numbers below mirror the shape of the real 2026-07 probe: mobile carries
most sessions while desktop earns more per session, and the booking engine
shows up as its own host. Every GA4 call is mocked.
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


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Fresh accounts + empty caches for every test."""
    import app.routers.ga4 as ga4_router

    db = TestSession()
    db.query(AdAccount).delete()
    db.commit()
    db.close()
    ga4_router._cache.clear()
    ga4_router._metadata_cache.clear()
    yield
    ga4_router._cache.clear()
    ga4_router._metadata_cache.clear()


def _account(db, name="Meander Taipei", property_id="295612616"):
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id=f"act_{uuid.uuid4().hex[:6]}",
        account_name=name, currency="TWD", access_token_enc="tok", is_active=True,
        ga4_property_id=property_id,
    )
    db.add(acc)
    db.commit()
    return acc


METRICS = ["sessions", "activeUsers", "newUsers", "screenPageViews", "engagedSessions",
           "engagementRate", "averageSessionDuration", "bounceRate", "keyEvents",
           "purchaseRevenue", "eventCount", "totalUsers"]

ROWS = {
    (): [{"sessions": 24053, "activeUsers": 20918, "newUsers": 20274,
          "screenPageViews": 65231, "engagedSessions": 21849, "engagementRate": 0.908,
          "averageSessionDuration": 95.2, "bounceRate": 0.092,
          "keyEvents": 3009, "purchaseRevenue": 707254.99}],
    ("date",): [
        {"date": "20260703", "sessions": 800, "activeUsers": 700, "keyEvents": 90, "purchaseRevenue": 21000.0},
        {"date": "20260702", "sessions": 900, "activeUsers": 780, "keyEvents": 110, "purchaseRevenue": 25000.0},
    ],
    ("sessionDefaultChannelGroup",): [
        {"sessionDefaultChannelGroup": "Organic Social", "sessions": 9515,
         "engagedSessions": 8000, "engagementRate": 0.84, "keyEvents": 742, "purchaseRevenue": 120000.0},
        {"sessionDefaultChannelGroup": "Referral", "sessions": 2169,
         "engagedSessions": 1900, "engagementRate": 0.87, "keyEvents": 649, "purchaseRevenue": 300000.0},
    ],
    ("sessionSource", "sessionMedium"): [
        {"sessionSource": "hotels.cloudbeds.com", "sessionMedium": "referral", "sessions": 2000,
         "engagedSessions": 1800, "engagementRate": 0.9, "keyEvents": 600, "purchaseRevenue": 290000.0},
        {"sessionSource": "instagram", "sessionMedium": "organic", "sessions": 9000,
         "engagedSessions": 7600, "engagementRate": 0.84, "keyEvents": 700, "purchaseRevenue": 110000.0},
    ],
    ("sessionCampaignName",): [
        {"sessionCampaignName": "(not set)", "sessions": 12000, "engagedSessions": 10000,
         "engagementRate": 0.83, "keyEvents": 900, "purchaseRevenue": 200000.0},
    ],
    ("deviceCategory",): [
        {"deviceCategory": "mobile", "sessions": 20083, "engagedSessions": 18644,
         "engagementRate": 0.928, "keyEvents": 2327, "purchaseRevenue": 331674.99},
        {"deviceCategory": "desktop", "sessions": 3590, "engagedSessions": 2795,
         "engagementRate": 0.778, "keyEvents": 654, "purchaseRevenue": 375579.99},
        {"deviceCategory": "tablet", "sessions": 427, "engagedSessions": 410,
         "engagementRate": 0.96, "keyEvents": 28, "purchaseRevenue": 0.0},
    ],
    ("deviceCategory", "sessionDefaultChannelGroup"): [
        {"deviceCategory": "mobile", "sessionDefaultChannelGroup": "Organic Social",
         "sessions": 9000, "keyEvents": 600, "purchaseRevenue": 100000.0},
        {"deviceCategory": "desktop", "sessionDefaultChannelGroup": "Referral",
         "sessions": 1200, "keyEvents": 400, "purchaseRevenue": 250000.0},
    ],
    ("eventName",): [
        {"eventName": "session_start", "eventCount": 23831, "totalUsers": 20728},
        {"eventName": "cb_booking_engine_load", "eventCount": 7361, "totalUsers": 5309},
        {"eventName": "add_to_cart", "eventCount": 1306, "totalUsers": 909},
        {"eventName": "begin_checkout", "eventCount": 669, "totalUsers": 468},
        {"eventName": "purchase", "eventCount": 187, "totalUsers": 170},
        {"eventName": "scroll", "eventCount": 12619, "totalUsers": 8267},
    ],
    ("eventName", "deviceCategory"): [
        {"eventName": "session_start", "deviceCategory": "mobile", "eventCount": 20000, "totalUsers": 17000},
        {"eventName": "purchase", "deviceCategory": "mobile", "eventCount": 100, "totalUsers": 90},
        {"eventName": "session_start", "deviceCategory": "desktop", "eventCount": 3500, "totalUsers": 3000},
        {"eventName": "purchase", "deviceCategory": "desktop", "eventCount": 87, "totalUsers": 80},
    ],
    ("landingPage",): [
        {"landingPage": "/rooms", "sessions": 5000, "engagedSessions": 4000,
         "engagementRate": 0.8, "keyEvents": 400, "purchaseRevenue": 90000.0},
    ],
    ("country",): [
        {"country": "Taiwan", "sessions": 15000, "engagedSessions": 13000,
         "engagementRate": 0.86, "keyEvents": 2000, "purchaseRevenue": 500000.0},
    ],
    ("hostName",): [
        {"hostName": "tpe.staymeander.com", "sessions": 14454, "engagedSessions": 12000,
         "engagementRate": 0.83, "keyEvents": 900, "purchaseRevenue": 200000.0},
        {"hostName": "hotels.cloudbeds.com", "sessions": 7015, "engagedSessions": 6500,
         "engagementRate": 0.92, "keyEvents": 2000, "purchaseRevenue": 500000.0},
        {"hostName": "1948.staymeander.com", "sessions": 25984, "engagedSessions": 12000,
         "engagementRate": 0.46, "keyEvents": 500, "purchaseRevenue": 80000.0},
    ],
}


def _patch(monkeypatch, rows=None, capture=None):
    import app.services.ga4_client as ga4_client

    data = rows if rows is not None else ROWS

    def _run(property_id, *, date_from, date_to, dimensions, metrics,
             dimension_filter=None, limit=100_000):
        if capture is not None:
            capture.append({
                "dimensions": tuple(dimensions), "metrics": list(metrics),
                "date_from": date_from, "date_to": date_to,
                "dimension_filter": dimension_filter,
            })
        return data.get(tuple(dimensions), [])

    monkeypatch.setattr(ga4_client, "get_metadata", lambda pid: {"dimensions": [], "metrics": METRICS})
    monkeypatch.setattr(ga4_client, "run_report", _run)


def _get(path, headers=None):
    resp = client.get(path, headers=headers or _admin_headers())
    assert resp.status_code == 200
    return resp.json()


# ── overview ───────────────────────────────────────────────────────────────


def test_overview_summary_and_derived_rates(monkeypatch):
    db = TestSession(); _account(db); db.close()
    _patch(monkeypatch)

    body = _get("/api/ga4/overview?branch=Taipei&date_from=2026-07-03&date_to=2026-07-30")
    assert body["success"] is True
    d = body["data"]
    assert d["branch"] == "Taipei"
    assert d["property_id"] == "295612616"
    assert d["conversion_metric"] == "keyEvents"

    s = d["summary"]
    assert s["sessions"] == 24053
    assert s["key_events"] == 3009
    # derived from raw sums, not averaged
    assert s["conversion_rate"] == pytest.approx(3009 / 24053)
    assert s["revenue_per_session"] == pytest.approx(707254.99 / 24053)
    # trend sorted ascending by date, GA4's YYYYMMDD parsed to ISO
    assert [t["date"] for t in d["trend"]] == ["2026-07-02", "2026-07-03"]


def test_overview_compare_uses_preceding_equal_window(monkeypatch):
    db = TestSession(); _account(db); db.close()
    calls = []
    _patch(monkeypatch, capture=calls)

    body = _get("/api/ga4/overview?branch=Taipei&date_from=2026-07-03&date_to=2026-07-30")
    prev = body["data"]["previous"]
    # 28-day window → previous window is the 28 days immediately before it
    assert prev["date_from"] == "2026-06-05"
    assert prev["date_to"] == "2026-07-02"

    totals_calls = [c for c in calls if c["dimensions"] == ()]
    assert len(totals_calls) == 2


def test_overview_compare_can_be_disabled(monkeypatch):
    db = TestSession(); _account(db); db.close()
    _patch(monkeypatch)
    body = _get("/api/ga4/overview?branch=Taipei&compare=false")
    assert body["data"]["previous"] is None


def test_overview_defaults_to_last_28_days_ending_yesterday(monkeypatch):
    from datetime import date, datetime, timedelta, timezone

    db = TestSession(); _account(db); db.close()
    _patch(monkeypatch)
    body = _get("/api/ga4/overview?branch=Taipei&compare=false")
    today = datetime.now(timezone.utc).date()
    assert body["data"]["date_to"] == (today - timedelta(days=1)).isoformat()
    assert body["data"]["date_from"] == (today - timedelta(days=28)).isoformat()


def test_unknown_branch_returns_error(monkeypatch):
    db = TestSession(); _account(db); db.close()
    _patch(monkeypatch)
    body = _get("/api/ga4/overview?branch=Bread")
    assert body["success"] is False
    assert "Bread" in body["error"]


def test_invalid_host_scope_rejected(monkeypatch):
    db = TestSession(); _account(db); db.close()
    _patch(monkeypatch)
    body = _get("/api/ga4/overview?branch=Taipei&host_scope=nonsense")
    assert body["success"] is False
    assert "host_scope" in body["error"]


# ── host scoping ───────────────────────────────────────────────────────────


def test_host_scope_all_sends_no_filter(monkeypatch):
    db = TestSession(); _account(db); db.close()
    calls = []
    _patch(monkeypatch, capture=calls)
    _get("/api/ga4/overview?branch=Taipei&host_scope=all&compare=false")
    assert all(c["dimension_filter"] is None for c in calls)


def test_host_scope_site_pins_branch_subdomain(monkeypatch):
    db = TestSession(); _account(db); db.close()
    calls = []
    _patch(monkeypatch, capture=calls)
    _get("/api/ga4/overview?branch=Taipei&host_scope=site&compare=false")
    values = calls[0]["dimension_filter"]["filter"]["in_list_filter"]["values"]
    assert values == ["tpe.staymeander.com"]
    # the shared group domain must NOT be included — it is tagged into every
    # property and would be counted once per branch
    assert "staymeander.com" not in values


def test_host_scope_booking_pins_cloudbeds(monkeypatch):
    db = TestSession(); _account(db); db.close()
    calls = []
    _patch(monkeypatch, capture=calls)
    _get("/api/ga4/overview?branch=Taipei&host_scope=booking&compare=false")
    values = calls[0]["dimension_filter"]["filter"]["in_list_filter"]["values"]
    assert "hotels.cloudbeds.com" in values


def test_shared_property_is_flagged(monkeypatch):
    """Property 514380737 is also tagged on the 1948 and Osaka sites."""
    db = TestSession(); _account(db, name="Oani (Taipei)", property_id="514380737"); db.close()
    _patch(monkeypatch)
    body = _get("/api/ga4/overview?branch=Oani&compare=false")
    assert body["data"]["shared_property_with"] == ["1948", "Osaka"]


def test_unshared_property_reports_empty_shared_list(monkeypatch):
    db = TestSession(); _account(db); db.close()
    _patch(monkeypatch)
    body = _get("/api/ga4/overview?branch=Taipei&compare=false")
    assert body["data"]["shared_property_with"] == []


# ── acquisition ────────────────────────────────────────────────────────────


def test_acquisition_shapes_and_sorts(monkeypatch):
    db = TestSession(); _account(db); db.close()
    _patch(monkeypatch)
    d = _get("/api/ga4/acquisition?branch=Taipei")["data"]

    assert [c["channel"] for c in d["channels"]] == ["Organic Social", "Referral"]
    ref = d["channels"][1]
    assert ref["conversion_rate"] == pytest.approx(649 / 2169)
    assert [s["source_medium"] for s in d["sources"]][0] == "instagram / organic"


def test_acquisition_detects_booking_engine_self_referral(monkeypatch):
    db = TestSession(); _account(db); db.close()
    _patch(monkeypatch)
    d = _get("/api/ga4/acquisition?branch=Taipei")["data"]
    assert d["self_referral"]["detected"] is True
    assert d["self_referral"]["rows"][0]["source_medium"] == "hotels.cloudbeds.com / referral"
    assert "original channel" in d["self_referral"]["note"]


def test_acquisition_clean_property_reports_no_self_referral(monkeypatch):
    db = TestSession(); _account(db); db.close()
    rows = {**ROWS, ("sessionSource", "sessionMedium"): [
        {"sessionSource": "google", "sessionMedium": "organic", "sessions": 100,
         "engagedSessions": 80, "engagementRate": 0.8, "keyEvents": 10, "purchaseRevenue": 500.0},
    ]}
    _patch(monkeypatch, rows=rows)
    d = _get("/api/ga4/acquisition?branch=Taipei")["data"]
    assert d["self_referral"]["detected"] is False
    assert d["self_referral"]["note"] is None


# ── devices ────────────────────────────────────────────────────────────────


def test_devices_ranks_by_revenue_per_session_not_volume(monkeypatch):
    db = TestSession(); _account(db); db.close()
    _patch(monkeypatch)
    d = _get("/api/ga4/devices?branch=Taipei")["data"]

    # sorted by sessions, so mobile leads the table
    assert [x["device"] for x in d["devices"]] == ["mobile", "desktop", "tablet"]
    mobile = d["devices"][0]
    desktop = d["devices"][1]
    assert mobile["revenue_per_session"] == pytest.approx(331674.99 / 20083)
    assert desktop["revenue_per_session"] == pytest.approx(375579.99 / 3590)
    # ...but the verdict names desktop, which earns ~6x more per session
    assert d["verdict"]["best_revenue_per_session"] == "desktop"
    assert d["verdict"]["desktop_vs_mobile_rps_ratio"] == pytest.approx(6.33, abs=0.05)


def test_devices_matrix_crosses_device_and_channel(monkeypatch):
    db = TestSession(); _account(db); db.close()
    _patch(monkeypatch)
    d = _get("/api/ga4/devices?branch=Taipei")["data"]
    top = d["device_channel_matrix"][0]
    assert (top["device"], top["channel"]) == ("mobile", "Organic Social")
    assert top["conversion_rate"] == pytest.approx(600 / 9000)


def test_devices_handles_zero_revenue_without_dividing_by_zero(monkeypatch):
    db = TestSession(); _account(db); db.close()
    rows = {**ROWS, ("deviceCategory",): [
        {"deviceCategory": "mobile", "sessions": 100, "engagedSessions": 50,
         "engagementRate": 0.5, "keyEvents": 0, "purchaseRevenue": 0.0},
    ]}
    _patch(monkeypatch, rows=rows)
    d = _get("/api/ga4/devices?branch=Taipei")["data"]
    assert d["devices"][0]["revenue_per_session"] == 0
    assert d["verdict"]["desktop_vs_mobile_rps_ratio"] is None


# ── funnel ─────────────────────────────────────────────────────────────────


def test_funnel_uses_real_site_events_not_generic_retail_steps(monkeypatch):
    db = TestSession(); _account(db); db.close()
    _patch(monkeypatch)
    d = _get("/api/ga4/funnel?branch=Taipei")["data"]

    labels = [s["event"] for s in d["steps"]]
    assert labels == ["session_start", "cb_booking_engine_load", "add_to_cart",
                      "begin_checkout", "purchase"]
    # the never-fired retail events are absent entirely
    assert "view_item" not in labels
    assert "add_payment_info" not in labels


def test_funnel_dropoff_math(monkeypatch):
    db = TestSession(); _account(db); db.close()
    _patch(monkeypatch)
    steps = {s["event"]: s for s in _get("/api/ga4/funnel?branch=Taipei")["data"]["steps"]}

    assert steps["session_start"]["pct_of_top"] == 1.0
    assert steps["session_start"]["step_conversion"] is None
    assert steps["cb_booking_engine_load"]["step_conversion"] == pytest.approx(5309 / 20728)
    assert steps["purchase"]["pct_of_top"] == pytest.approx(170 / 20728)
    assert steps["begin_checkout"]["dropoff"] == pytest.approx(1 - 468 / 909)


def test_funnel_per_device_and_other_events(monkeypatch):
    db = TestSession(); _account(db); db.close()
    _patch(monkeypatch)
    d = _get("/api/ga4/funnel?branch=Taipei")["data"]

    by_device = {x["device"]: x for x in d["by_device"]}
    assert by_device["mobile"]["top_to_purchase"] == pytest.approx(90 / 17000)
    assert by_device["desktop"]["top_to_purchase"] == pytest.approx(80 / 3000)
    # events outside the funnel are still surfaced
    assert d["other_events"][0]["event"] == "scroll"
    assert "sequential" in d["caveat"]


def test_funnel_missing_step_does_not_break_ratios(monkeypatch):
    db = TestSession(); _account(db); db.close()
    rows = {**ROWS, ("eventName",): [
        {"eventName": "session_start", "eventCount": 1000, "totalUsers": 900},
        {"eventName": "purchase", "eventCount": 10, "totalUsers": 9},
    ]}
    _patch(monkeypatch, rows=rows)
    steps = {s["event"]: s for s in _get("/api/ga4/funnel?branch=Taipei")["data"]["steps"]}
    assert steps["cb_booking_engine_load"]["present"] is False
    assert steps["cb_booking_engine_load"]["users"] == 0
    # an absent middle step must not zero out the steps below it
    assert steps["purchase"]["step_conversion"] == pytest.approx(9 / 900)


# ── pages ──────────────────────────────────────────────────────────────────


def test_pages_flags_foreign_branch_hosts(monkeypatch):
    """The Oani-style tagging leak has to be visible, not silently summed."""
    db = TestSession(); _account(db); db.close()
    _patch(monkeypatch)
    d = _get("/api/ga4/pages?branch=Taipei")["data"]

    assert [h["host"] for h in d["foreign_branch_hosts"]] == ["1948.staymeander.com"]
    # the branch's own host and the booking engine are not "foreign"
    hosts = [h["host"] for h in d["hosts"]]
    assert "tpe.staymeander.com" in hosts and "hotels.cloudbeds.com" in hosts
    assert d["pages"][0]["page"] == "/rooms"
    assert d["countries"][0]["country"] == "Taiwan"


# ── caching ────────────────────────────────────────────────────────────────


def test_response_is_cached_per_branch_and_window(monkeypatch):
    db = TestSession(); _account(db); db.close()
    calls = []
    _patch(monkeypatch, capture=calls)

    _get("/api/ga4/devices?branch=Taipei&date_from=2026-07-03&date_to=2026-07-30")
    after_first = len(calls)
    _get("/api/ga4/devices?branch=Taipei&date_from=2026-07-03&date_to=2026-07-30")
    assert len(calls) == after_first, "second identical request should hit the cache"

    # a different window must miss the cache
    _get("/api/ga4/devices?branch=Taipei&date_from=2026-06-01&date_to=2026-06-28")
    assert len(calls) > after_first


# ── cross-filter segments ──────────────────────────────────────────────────


def _filter_of(call):
    return call["dimension_filter"]


def test_single_segment_becomes_a_bare_string_filter(monkeypatch):
    db = TestSession(); _account(db); db.close()
    calls = []
    _patch(monkeypatch, capture=calls)

    _get("/api/ga4/overview?branch=Taipei&host_scope=all&compare=false&device=mobile")
    f = _filter_of(calls[0])
    assert f == {
        "filter": {
            "field_name": "deviceCategory",
            "string_filter": {"match_type": "EXACT", "value": "mobile"},
        }
    }


def test_multiple_segments_are_anded_together(monkeypatch):
    db = TestSession(); _account(db); db.close()
    calls = []
    _patch(monkeypatch, capture=calls)

    _get("/api/ga4/devices?branch=Taipei&device=desktop&channel=Paid%20Social&country=Taiwan")
    exprs = _filter_of(calls[0])["and_group"]["expressions"]
    fields = {e["filter"]["field_name"]: e["filter"]["string_filter"]["value"] for e in exprs}
    assert fields == {
        "deviceCategory": "desktop",
        "sessionDefaultChannelGroup": "Paid Social",
        "country": "Taiwan",
    }


def test_segment_combines_with_host_scope(monkeypatch):
    """Host scope and a pinned segment must both apply, not override each other."""
    db = TestSession(); _account(db); db.close()
    calls = []
    _patch(monkeypatch, capture=calls)

    _get("/api/ga4/funnel?branch=Taipei&host_scope=site&device=mobile")
    exprs = _filter_of(calls[0])["and_group"]["expressions"]
    assert exprs[0]["filter"]["in_list_filter"]["values"] == ["tpe.staymeander.com"]
    assert exprs[1]["filter"]["string_filter"]["value"] == "mobile"


def test_segments_apply_to_every_report_in_a_section(monkeypatch):
    db = TestSession(); _account(db); db.close()
    calls = []
    _patch(monkeypatch, capture=calls)

    _get("/api/ga4/devices?branch=Taipei&channel=Referral")
    assert len(calls) >= 2
    assert all(_filter_of(c) is not None for c in calls), "every report must carry the filter"


def test_segments_are_echoed_back(monkeypatch):
    db = TestSession(); _account(db); db.close()
    _patch(monkeypatch)
    d = _get("/api/ga4/overview?branch=Taipei&compare=false&device=mobile&country=Japan")["data"]
    assert d["segments"] == {"device": "mobile", "country": "Japan"}


def test_empty_segment_values_are_ignored(monkeypatch):
    db = TestSession(); _account(db); db.close()
    calls = []
    _patch(monkeypatch, capture=calls)

    _get("/api/ga4/overview?branch=Taipei&host_scope=all&compare=false&device=&channel=")
    assert _filter_of(calls[0]) is None
    assert _get("/api/ga4/overview?branch=Taipei&compare=false&device=")["data"]["segments"] == {}


def test_cache_key_separates_segments(monkeypatch):
    db = TestSession(); _account(db); db.close()
    calls = []
    _patch(monkeypatch, capture=calls)

    _get("/api/ga4/devices?branch=Taipei&device=mobile")
    n = len(calls)
    _get("/api/ga4/devices?branch=Taipei&device=mobile")
    assert len(calls) == n, "identical segment should hit the cache"
    _get("/api/ga4/devices?branch=Taipei&device=desktop")
    assert len(calls) > n, "a different segment must miss the cache"


def test_sources_carry_raw_source_and_medium_for_cross_filtering(monkeypatch):
    """The combined "source / medium" label can't be split — a source may
    itself contain a slash — so both raw values ride along."""
    db = TestSession(); _account(db); db.close()
    _patch(monkeypatch)
    d = _get("/api/ga4/acquisition?branch=Taipei")["data"]
    top = d["sources"][0]
    assert top["source_medium"] == "instagram / organic"
    assert top["source"] == "instagram"
    assert top["medium"] == "organic"


def test_cache_key_separates_host_scopes(monkeypatch):
    db = TestSession(); _account(db); db.close()
    calls = []
    _patch(monkeypatch, capture=calls)

    _get("/api/ga4/devices?branch=Taipei&host_scope=all")
    n = len(calls)
    _get("/api/ga4/devices?branch=Taipei&host_scope=site")
    assert len(calls) > n, "host_scope must be part of the cache key"
