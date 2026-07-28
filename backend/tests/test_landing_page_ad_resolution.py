"""utm_content → ad resolution for landing-page ad-links.

Landing pages are chosen per ad, but ad-links were only ever recorded per
campaign, so a campaign shared by several pages handed its full spend to each
of them. These cover the matcher that makes ad-level attribution possible.
"""
from collections import defaultdict

from app.services.landing_page_importer import resolve_ad_from_utm_content


class FakeAd:
    """Stand-in for app.models.ad.Ad — the matcher only reads these fields."""

    def __init__(self, id, campaign_id, name, platform_ad_id=None):
        self.id = id
        self.campaign_id = campaign_id
        self.name = name
        self.platform_ad_id = platform_ad_id


def _index(ads):
    by_campaign = defaultdict(list)
    by_platform_id = {}
    for a in ads:
        if a.campaign_id:
            by_campaign[a.campaign_id].append(a)
        if a.platform_ad_id:
            by_platform_id[a.platform_ad_id] = a
    return by_campaign, by_platform_id


def test_resolves_bare_meta_ad_id():
    ad = FakeAd("ad-1", "camp-1", "[Video] KOL_Xavier", "120246611392740192")
    by_c, by_p = _index([ad])

    assert resolve_ad_from_utm_content("120246611392740192", "camp-1", by_c, by_p) is ad


def test_ad_id_from_another_campaign_is_rejected():
    """The id resolves, but to an ad outside the campaign we matched — that
    combination means the utm tags disagree, so trust neither."""
    ad = FakeAd("ad-1", "camp-OTHER", "[Video] KOL_Xavier", "120246611392740192")
    by_c, by_p = _index([ad])

    assert resolve_ad_from_utm_content("120246611392740192", "camp-1", by_c, by_p) is None


def test_unknown_ad_id_resolves_to_nothing():
    by_c, by_p = _index([FakeAd("ad-1", "camp-1", "whatever", "111")])

    assert resolve_ad_from_utm_content("999999999", "camp-1", by_c, by_p) is None


def test_resolves_adset_prefixed_name_by_suffix():
    """Real prod shape: utm_content is the adset name and ad name joined."""
    ad = FakeAd("ad-1", "camp-1", "[Video] KOL_Denver Choi")
    by_c, by_p = _index([ad])

    got = resolve_ad_from_utm_content(
        "HK_M&F_25-44_Friend_ZH_[Video] KOL_Denver Choi", "camp-1", by_c, by_p
    )
    assert got is ad


def test_longest_suffix_wins_over_shorter_one():
    short = FakeAd("ad-short", "camp-1", "KOL_Xavier")
    long = FakeAd("ad-long", "camp-1", "[Video] KOL_Xavier")
    by_c, by_p = _index([short, long])

    got = resolve_ad_from_utm_content("MY_M&F_18-54_[Video] KOL_Xavier", "camp-1", by_c, by_p)
    assert got is long


def test_tie_between_two_ads_resolves_to_nothing():
    """Two different ads with the same name — misattributing spend is worse
    than reporting none, so refuse to pick."""
    a = FakeAd("ad-a", "camp-1", "[Image] Suite Rooms")
    b = FakeAd("ad-b", "camp-1", "[Image] Suite Rooms")
    by_c, by_p = _index([a, b])

    assert resolve_ad_from_utm_content("TW_M&F_ZH_[Image] Suite Rooms", "camp-1", by_c, by_p) is None


def test_ads_outside_the_campaign_are_not_candidates():
    other = FakeAd("ad-other", "camp-2", "[Video] KOL_Denver Choi")
    by_c, by_p = _index([other])

    got = resolve_ad_from_utm_content(
        "HK_M&F_25-44_Friend_ZH_[Video] KOL_Denver Choi", "camp-1", by_c, by_p
    )
    assert got is None


def test_no_match_when_name_is_not_a_suffix():
    """Substring in the middle must not count — only a true suffix does."""
    ad = FakeAd("ad-1", "camp-1", "KOL_Xavier")
    by_c, by_p = _index([ad])

    assert resolve_ad_from_utm_content("KOL_Xavier_extra_tail", "camp-1", by_c, by_p) is None


def test_unsubstituted_meta_placeholder_is_ignored():
    ad = FakeAd("ad-1", "camp-1", "{{ad.name}}")
    by_c, by_p = _index([ad])

    assert resolve_ad_from_utm_content("{{ad.name}}", "camp-1", by_c, by_p) is None


def test_blank_and_missing_values_are_ignored():
    by_c, by_p = _index([FakeAd("ad-1", "camp-1", "x")])

    assert resolve_ad_from_utm_content(None, "camp-1", by_c, by_p) is None
    assert resolve_ad_from_utm_content("", "camp-1", by_c, by_p) is None
    assert resolve_ad_from_utm_content("   ", "camp-1", by_c, by_p) is None


def test_ad_with_empty_name_never_matches():
    ad = FakeAd("ad-1", "camp-1", "")
    by_c, by_p = _index([ad])

    assert resolve_ad_from_utm_content("anything at all", "camp-1", by_c, by_p) is None
