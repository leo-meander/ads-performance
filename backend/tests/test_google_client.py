"""Tests for Google Ads client (google_client.py).

All Google API calls are mocked — no real API access needed.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest


# Mock the google.ads module before importing google_client
@pytest.fixture(autouse=True)
def mock_google_ads():
    """Mock the google-ads SDK so tests don't require it installed."""
    mock_client_class = MagicMock()
    mock_client_instance = MagicMock()
    mock_client_class.load_from_dict.return_value = mock_client_instance

    with patch.dict("sys.modules", {
        "google": MagicMock(),
        "google.ads": MagicMock(),
        "google.ads.googleads": MagicMock(),
        "google.ads.googleads.client": MagicMock(GoogleAdsClient=mock_client_class),
        "google.ads.googleads.errors": MagicMock(GoogleAdsException=Exception),
    }):
        yield mock_client_instance


def _make_campaign_row(cid="123", name="Test Campaign", status="ENABLED", channel_type="SEARCH", budget_micros=50_000_000):
    """Create a mock GAQL row for campaign query."""
    row = MagicMock()
    row.campaign.id = cid
    row.campaign.name = name
    row.campaign.status = status
    row.campaign.advertising_channel_type = channel_type
    row.campaign.start_date = "2026-01-01"
    row.campaign.end_date = ""
    row.campaign_budget.amount_micros = budget_micros
    return row


def _make_metrics_row(campaign_id="123", date_str="2026-04-01", cost_micros=10_000_000,
                      impressions=1000, clicks=50, conversions=5.0, conversions_value=500.0):
    row = MagicMock()
    row.campaign.id = campaign_id
    row.segments.date = date_str
    row.metrics.cost_micros = cost_micros
    row.metrics.impressions = impressions
    row.metrics.clicks = clicks
    row.metrics.conversions = conversions
    row.metrics.conversions_value = conversions_value
    return row


class TestNormalization:
    def test_status_normalization(self):
        from app.services.google_client import _normalize_status
        assert _normalize_status("ENABLED") == "ACTIVE"
        assert _normalize_status("PAUSED") == "PAUSED"
        assert _normalize_status("REMOVED") == "ARCHIVED"
        assert _normalize_status("UNKNOWN") == "UNKNOWN"

    def test_micros_to_currency(self):
        from app.services.google_client import _micros_to_currency
        assert _micros_to_currency(1_000_000) == 1.0
        assert _micros_to_currency(50_000_000) == 50.0
        assert _micros_to_currency(0) == 0.0
        assert _micros_to_currency(None) is None

    def test_micros_precision(self):
        from app.services.google_client import _micros_to_currency
        assert _micros_to_currency(1_500_000) == 1.5
        assert _micros_to_currency(123_456) == 0.123456


class TestFetchCampaigns:
    def test_returns_normalized_dicts(self, mock_google_ads):
        mock_ga_service = MagicMock()
        mock_google_ads.get_service.return_value = mock_ga_service

        row = _make_campaign_row(cid="999", name="VN_Solo_[TOF] PMax", status="ENABLED",
                                  channel_type="PERFORMANCE_MAX", budget_micros=100_000_000)

        mock_batch = MagicMock()
        mock_batch.results = [row]
        mock_ga_service.search_stream.return_value = [mock_batch]

        from app.services.google_client import fetch_campaigns
        results = fetch_campaigns("123-456-7890")

        assert len(results) == 1
        assert results[0]["platform_campaign_id"] == "999"
        assert results[0]["name"] == "VN_Solo_[TOF] PMax"
        assert results[0]["status"] == "ACTIVE"
        assert results[0]["objective"] == "PERFORMANCE_MAX"
        assert results[0]["daily_budget"] == 100.0

    def test_converts_micros_to_currency(self, mock_google_ads):
        mock_ga_service = MagicMock()
        mock_google_ads.get_service.return_value = mock_ga_service

        row = _make_campaign_row(budget_micros=75_500_000)
        mock_batch = MagicMock()
        mock_batch.results = [row]
        mock_ga_service.search_stream.return_value = [mock_batch]

        from app.services.google_client import fetch_campaigns
        results = fetch_campaigns("1234567890")
        assert results[0]["daily_budget"] == 75.5

    def test_empty_account(self, mock_google_ads):
        mock_ga_service = MagicMock()
        mock_google_ads.get_service.return_value = mock_ga_service

        mock_batch = MagicMock()
        mock_batch.results = []
        mock_ga_service.search_stream.return_value = [mock_batch]

        from app.services.google_client import fetch_campaigns
        results = fetch_campaigns("1234567890")
        assert results == []


class TestFetchCampaignMetrics:
    def test_metrics_normalized(self, mock_google_ads):
        mock_ga_service = MagicMock()
        mock_google_ads.get_service.return_value = mock_ga_service

        row = _make_metrics_row(
            campaign_id="123",
            cost_micros=10_000_000,  # $10
            impressions=1000,
            clicks=50,
            conversions=5.0,
            conversions_value=500.0,
        )
        mock_batch = MagicMock()
        mock_batch.results = [row]
        mock_ga_service.search_stream.return_value = [mock_batch]

        from app.services.google_client import fetch_campaign_metrics
        from datetime import date
        results = fetch_campaign_metrics("1234567890", date(2026, 4, 1), date(2026, 4, 1))

        assert len(results) == 1
        m = results[0]
        assert m["spend"] == 10.0
        assert m["impressions"] == 1000
        assert m["clicks"] == 50
        assert m["conversions"] == 5
        assert m["revenue"] == 500.0
        assert m["roas"] == 50.0  # 500/10
        assert m["cpa"] == 2.0  # 10/5
        assert m["cpc"] == 0.2  # 10/50
        assert m["ctr"] == 5.0  # 50/1000*100

    def test_zero_spend_no_division_error(self, mock_google_ads):
        mock_ga_service = MagicMock()
        mock_google_ads.get_service.return_value = mock_ga_service

        row = _make_metrics_row(cost_micros=0, impressions=0, clicks=0, conversions=0, conversions_value=0)
        mock_batch = MagicMock()
        mock_batch.results = [row]
        mock_ga_service.search_stream.return_value = [mock_batch]

        from app.services.google_client import fetch_campaign_metrics
        results = fetch_campaign_metrics("1234567890")

        m = results[0]
        assert m["spend"] == 0
        assert m["roas"] == 0
        assert m["cpa"] is None
        assert m["cpc"] is None
        assert m["ctr"] == 0


