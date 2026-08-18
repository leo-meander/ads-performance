"""Tests for the Ad Name Performance router — per-ad rows and the ad_name pivot.

The pivot must sum RAW counts first and derive rates after (a weighted ROAS,
not an average of ROASes), and must never merge the same ad name across two
branches — spend/revenue are stored in each branch's native currency.
"""

import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.models.account import AdAccount
from app.models.ad_daily_metric import AdDailyMetric
from app.models.ad import Ad
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.models.user import User
from app.services.auth_service import create_access_token, hash_password
from tests.db import TestSession

client = TestClient(app)

D0 = date.today()
D1 = D0 - timedelta(days=1)
FROM = (D0 - timedelta(days=10)).isoformat()
TO = D0.isoformat()


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


def _account(db, name="Saigon", currency="VND"):
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id=f"act_{uuid.uuid4().hex[:6]}",
        account_name=name, currency=currency, access_token_enc="tok", is_active=True,
    )
    db.add(acc)
    db.commit()
    return acc


def _metric(db, acc, *, ad_id, ad_name, campaign_id="c1", adset_id="s1", on=D1,
            spend=0, revenue=0, impressions=0, clicks=0, conversions=0, leads=0):
    db.add(AdDailyMetric(
        id=str(uuid.uuid4()), account_id=acc.id,
        campaign_id=campaign_id, campaign_name=f"Camp {campaign_id}",
        adset_id=adset_id, adset_name=f"Set {adset_id}",
        ad_id=ad_id, ad_name=ad_name, date=on,
        spend=spend, revenue=revenue, impressions=impressions, clicks=clicks,
        conversions=conversions, leads=leads,
    ))
    db.commit()


def _live_ad(db, acc, *, ad_id, ad_name, effective_status="ACTIVE", preview=None):
    """A row in `ads` — what the platform sync writes, and where Status /
    Preview are read from."""
    camp = Campaign(
        id=str(uuid.uuid4()), account_id=acc.id, platform="meta",
        platform_campaign_id=f"c_{ad_id}", name="Camp", objective="OUTCOME_SALES",
        status="ACTIVE",
    )
    db.add(camp)
    aset = AdSet(
        id=str(uuid.uuid4()), campaign_id=camp.id, account_id=acc.id, platform="meta",
        platform_adset_id=f"s_{ad_id}", name="Set", status="ACTIVE",
    )
    db.add(aset)
    db.flush()
    db.add(Ad(
        id=str(uuid.uuid4()), ad_set_id=aset.id, campaign_id=camp.id, account_id=acc.id,
        platform="meta", platform_ad_id=ad_id, name=ad_name,
        status=effective_status, effective_status=effective_status, preview_url=preview,
    ))
    db.commit()


