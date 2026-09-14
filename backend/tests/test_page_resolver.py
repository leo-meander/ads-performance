"""Tests for turning a pasted URL into a Meta Page ID.

The failure this guards against is silent: the Ad Library answers an unknown
`view_all_page_id` with an empty result, so a handle stored as an id reads as
"this competitor stopped advertising" forever. So the cases that matter are

  - every URL shape that already carries the id resolves without a lookup,
  - a handle that cannot be matched confidently returns candidates instead of
    a guess,
  - Instagram resolves to the Facebook Page that actually buys the ads,
  - a non-numeric page_id never reaches the provider on crawl.

No test touches Facebook or Apify.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import app.models  # noqa: F401 - register every table before create_all
from app.services.ad_library.base import AdLibraryError, AdLibraryPage, NormalizedAd
from app.services.ad_library.page_resolver import (
    looks_like_page_id,
    parse_target,
    resolve_page,
)
from app.models.spy_tracked_page import SpyTrackedPage
from app.services.spy_monitor import crawl_tracked_page
from tests.db import TestSession

NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)


def ad(page_id: str, page_name: str, archive_id: str = "") -> NormalizedAd:
    return NormalizedAd(
        ad_archive_id=archive_id or uuid.uuid4().hex,
        page_id=page_id,
        page_name=page_name,
        ad_delivery_start_time=NOW,
        source="apify",
    )


# ── URL shapes that already carry the id ───────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("102938475610293", "102938475610293"),
        ("https://www.facebook.com/profile.php?id=102938475610293", "102938475610293"),
        (
            "https://www.facebook.com/ads/library/?active_status=active"
            "&view_all_page_id=102938475610293",
            "102938475610293",
        ),
        ("https://www.facebook.com/pages/Icon-Hotel/102938475610293", "102938475610293"),
        ("facebook.com/pages/Icon-Hotel/102938475610293/", "102938475610293"),
    ],
)
def test_ids_in_the_url_resolve_without_any_lookup(raw, expected):
    # No provider patch on purpose: any network call here would fail the test.
    result = resolve_page(raw)
    assert result.page_id == expected
    assert result.method in ("numeric", "url_param")


def test_pages_url_keeps_the_display_name_as_a_hint():
    result = resolve_page("https://www.facebook.com/pages/Icon-Lifestyle-Hotel/102938475610293")
    assert result.page_name == "Icon Lifestyle Hotel"


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.facebook.com/groups/saigonhotels",
        "https://www.instagram.com/p/Cabc123/",
        "https://twitter.com/somehotel",
        "   ",
    ],
)
def test_links_that_are_not_pages_are_refused_with_a_message(raw):
    with pytest.raises(AdLibraryError):
        resolve_page(raw)


def test_handle_parsing_strips_the_noise():
    assert parse_target("https://m.facebook.com/iconlifestylehotel/?ref=page_internal").value == "iconlifestylehotel"
    assert parse_target("https://www.instagram.com/icon.lifestyle/").kind == "instagram"
    assert parse_target("@iconlifestylehotel").value == "iconlifestylehotel"
    assert looks_like_page_id("102938475610293") is True
    assert looks_like_page_id("iconlifestylehotel") is False


# ── Handles: page HTML first, ads second ───────────────────


def test_facebook_handle_uses_the_free_page_html_when_it_answers():
    html = '<title>Icon Lifestyle Hotel | Facebook</title><script>{"pageID":"102938475610293"}</script>'
    with patch("app.services.ad_library.page_resolver._fetch_html", return_value=html), \
         patch("app.services.ad_library.page_resolver._search_candidates") as search:
        result = resolve_page("https://www.facebook.com/iconlifestylehotel")

    assert result.page_id == "102938475610293"
    assert result.page_name == "Icon Lifestyle Hotel"
    assert result.method == "page_html"
    # The paid route must not run once the free one answered.
    search.assert_not_called()


def test_page_name_arrives_unescaped():
    """Facebook escapes the title, so a Vietnamese page name comes back as
    "Kh&#xe1;ch S&#x1ea1;n ...". Stored raw it is unreadable in the UI, and as
    an Ad Library query it matches nothing."""
    html = (
        '<title>Cupid Love Hotel - Kh&#xe1;ch S&#x1ea1;n T&#xec;nh Y&#xea;u | Facebook</title>'
        'fb://profile/100083089736912'
    )
    with patch("app.services.ad_library.page_resolver._fetch_html", return_value=html):
        result = resolve_page("https://www.facebook.com/Cupidlovehotel.01/")

    assert result.page_id == "100083089736912"
    assert result.page_name == "Cupid Love Hotel - Khách Sạn Tình Yêu"


def test_mbasic_is_tried_before_paying_for_a_search():
    """www can answer a datacenter IP with a login wall that carries no id.
    mbasic is the same Page stripped down, still free — so it must be tried
    before the provider is billed for a keyword search."""
    walled = '<title>Facebook</title><script>{"userID":"0"}</script>'
    mbasic = '<title>Cupid Love Hotel | Facebook</title>fb://profile/100083089736912'
    with patch("app.services.ad_library.page_resolver._fetch_html",
               side_effect=[walled, mbasic]) as fetch,          patch("app.services.ad_library.page_resolver._search_candidates") as search:
        result = resolve_page("https://www.facebook.com/Cupidlovehotel.01/")

    assert result.page_id == "100083089736912"
    assert result.method == "page_html"
    assert "mbasic.facebook.com" in fetch.call_args_list[1].args[0]
    search.assert_not_called()


def test_logged_out_zero_id_is_not_mistaken_for_a_page():
    html = '<title>Facebook</title><script>{"userID":"0"}</script>'
    page = AdLibraryPage(ads=[ad("102938475610293", "Icon Lifestyle Hotel")], source="apify")
    with patch("app.services.ad_library.page_resolver._fetch_html", return_value=html), \
         patch("app.services.ad_library.search_ads", return_value=page):
        result = resolve_page("https://www.facebook.com/iconlifestylehotel")

    assert result.page_id == "102938475610293"
    assert result.method == "ad_library_search"


def test_instagram_resolves_to_the_facebook_page_that_buys_the_ads():
    page = AdLibraryPage(ads=[ad("102938475610293", "Icon Lifestyle Hotel")], source="apify")
    # Empty HTML everywhere: no free route answers, so the ad search decides.
    with patch("app.services.ad_library.page_resolver._fetch_html", return_value=""), \
         patch("app.services.ad_library.search_ads", return_value=page) as search:
        result = resolve_page("https://www.instagram.com/iconlifestylehotel/")

    assert result.page_id == "102938475610293"
    assert result.platform == "instagram"
    assert "Facebook Page" in (result.note or "")
    assert search.call_count == 1


def test_instagram_first_tries_the_facebook_page_with_the_same_handle():
    # Brands almost always reuse the slug, and that check is free — so the
    # paid search must not run when facebook.com/<handle> already answers.
    html = '<title>Icon Lifestyle Hotel | Ho Chi Minh City</title>fb://profile/102938475610293'
    with patch("app.services.ad_library.page_resolver._fetch_html", return_value=html), \
         patch("app.services.ad_library.page_resolver._search_candidates") as search:
        result = resolve_page("https://www.instagram.com/iconlifestylehotel/")

    assert result.page_id == "102938475610293"
    assert result.page_name == "Icon Lifestyle Hotel"
    assert result.method == "page_html"
    assert "facebook.com/iconlifestylehotel" in (result.note or "")
    search.assert_not_called()


def test_instagram_searches_the_display_name_not_the_run_together_handle():
    # No Facebook Page is named "iconlifestylehotel", so searching the handle
    # finds nobody. Instagram's own og:title gives the name that does match.
    ig_html = (
        '<meta property="og:title" content="Icon Lifestyle Hotel (@iconlifestylehotel)'
        ' • Instagram photos and videos" />'
    )
    page = AdLibraryPage(ads=[ad("102938475610293", "Icon Lifestyle Hotel")], source="apify")
    with patch("app.services.ad_library.page_resolver._fetch_html", return_value=ig_html), \
         patch("app.services.ad_library.search_ads", return_value=page) as search:
        result = resolve_page("https://www.instagram.com/iconlifestylehotel/")

    assert search.call_args.kwargs["query"] == "Icon Lifestyle Hotel"
    assert result.page_id == "102938475610293"


def test_ambiguous_handle_returns_candidates_instead_of_a_guess():
    page = AdLibraryPage(
        ads=[
            ad("111111111111", "Saigon Riverside Resort"),
            ad("222222222222", "Hanoi Old Quarter Homes"),
        ],
        source="apify",
    )
    # Empty HTML everywhere: no free route answers, so the ad search decides.
    with patch("app.services.ad_library.page_resolver._fetch_html", return_value=""), \
         patch("app.services.ad_library.search_ads", return_value=page):
        result = resolve_page("https://www.instagram.com/iconlifestylehotel/")

    assert result.resolved is False
    assert result.page_id == ""
    assert {c.page_id for c in result.candidates} == {"111111111111", "222222222222"}


def test_no_ads_at_all_says_so_rather_than_returning_nothing():
    # Empty HTML everywhere: no free route answers, so the ad search decides.
    with patch("app.services.ad_library.page_resolver._fetch_html", return_value=""), \
         patch("app.services.ad_library.search_ads", return_value=AdLibraryPage(ads=[], source="apify")):
        with pytest.raises(AdLibraryError, match="No ads found"):
            resolve_page("https://www.instagram.com/iconlifestylehotel/")


# ── The crawl side of the same mistake ─────────────────────


def test_crawl_refuses_a_handle_instead_of_buying_a_provider_run():
    db = TestSession()
    row = SpyTrackedPage(page_id="iconlifestylehotel", page_name="Icon Lifestyle Hotel", country="VN")
    db.add(row)
    db.commit()

    with patch("app.services.spy_monitor.fetch_page_ads") as fetch:
        result = crawl_tracked_page(db, row, now=NOW)

    fetch.assert_not_called()
    assert "not a numeric Meta Page ID" in (result["error"] or "")
    assert row.last_crawl_ad_count == 0
    assert "not a numeric Meta Page ID" in (row.last_crawl_error or "")
    db.close()