class TestConversionColumnMatching:
    """Conversion action → metrics_cache column mapping.

    Category (Google enum) is the primary, account-stable signal; the action's
    display name is only a fallback. Regression coverage for branches whose
    add-to-cart action is renamed (e.g. Saigon/Osaka use "Shopping Cart") and
    so never matched the old name-only substring map.
    """

    def test_category_matches_regardless_of_name(self):
        from app.services.google_client import _match_conversion_column
        # "Shopping Cart" name would NOT contain "add_to_cart", but the
        # ADD_TO_CART category resolves it correctly.
        assert _match_conversion_column("Shopping Cart", "ADD_TO_CART") == "add_to_cart"
        assert _match_conversion_column("Reserva", "BEGIN_CHECKOUT") == "checkouts"
        assert _match_conversion_column("Contact Form", "SUBMIT_LEAD_FORM") == "leads"

    def test_category_is_case_insensitive(self):
        from app.services.google_client import _match_conversion_column
        assert _match_conversion_column("whatever", "add_to_cart") == "add_to_cart"

    def test_name_fallback_when_category_generic(self):
        from app.services.google_client import _match_conversion_column
        # DEFAULT/PAGE_VIEW carry no funnel meaning → fall back to the name.
        assert _match_conversion_column("Add to cart", "DEFAULT") == "add_to_cart"
        assert _match_conversion_column("add_to_cart", "DEFAULT") == "add_to_cart"
        assert _match_conversion_column("Checkout started", "DEFAULT") == "checkouts"

    def test_search_has_no_category_uses_name(self):
        from app.services.google_client import _match_conversion_column
        # Google has no SEARCH category; the name is the only signal.
        assert _match_conversion_column("Search", "DEFAULT") == "searches"
        assert _match_conversion_column("Site Search", None) == "searches"

    def test_purchase_never_maps(self):
        from app.services.google_client import _match_conversion_column
        # PURCHASE is counted by the main query — must NOT be mapped here
        # (would double-count into a funnel column).
        assert _match_conversion_column("Purchase", "PURCHASE") is None

    def test_unrecognized_returns_none(self):
        from app.services.google_client import _match_conversion_column
        assert _match_conversion_column("Random Event", "ENGAGEMENT") is None
        assert _match_conversion_column("", None) is None


class TestFetchConversionActionMetrics:
    def test_maps_rows_via_category(self, mock_google_ads):
        mock_ga_service = MagicMock()
        mock_google_ads.get_service.return_value = mock_ga_service

        def _conv_row(cid, date_str, name, category, value):
            row = MagicMock()
            row.campaign.id = cid
            row.segments.date = date_str
            row.segments.conversion_action_name = name
            # _enum_name reads .name off the proto-plus enum
            row.segments.conversion_action_category.name = category
            row.metrics.all_conversions = value
            return row

        rows = [
            _conv_row("123", "2026-05-01", "Shopping Cart", "ADD_TO_CART", 128.99),
            _conv_row("123", "2026-05-01", "Begin checkout", "BEGIN_CHECKOUT", 45.0),
            _conv_row("123", "2026-05-01", "Purchase", "PURCHASE", 21.0),  # skipped
        ]
        mock_batch = MagicMock()
        mock_batch.results = rows
        mock_ga_service.search_stream.return_value = [mock_batch]

        from app.services.google_client import fetch_conversion_action_metrics
        from datetime import date
        out = fetch_conversion_action_metrics("1234567890", date(2026, 5, 1), date(2026, 5, 1))

        cols = {(r["column"], r["value"]) for r in out}
        assert ("add_to_cart", 128) in cols  # int() truncates 128.99
        assert ("checkouts", 45) in cols
        # PURCHASE row dropped (handled by the main per-entity query)
        assert all(r["column"] != "conversions" for r in out)
        assert len(out) == 2


class TestFieldTypeMapping:
    def test_asset_type_map(self):
        from app.services.google_client import _FIELD_TYPE_MAP
        assert _FIELD_TYPE_MAP["HEADLINE"] == "HEADLINE"
        assert _FIELD_TYPE_MAP["DESCRIPTION"] == "DESCRIPTION"
        assert _FIELD_TYPE_MAP["MARKETING_IMAGE"] == "IMAGE"
        assert _FIELD_TYPE_MAP["SQUARE_MARKETING_IMAGE"] == "IMAGE"
        assert _FIELD_TYPE_MAP["YOUTUBE_VIDEO"] == "VIDEO"
        assert _FIELD_TYPE_MAP["LANDSCAPE_LOGO"] == "LOGO"
        assert _FIELD_TYPE_MAP["BUSINESS_NAME"] == "BUSINESS_NAME"