def _get(params):
    resp = client.get(f"/api/ad-performance?{params}", headers=_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True, body["error"]
    return body["data"]


class TestPivotByAdName:
    def test_merges_same_name_across_campaigns(self):
        db = TestSession()
        acc = _account(db)
        # Same creative name, two campaigns / ad sets.
        _metric(db, acc, ad_id="a1", ad_name="Ad One", campaign_id="c1", adset_id="s1",
                spend=100, revenue=500, impressions=1000, clicks=50, conversions=2, leads=4)
        _metric(db, acc, ad_id="a2", ad_name="Ad One", campaign_id="c2", adset_id="s2",
                spend=300, revenue=300, impressions=1000, clicks=30, conversions=1, leads=1)
        _metric(db, acc, ad_id="a3", ad_name="Ad Two", campaign_id="c1", adset_id="s1",
                spend=50, revenue=250, impressions=200, clicks=10, conversions=1, leads=2)
        db.close()

        flat = _get(f"date_from={FROM}&date_to={TO}")
        assert flat["group_by"] == "ad"
        assert len(flat["items"]) == 3

        pv = _get(f"date_from={FROM}&date_to={TO}&group_by=ad_name")
        assert pv["group_by"] == "ad_name"
        assert len(pv["items"]) == 2

        one = next(i for i in pv["items"] if i["ad_name"] == "Ad One")
        assert one["ad_count"] == 2
        assert one["campaign_count"] == 2
        assert one["adset_count"] == 2
        assert one["ad_id"] is None
        assert one["spend"] == 400
        assert one["conversions"] == 3
        assert one["leads"] == 5
        # Weighted: 800/400 = 2.0 — NOT the mean of 5.0x and 1.0x.
        assert one["roas"] == 2.0
        assert one["ctr"] == 80 / 2000
        assert one["cost_per_lead"] == 80.0

        two = next(i for i in pv["items"] if i["ad_name"] == "Ad Two")
        assert two["ad_count"] == 1
        assert two["campaign_count"] == 1
        assert two["campaign_name"] == "Camp c1"

    def test_never_merges_across_branches(self):
        db = TestSession()
        sgn = _account(db, "Saigon", "VND")
        tpe = _account(db, "Taipei", "TWD")
        _metric(db, sgn, ad_id="a1", ad_name="Ad One", spend=100, revenue=500)
        _metric(db, tpe, ad_id="b1", ad_name="Ad One", spend=10, revenue=60)
        sgn_id, tpe_id = sgn.id, tpe.id
        db.close()

        items = _get(f"date_from={FROM}&date_to={TO}&group_by=ad_name")["items"]
        assert len(items) == 2
        assert {i["ad_name"] for i in items} == {"Ad One"}
        assert len({i["key"] for i in items}) == 2
        assert {i["account_id"] for i in items} == {sgn_id, tpe_id}

    def test_zero_spend_names_excluded_and_sorting_applies(self):
        db = TestSession()
        acc = _account(db)
        _metric(db, acc, ad_id="a1", ad_name="Small", spend=10, revenue=10)
        _metric(db, acc, ad_id="a2", ad_name="Big", spend=100, revenue=100)
        _metric(db, acc, ad_id="a3", ad_name="Free", spend=0, revenue=0)
        db.close()

        items = _get(f"date_from={FROM}&date_to={TO}&group_by=ad_name&sort_by=spend")["items"]
        assert [i["ad_name"] for i in items] == ["Big", "Small"]

    def test_branch_and_campaign_filters(self):
        db = TestSession()
        acc = _account(db)
        _metric(db, acc, ad_id="a1", ad_name="Ad One", campaign_id="c1", spend=100)
        _metric(db, acc, ad_id="a2", ad_name="Ad One", campaign_id="c2", spend=300)
        db.close()

        items = _get(f"date_from={FROM}&date_to={TO}&group_by=ad_name&campaign_id=c1")["items"]
        assert len(items) == 1
        assert items[0]["spend"] == 100
        assert items[0]["ad_count"] == 1


class TestAdStateColumns:
    """Status + preview link come from the `ads` table — a 'right now'
    snapshot joined onto the windowed metrics."""

    def test_per_ad_rows_carry_status_and_preview(self):
        db = TestSession()
        acc = _account(db)
        _metric(db, acc, ad_id="a1", ad_name="Ad One", spend=100, revenue=500)
        _metric(db, acc, ad_id="a2", ad_name="Ad Two", spend=50)
        _live_ad(db, acc, ad_id="a1", ad_name="Ad One", preview="https://fb.com/p/a1")
        _live_ad(db, acc, ad_id="a2", ad_name="Ad Two", effective_status="PAUSED")
        db.close()

        items = {i["ad_id"]: i for i in _get(f"date_from={FROM}&date_to={TO}")["items"]}
        assert items["a1"]["effective_status"] == "ACTIVE"
        assert items["a1"]["preview_url"] == "https://fb.com/p/a1"
        assert items["a1"]["active_count"] == 1
        assert items["a2"]["effective_status"] == "PAUSED"
        assert items["a2"]["active_count"] == 0
        assert items["a2"]["preview_url"] is None

    def test_ad_with_no_state_row_still_listed(self):
        # An ad archived or deleted on Meta after it spent has no `ads` row —
        # it must keep its metrics, not vanish or crash the join.
        db = TestSession()
        acc = _account(db)
        _metric(db, acc, ad_id="a1", ad_name="Ad One", spend=100, revenue=500)
        db.close()

        items = _get(f"date_from={FROM}&date_to={TO}")["items"]
        assert len(items) == 1
        assert items[0]["spend"] == 100
        assert items[0]["effective_status"] is None
        assert items[0]["preview_url"] is None
        assert items[0]["state_count"] == 0

    def test_pivot_row_is_active_when_any_ad_is(self):
        db = TestSession()
        acc = _account(db)
        _metric(db, acc, ad_id="a1", ad_name="Ad One", campaign_id="c1", spend=100)
        _metric(db, acc, ad_id="a2", ad_name="Ad One", campaign_id="c2", spend=300)
        _live_ad(db, acc, ad_id="a1", ad_name="Ad One", effective_status="PAUSED",
               preview="https://fb.com/p/a1")
        _live_ad(db, acc, ad_id="a2", ad_name="Ad One", effective_status="ACTIVE",
               preview="https://fb.com/p/a2")
        db.close()

        items = _get(f"date_from={FROM}&date_to={TO}&group_by=ad_name")["items"]
        assert len(items) == 1
        row = items[0]
        assert row["effective_status"] == "ACTIVE"
        assert row["active_count"] == 1
        assert row["state_count"] == 2
        # The link points at the ad that is actually running.
        assert row["preview_url"] == "https://fb.com/p/a2"

    def test_pivot_row_all_paused_reports_the_common_status(self):
        db = TestSession()
        acc = _account(db)
        _metric(db, acc, ad_id="a1", ad_name="Ad One", campaign_id="c1", spend=100)
        _metric(db, acc, ad_id="a2", ad_name="Ad One", campaign_id="c2", spend=300)
        _live_ad(db, acc, ad_id="a1", ad_name="Ad One", effective_status="PAUSED")
        _live_ad(db, acc, ad_id="a2", ad_name="Ad One", effective_status="PAUSED",
               preview="https://fb.com/p/a2")
        db.close()

        row = _get(f"date_from={FROM}&date_to={TO}&group_by=ad_name")["items"][0]
        assert row["effective_status"] == "PAUSED"
        assert row["active_count"] == 0
        assert row["preview_url"] == "https://fb.com/p/a2"

    def test_state_never_bleeds_across_branches(self):
        # Same ad name in two branches — each row keeps its own branch's state.
        db = TestSession()
        sgn = _account(db, "Saigon", "VND")
        tpe = _account(db, "Taipei", "TWD")
        _metric(db, sgn, ad_id="a1", ad_name="Ad One", spend=100)
        _metric(db, tpe, ad_id="b1", ad_name="Ad One", spend=10)
        _live_ad(db, sgn, ad_id="a1", ad_name="Ad One", effective_status="ACTIVE")
        _live_ad(db, tpe, ad_id="b1", ad_name="Ad One", effective_status="PAUSED")
        sgn_id = sgn.id
        db.close()

        items = _get(f"date_from={FROM}&date_to={TO}&group_by=ad_name")["items"]
        assert len(items) == 2
        for i in items:
            assert i["state_count"] == 1
            assert i["effective_status"] == ("ACTIVE" if i["account_id"] == sgn_id else "PAUSED")


class TestDailyByAdName:
    def test_daily_series_sums_ads_sharing_a_name(self):
        db = TestSession()
        acc = _account(db)
        _metric(db, acc, ad_id="a1", ad_name="Ad One", on=D1, spend=100, revenue=500)
        _metric(db, acc, ad_id="a2", ad_name="Ad One", campaign_id="c2", on=D1,
                spend=300, revenue=300)
        _metric(db, acc, ad_id="a1", ad_name="Ad One", on=D0, spend=50, revenue=250)
        _metric(db, acc, ad_id="a3", ad_name="Other", on=D1, spend=10, revenue=10)
        db.close()

        resp = client.get(
            f"/api/ad-performance/daily?ad_names=Ad+One&date_from={FROM}&date_to={TO}",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 2  # one row per day, both ads merged

        day1 = next(i for i in items if i["date"] == D1.isoformat())
        assert day1["spend"] == 400
        assert day1["roas"] == 2.0
        assert day1["ad_name"] == "Ad One"
        assert day1["key"].endswith("::Ad One")

        day0 = next(i for i in items if i["date"] == D0.isoformat())
        assert day0["spend"] == 50

    def test_daily_keys_match_the_pivot_list(self):
        db = TestSession()
        acc = _account(db)
        _metric(db, acc, ad_id="a1", ad_name="Ad One", spend=100, revenue=500)
        db.close()
        headers = _admin_headers()

        listed = client.get(
            f"/api/ad-performance?date_from={FROM}&date_to={TO}&group_by=ad_name",
            headers=headers,
        ).json()["data"]["items"]
        daily = client.get(
            f"/api/ad-performance/daily?ad_names=Ad+One&date_from={FROM}&date_to={TO}",
            headers=headers,
        ).json()["data"]["items"]

        assert {i["key"] for i in listed} == {i["key"] for i in daily}

    def test_daily_by_ad_id_still_works(self):
        db = TestSession()
        acc = _account(db)
        _metric(db, acc, ad_id="a1", ad_name="Ad One", spend=100, revenue=500)
        db.close()

        items = client.get(
            f"/api/ad-performance/daily?ad_ids=a1&date_from={FROM}&date_to={TO}",
            headers=_admin_headers(),
        ).json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["key"] == "a1"
        assert items[0]["ad_id"] == "a1"
        assert items[0]["roas"] == 5.0

    def test_daily_requires_ids_or_names(self):
        resp = client.get(f"/api/ad-performance/daily?date_from={FROM}&date_to={TO}",
                          headers=_admin_headers())
        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []
