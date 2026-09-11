"""Tests for the Spy Ads competitor monitor.

The parts worth pinning down are the ones that quietly corrupt history if they
regress:

  - longevity accumulates across crawls instead of resetting,
  - a truncated crawl never retires the ads it simply did not reach,
  - creative grouping is order-independent and survives copy rewrites,
  - the pattern tally counts what is actually in the ledger.

Every provider call is mocked; no test touches Apify or Meta.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.models  # noqa: F401 - register every table before create_all
from app.main import app
from app.models.spy_competitor_ad import SpyCompetitorAd, SpyCreativeGroup
from app.models.spy_tracked_page import SpyTrackedPage
from app.models.user import User
from app.services.ad_library.base import AdLibraryError, AdLibraryPage, NormalizedAd
from app.services.auth_service import create_access_token, hash_password
from app.services.spy_fingerprint import asset_key, group_ads, jaccard, text_tokens
from app.services.spy_monitor import crawl_tracked_page, rebuild_creative_groups, upsert_ads
from tests.db import TestSession

client = TestClient(app)

NOW = datetime(2026, 9, 8, tzinfo=timezone.utc)


def at(dt):
    """Normalize a datetime read back from the DB.

    The test DB is SQLite, which drops tzinfo on round-trip; Postgres keeps
    it. Production code already normalizes on read, so comparing naive-to-
    aware here would only be testing the driver.
    """
    return dt.replace(tzinfo=None) if dt is not None and dt.tzinfo else dt


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


def _page(db, page_id="100000000000111", name="Hotel A", country="VN"):
    row = SpyTrackedPage(
        id=str(uuid.uuid4()),
        page_id=page_id,
        page_name=name,
        category="Boutique Hotel",
        country=country,
        is_active=True,
        monitor_enabled=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _ad(archive_id, *, start=None, body="Stay in the heart of Osaka tonight",
        images=None, videos=None, active=True, page_id="100000000000111", page_name="Hotel A"):
    return NormalizedAd(
        ad_archive_id=archive_id,
        page_id=page_id,
        page_name=page_name,
        ad_creative_bodies=[body],
        ad_creative_link_titles=["Book direct"],
        image_urls=images or [],
        video_urls=videos or [],
        media_type="video" if videos else "image",
        country="VN",
        ad_delivery_start_time=start,
        is_active=active,
        source="apify",
    )


# -- longevity ----------------------------------------------------------


def test_first_crawl_records_first_and_last_seen():
    db = TestSession()
    page = _page(db)
    upsert_ads(db, [_ad("A1", start=NOW - timedelta(days=39))], tracked_page=page, now=NOW)
    db.commit()

    row = db.query(SpyCompetitorAd).filter_by(ad_archive_id="A1").one()
    assert at(row.first_seen_at) == at(NOW)
    assert at(row.last_seen_at) == at(NOW)
    assert row.seen_count == 1
    # Meta's own start date wins over our (zero-length) observation window.
    assert row.days_running == 39
    assert row.days_observed == 0
    db.close()


def test_repeat_crawls_extend_last_seen_without_resetting_first_seen():
    db = TestSession()
    page = _page(db)
    start = NOW - timedelta(days=39)
    for offset in (0, 1, 2, 7):
        upsert_ads(
            db, [_ad("A1", start=start)], tracked_page=page,
            now=NOW + timedelta(days=offset),
        )
    db.commit()

    row = db.query(SpyCompetitorAd).filter_by(ad_archive_id="A1").one()
    assert at(row.first_seen_at) == at(NOW)
    assert at(row.last_seen_at) == at(NOW + timedelta(days=7))
    assert row.seen_count == 4
    assert row.days_observed == 7
    assert row.days_running == 46  # 39 + the 7 days we watched it keep going
    db.close()


def test_days_running_falls_back_to_observation_when_meta_gives_no_start():
    db = TestSession()
    page = _page(db)
    upsert_ads(db, [_ad("A1", start=None)], tracked_page=page, now=NOW)
    upsert_ads(db, [_ad("A1", start=None)], tracked_page=page, now=NOW + timedelta(days=5))
    db.commit()

    row = db.query(SpyCompetitorAd).filter_by(ad_archive_id="A1").one()
    assert row.days_running == 5
    db.close()


def test_missing_ad_is_retired_only_when_the_crawl_was_complete():
    """A crawl that hit its limit was truncated - absence proves nothing."""
    db = TestSession()
    page = _page(db)
    ads = [_ad(f"A{i}", start=NOW - timedelta(days=10)) for i in range(3)]

    with patch("app.services.spy_monitor.fetch_page_ads") as fetch:
        fetch.return_value = AdLibraryPage(ads=ads, source="apify")
        crawl_tracked_page(db, page, limit=10, now=NOW)

        # Second crawl returns exactly `limit` ads and drops A2 - truncated.
        fetch.return_value = AdLibraryPage(ads=ads[:2], source="apify")
        result = crawl_tracked_page(db, page, limit=2, now=NOW + timedelta(days=1))
    assert result["retired"] == 0
    assert db.query(SpyCompetitorAd).filter_by(ad_archive_id="A2").one().is_currently_active

    with patch("app.services.spy_monitor.fetch_page_ads") as fetch:
        fetch.return_value = AdLibraryPage(ads=ads[:2], source="apify")
        result = crawl_tracked_page(db, page, limit=10, now=NOW + timedelta(days=2))
    assert result["retired"] == 1
    gone = db.query(SpyCompetitorAd).filter_by(ad_archive_id="A2").one()
    assert gone.is_currently_active is False
    assert at(gone.disappeared_at) == at(NOW + timedelta(days=2))
    db.close()


def test_relaunched_ad_clears_its_tombstone():
    db = TestSession()
    page = _page(db)
    upsert_ads(db, [_ad("A1", active=False)], tracked_page=page, now=NOW)
    db.commit()
    assert db.query(SpyCompetitorAd).filter_by(ad_archive_id="A1").one().disappeared_at

    upsert_ads(db, [_ad("A1", active=True)], tracked_page=page, now=NOW + timedelta(days=1))
    db.commit()
    row = db.query(SpyCompetitorAd).filter_by(ad_archive_id="A1").one()
    assert row.disappeared_at is None
    assert row.is_currently_active is True
    db.close()


def test_provider_failure_lands_on_the_page_instead_of_raising():
    """A dead provider must be visible per page, not a silent empty grid."""
    db = TestSession()
    page = _page(db)
    with patch("app.services.spy_monitor.fetch_page_ads") as fetch:
        fetch.side_effect = AdLibraryError("APIFY_TOKEN is not set")
        result = crawl_tracked_page(db, page, now=NOW)

    assert result["error"] == "APIFY_TOKEN is not set"
    db.refresh(page)
    assert page.last_crawl_error == "APIFY_TOKEN is not set"
    assert page.last_crawl_ad_count == 0
    assert at(page.last_checked_at) == at(NOW)
    db.close()


def test_known_start_date_is_never_overwritten_by_a_blank_one():
    db = TestSession()
    page = _page(db)
    start = NOW - timedelta(days=30)
    upsert_ads(db, [_ad("A1", start=start)], tracked_page=page, now=NOW)
    upsert_ads(db, [_ad("A1", start=None)], tracked_page=page, now=NOW + timedelta(days=1))
    db.commit()

    assert db.query(SpyCompetitorAd).filter_by(ad_archive_id="A1").one().days_running == 31
    db.close()


# -- fingerprinting -----------------------------------------------------


def test_asset_key_ignores_the_volatile_cdn_signature():
    a = "https://scontent.xx.fbcdn.net/v/t39.30808-6/473829104_122_n.jpg?oh=abc&oe=123"
    b = "https://scontent-hkg.xx.fbcdn.net/v/t39.30808-6/473829104_998_n.jpg?oh=zzz&oe=999"
    assert asset_key(a) == asset_key(b) == "473829104"
    assert asset_key("https://example.com/no-id.jpg") is None


def test_shared_asset_groups_ads_even_when_the_copy_differs():
    img = "https://scontent.xx.fbcdn.net/v/t39/998877665544_1_n.jpg?oh=a"
    ads = [
        {"id": "1", "ad_creative_bodies": ["Totally different words here"],
         "ad_creative_link_titles": [], "image_urls": [img], "video_urls": []},
        {"id": "2", "ad_creative_bodies": ["Nothing alike whatsoever friend"],
         "ad_creative_link_titles": [], "image_urls": [img + "&oe=b"], "video_urls": []},
    ]
    groups = group_ads(ads)
    assert len(groups) == 1
    assert sorted(next(iter(groups.values()))) == ["1", "2"]


def test_similar_copy_groups_when_only_price_and_dates_changed():
    ads = [
        {"id": "1", "ad_creative_bodies": [
            "Stay two nights in central Taipei walking distance from Zhongshan MRT "
            "station and save 15% when you book direct"],
         "ad_creative_link_titles": [], "image_urls": [], "video_urls": []},
        {"id": "2", "ad_creative_bodies": [
            "Stay three nights in central Taipei walking distance from Zhongshan MRT "
            "station and save 25% when you book direct"],
         "ad_creative_link_titles": [], "image_urls": [], "video_urls": []},
    ]
    assert len(group_ads(ads)) == 1


def test_unrelated_ads_stay_apart():
    ads = [
        {"id": "1", "ad_creative_bodies": ["Rooftop cocktails every Friday night in Saigon"],
         "ad_creative_link_titles": [], "image_urls": [], "video_urls": []},
        {"id": "2", "ad_creative_bodies": ["Family suites near Universal Studios Osaka"],
         "ad_creative_link_titles": [], "image_urls": [], "video_urls": []},
    ]
    assert len(group_ads(ads)) == 2


def test_grouping_is_order_independent():
    img = "https://scontent.xx.fbcdn.net/v/t39/112233445566_1_n.jpg"
    make = lambda i, url: {  # noqa: E731
        "id": i, "ad_creative_bodies": [f"copy {i}"],
        "ad_creative_link_titles": [], "image_urls": [url], "video_urls": [],
    }
    ads = [make("1", img), make("2", img), make("3", "https://x/other.jpg")]
    assert group_ads(ads).keys() == group_ads(list(reversed(ads))).keys()


def test_jaccard_and_tokens_drop_boilerplate():
    assert "book" not in text_tokens("Book your stay now")
    assert jaccard(set(), {"a"}) == 0.0


# -- creative groups ----------------------------------------------------


def test_rebuild_groups_counts_competitors_and_keeps_the_oldest_start():
    db = TestSession()
    page = _page(db)
    img = "https://scontent.xx.fbcdn.net/v/t39/555555555555_1_n.jpg"
    upsert_ads(
        db,
        [
            _ad("A1", start=NOW - timedelta(days=60), images=[img],
                page_id="100000000000111", page_name="Hotel A"),
            _ad("A2", start=NOW - timedelta(days=10), images=[img + "?oh=z"],
                page_id="100000000000222", page_name="Hotel B"),
        ],
        tracked_page=page,
        now=NOW,
    )
    db.commit()
    out = rebuild_creative_groups(db, now=NOW)

    assert out["groups"] == 1
    group = db.query(SpyCreativeGroup).one()
    assert group.ad_count == 2
    assert group.active_ad_count == 2
    assert sorted(group.page_names) == ["Hotel A", "Hotel B"]
    assert group.max_days_running == 60
    assert at(group.first_seen_at) == at(NOW - timedelta(days=60))
    assert group.is_still_active is True
    db.close()


def test_group_is_marked_inactive_once_every_member_stops():
    db = TestSession()
    page = _page(db)
    img = "https://scontent.xx.fbcdn.net/v/t39/777777777777_1_n.jpg"
    upsert_ads(
        db,
        [
            _ad("A1", images=[img], active=False),
            _ad("A2", images=[img + "?oh=z"], active=False),
        ],
        tracked_page=page,
        now=NOW,
    )
    db.commit()
    rebuild_creative_groups(db, now=NOW)

    group = db.query(SpyCreativeGroup).filter_by(is_active=True).one()
    assert group.is_still_active is False
    db.close()


# -- pattern tally ------------------------------------------------------


def test_compute_tally_counts_angles_and_grades_confidence():
    from app.services.spy_intelligence import compute_tally

    db = TestSession()
    page = _page(db)
    # Three advertisers, five ads, all long-running on one angle -> HIGH.
    ads = []
    for i in range(5):
        ads.append(_ad(
            f"L{i}", start=NOW - timedelta(days=45),
            page_id=str(100 + i % 3), page_name=f"Hotel {i % 3}",
            body=f"unique body number {i} about the station",
        ))
    upsert_ads(db, ads, tracked_page=page, now=NOW)
    db.commit()
    for row in db.query(SpyCompetitorAd).all():
        row.ai_breakdown = {
            "hook": f"hook {row.ad_archive_id}",
            "primary_angle": "transit_proximity",
            "secondary_angle": "not_a_real_angle",
            "cta": "Book Now",
        }
    db.commit()

    tally = compute_tally(db, min_days_running=30)
    assert tally["total_ads"] == 5
    assert len(tally["patterns"]) == 1  # the bogus secondary angle is dropped
    pattern = tally["patterns"][0]
    assert pattern["angle"] == "transit_proximity"
    assert pattern["ad_count"] == 5
    assert pattern["competitor_count"] == 3
    assert pattern["confidence"] == "HIGH"
    assert pattern["share"] == 1.0
    assert tally["ctas"][0]["name"] == "Book Now"
    db.close()


def test_tally_ignores_ads_below_the_long_running_bar():
    from app.services.spy_intelligence import compute_tally

    db = TestSession()
    page = _page(db)
    upsert_ads(db, [_ad("S1", start=NOW - timedelta(days=3))], tracked_page=page, now=NOW)
    db.commit()
    db.query(SpyCompetitorAd).one().ai_breakdown = {"primary_angle": "price_discount"}
    db.commit()

    assert compute_tally(db, min_days_running=30)["total_ads"] == 0
    db.close()


def test_digest_refuses_to_invent_a_pattern_from_nothing():
    from app.services.spy_intelligence import build_pattern_digest

    db = TestSession()
    with pytest.raises(ValueError, match="No long-running competitor ads"):
        build_pattern_digest(db)
    db.close()


# -- API ----------------------------------------------------------------


def test_monitor_ads_ranks_longest_running_first():
    db = TestSession()
    page = _page(db)
    upsert_ads(
        db,
        [
            _ad("SHORT", start=NOW - timedelta(days=5)),
            _ad("LONG", start=NOW - timedelta(days=72)),
            _ad("MID", start=NOW - timedelta(days=31)),
        ],
        tracked_page=page,
        now=NOW,
    )
    db.commit()
    db.close()

    user = _admin()
    resp = client.get("/api/spy-ads/monitor/ads?min_days=30", headers=_auth(user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    ids = [a["ad_archive_id"] for a in body["data"]["items"]]
    assert ids == ["LONG", "MID"]
    assert body["data"]["items"][0]["days_running"] == 72


def test_monitor_status_names_the_page_that_failed():
    db = TestSession()
    page = _page(db, name="Hotel Broken")
    page.last_crawl_error = "APIFY_TOKEN is not set"
    page.last_crawl_ad_count = 0
    db.commit()
    db.close()

    user = _admin()
    body = client.get("/api/spy-ads/monitor/status", headers=_auth(user)).json()
    assert body["success"] is True
    entry = next(p for p in body["data"]["pages"] if p["page_name"] == "Hotel Broken")
    assert entry["last_crawl_error"] == "APIFY_TOKEN is not set"
    assert body["data"]["provider"]["provider"] in ("apify", "meta_official")


def test_search_surfaces_the_provider_error_instead_of_an_empty_grid():
    user = _admin()
    with patch("app.routers.ad_research.search_ads") as search:
        search.side_effect = AdLibraryError("APIFY_TOKEN is not set")
        body = client.get("/api/spy-ads/search?q=hotel", headers=_auth(user)).json()

    assert body["success"] is False
    assert "APIFY_TOKEN" in body["error"]


def test_search_passes_through_the_coverage_note_when_a_source_cannot_see_the_ads():
    user = _admin()
    with patch("app.routers.ad_research.search_ads") as search:
        search.return_value = AdLibraryPage(
            ads=[], source="meta_official", coverage_note="EU-only coverage",
        )
        body = client.get(
            "/api/spy-ads/search?q=hotel&provider=meta_official", headers=_auth(user)
        ).json()

    assert body["success"] is True
    assert body["data"]["ads"] == []
    assert body["data"]["coverage_note"] == "EU-only coverage"


def test_singleton_clusters_are_not_persisted_as_concepts():
    """One ad is not a duplicated concept - and must not claim to be."""
    db = TestSession()
    page = _page(db)
    upsert_ads(
        db,
        [
            _ad("SOLO", body="A completely unrelated rooftop bar announcement"),
            _ad("ALSO", body="Family suites beside Universal Studios in Osaka"),
        ],
        tracked_page=page,
        now=NOW,
    )
    db.commit()
    out = rebuild_creative_groups(db, now=NOW)

    assert out["groups"] == 0
    assert db.query(SpyCreativeGroup).count() == 0
    assert all(r.creative_group_key is None for r in db.query(SpyCompetitorAd).all())
    db.close()


def test_retired_ad_stops_counting_at_the_last_crawl_that_saw_it():
    """Ad-hoc crawling must not invent longevity across the gap.

    Crawl on day 0 and again on day 60 with the ad gone. We can prove it ran
    until day 0; whether it survived to day 60 is unknown, so the run length
    must stop at day 0 rather than absorb the whole 60-day gap.
    """
    db = TestSession()
    page = _page(db)
    ad = _ad("A1", start=NOW - timedelta(days=10))

    with patch("app.services.spy_monitor.fetch_page_ads") as fetch:
        fetch.return_value = AdLibraryPage(ads=[ad], source="apify")
        crawl_tracked_page(db, page, limit=10, now=NOW)
        assert db.query(SpyCompetitorAd).one().days_running == 10

        fetch.return_value = AdLibraryPage(ads=[], source="apify")
        crawl_tracked_page(db, page, limit=10, now=NOW + timedelta(days=60))

    row = db.query(SpyCompetitorAd).one()
    assert row.is_currently_active is False
    assert row.days_running == 10, "the 60-day gap must not become runtime"
    # We still record when we noticed, separately from when we last confirmed.
    assert at(row.disappeared_at) == at(NOW + timedelta(days=60))
    assert at(row.last_seen_at) == at(NOW)
    db.close()


def test_meta_stop_date_still_wins_over_our_last_sighting():
    db = TestSession()
    page = _page(db)
    ad = _ad("A1", start=NOW - timedelta(days=40))
    ad.ad_delivery_stop_time = NOW - timedelta(days=5)
    ad.is_active = False
    upsert_ads(db, [ad], tracked_page=page, now=NOW)
    db.commit()

    assert db.query(SpyCompetitorAd).one().days_running == 35
    db.close()
