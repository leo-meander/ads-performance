"""Country code to name mapping and date period helpers."""

from datetime import date, timedelta

# ISO 3166-1 alpha-2 → display name (only countries relevant to MEANDER Group campaigns)
COUNTRY_NAMES = {
    "AU": "Australia",
    "CA": "Canada",
    "CN": "China",
    "DE": "Germany",
    "HK": "Hong Kong",
    "ID": "Indonesia",
    "IN": "India",
    "JP": "Japan",
    "KR": "South Korea",
    "MY": "Malaysia",
    "PH": "Philippines",
    "SG": "Singapore",
    "TH": "Thailand",
    "TW": "Taiwan",
    "UK": "United Kingdom",
    "US": "United States",
    "VN": "Vietnam",
}


def country_name(code: str) -> str:
    """Return display name for country code, or the code itself if unknown."""
    if not code or len(code) != 2 or not code.isalpha():
        return None  # Invalid code — filter out
    return COUNTRY_NAMES.get(code.upper(), code.upper())


def is_valid_country(code: str) -> bool:
    """Check if a country code is a known 2-letter alpha code."""
    return bool(code) and code.upper() in COUNTRY_NAMES


def get_prev_period(date_from: date, date_to: date) -> tuple[date, date]:
    """Calculate the previous period of equal length for comparison."""
    period_days = (date_to - date_from).days + 1
    prev_to = date_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=period_days - 1)
    return prev_from, prev_to


def calc_change(current: float, previous: float) -> float | None:
    """Calculate percentage change. Returns None if no previous data."""
    if previous == 0:
        return None
    return round((current - previous) / previous, 4)
