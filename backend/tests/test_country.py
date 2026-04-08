"""Tests for country dashboard — basic import and structure tests."""

from app.routers.country import _api_response


class TestCountryApiResponse:
    def test_success_response(self):
        result = _api_response(data={"test": "value"})
        assert result["success"] is True
        assert result["data"] == {"test": "value"}
        assert result["error"] is None
        assert "timestamp" in result

    def test_error_response(self):
        result = _api_response(error="Something went wrong")
        assert result["success"] is False
        assert result["data"] is None
        assert result["error"] == "Something went wrong"
        assert "timestamp" in result


class TestCountryRouterImports:
    """Verify all country router functions can be imported."""

    def test_import_country_kpi(self):
        from app.routers.country import country_kpi_summary
        assert callable(country_kpi_summary)

    def test_import_ta_breakdown(self):
        from app.routers.country import ta_breakdown
        assert callable(ta_breakdown)

    def test_import_country_funnel(self):
        from app.routers.country import country_funnel
        assert callable(country_funnel)

    def test_import_country_comparison(self):
        from app.routers.country import country_comparison
        assert callable(country_comparison)

    def test_import_list_countries(self):
        from app.routers.country import list_countries
        assert callable(list_countries)
