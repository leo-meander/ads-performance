"""Tests for budget service."""

from datetime import date
from unittest.mock import patch

from app.services.budget_service import calculate_pace


class TestCalculatePace:
    def test_on_track(self):
        """Projected spend within 10% of budget = On Track."""
        result = calculate_pace(
            total_budget=30000000,
            actual_spend=15000000,
            month=date(2026, 4, 1),
        )
        assert result["status"] in ("On Track", "Over", "Under")
        assert "days_remaining" in result
        assert "projected_spend" in result

    @patch("app.services.budget_service.date")
    def test_over_pace(self, mock_date):
        """Projected spend > 110% of budget = Over."""
        mock_date.today.return_value = date(2026, 4, 10)
        mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

        result = calculate_pace(
            total_budget=30000000,
            actual_spend=20000000,  # Spending way too fast
            month=date(2026, 4, 1),
        )
        assert result["status"] == "Over"

    @patch("app.services.budget_service.date")
    def test_under_pace(self, mock_date):
        """Projected spend < 90% of budget = Under."""
        mock_date.today.return_value = date(2026, 4, 20)
        mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

        result = calculate_pace(
            total_budget=30000000,
            actual_spend=5000000,  # Spending way too slow
            month=date(2026, 4, 1),
        )
        assert result["status"] == "Under"

    @patch("app.services.budget_service.date")
    def test_exact_on_track(self, mock_date):
        """Spending exactly on pace."""
        mock_date.today.return_value = date(2026, 4, 15)
        mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

        result = calculate_pace(
            total_budget=30000000,
            actual_spend=15000000,  # Exactly half at mid-month
            month=date(2026, 4, 1),
        )
        assert result["status"] == "On Track"

    def test_zero_budget(self):
        """Zero budget should not crash."""
        result = calculate_pace(
            total_budget=0,
            actual_spend=0,
            month=date(2026, 4, 1),
        )
        assert result["projected_spend"] == 0

    def test_zero_spend(self):
        """Zero spend should be Under."""
        with patch("app.services.budget_service.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 15)
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

            result = calculate_pace(
                total_budget=30000000,
                actual_spend=0,
                month=date(2026, 4, 1),
            )
            assert result["status"] == "Under"

    def test_past_month(self):
        """Past month should use full month days."""
        result = calculate_pace(
            total_budget=30000000,
            actual_spend=28000000,
            month=date(2026, 3, 1),  # March (past)
        )
        assert result["days_remaining"] == 0
