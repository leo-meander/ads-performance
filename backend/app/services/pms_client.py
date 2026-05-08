"""PMS (Property Management System) API client.

Fetches reservation data + hotel intelligence (OCC, ADR, country trends,
holidays, events, KPI achievement) from the HID Dashboard public API.
Uses requests (sync) for Celery task compatibility.
"""

import logging
from datetime import date
from typing import Any

import requests

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = settings.PMS_API_BASE_URL.rstrip("/")
RESERVATIONS_ENDPOINT = f"{BASE_URL}/api/public/reservations"

# All public-API endpoints share the same X-API-Key auth + envelope shape.
PUBLIC_BASE = f"{BASE_URL}/api/public"
DEFAULT_TIMEOUT = 30


def _get(path: str, params: dict | None = None) -> Any:
    """GET /api/public{path} with X-API-Key, return body['data'] or raise.

    Centralised so every helper inherits the same auth, error shape, and
    logging — keep new endpoints one-liners.
    """
    url = f"{PUBLIC_BASE}{path}"
    headers = {"X-API-Key": settings.PMS_API_KEY}
    try:
        resp = requests.get(
            url, headers=headers, params=params or {}, timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException:
        logger.exception("HID public API request failed: %s params=%s", url, params)
        raise

    body = resp.json()
    if not body.get("success", True):
        error_msg = body.get("error", "Unknown HID API error")
        logger.error("HID API returned error: %s (path=%s)", error_msg, path)
        raise RuntimeError(f"HID API error: {error_msg}")
    return body.get("data")


def fetch_reservations(
    date_from: date,
    date_to: date,
    branch_id: str | None = None,
    limit: int = 1000,
) -> list[dict]:
    """Fetch all reservations from PMS API with pagination.

    Args:
        date_from: Start date for check-in filter.
        date_to: End date for check-in filter.
        branch_id: Optional branch UUID filter.
        limit: Max results per page (API max 1000).

    Returns:
        List of reservation dicts from the API.
    """
    headers = {"X-API-Key": settings.PMS_API_KEY}
    all_reservations: list[dict] = []
    offset = 0

    while True:
        params = {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "limit": limit,
            "offset": offset,
        }
        if branch_id:
            params["branch_id"] = branch_id

        try:
            resp = requests.get(
                RESERVATIONS_ENDPOINT,
                headers=headers,
                params=params,
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            body = resp.json()
        except requests.RequestException:
            logger.exception(
                "PMS API request failed (offset=%d, date_from=%s, date_to=%s)",
                offset, date_from, date_to,
            )
            raise

        if not body.get("success"):
            error_msg = body.get("error", "Unknown PMS API error")
            logger.error("PMS API returned error: %s", error_msg)
            raise RuntimeError(f"PMS API error: {error_msg}")

        data = body.get("data", {})
        reservations = data.get("reservations", [])
        total = data.get("total", 0)

        all_reservations.extend(reservations)
        offset += limit

        if offset >= total or not reservations:
            break

    logger.info(
        "Fetched %d reservations from PMS (%s to %s)",
        len(all_reservations), date_from, date_to,
    )
    return all_reservations


# ── Branches & Capacity ──────────────────────────────────────────────────────

def fetch_branches() -> list[dict]:
    """List active branches with capacity (total_rooms, room_count, dorm_count)."""
    return _get("/branches") or []


# ── Metrics: Daily / Weekly / Monthly / OTA Mix ──────────────────────────────

def fetch_daily_metrics(
    branch_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """Daily OCC, ADR, RevPAR, revenue per branch. Defaults to last 30 days."""
    params: dict = {}
    if branch_id:
        params["branch_id"] = branch_id
    if date_from:
        params["date_from"] = date_from.isoformat()
    if date_to:
        params["date_to"] = date_to.isoformat()
    return _get("/metrics/daily", params) or []


def fetch_weekly_metrics(
    branch_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """Weekly OCC/ADR/RevPAR/revenue rollup."""
    params: dict = {}
    if branch_id:
        params["branch_id"] = branch_id
    if date_from:
        params["date_from"] = date_from.isoformat()
    if date_to:
        params["date_to"] = date_to.isoformat()
    return _get("/metrics/weekly", params) or []


def fetch_monthly_metrics(
    branch_id: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[dict]:
    """Monthly rollup with country breakdown per month."""
    params: dict = {}
    if branch_id:
        params["branch_id"] = branch_id
    if year_from:
        params["year_from"] = year_from
    if year_to:
        params["year_to"] = year_to
    return _get("/metrics/monthly", params) or []


def fetch_ota_mix(
    branch_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """Channel mix — Direct vs each OTA, by booking count and revenue."""
    params: dict = {}
    if branch_id:
        params["branch_id"] = branch_id
    if date_from:
        params["date_from"] = date_from.isoformat()
    if date_to:
        params["date_to"] = date_to.isoformat()
    return _get("/metrics/ota-mix", params) or []


def fetch_country_yoy_insights(
    year: int | None = None,
    month: int | None = None,
    branch_id: str | None = None,
    date_type: str = "check_in",
) -> dict:
    """Country YoY comparison — current year vs previous year."""
    params: dict = {"date_type": date_type}
    if year:
        params["year"] = year
    if month:
        params["month"] = month
    if branch_id:
        params["branch_id"] = branch_id
    return _get("/metrics/country-yoy-insights", params) or {}


def fetch_country_reservations(
    view: str = "monthly",
    branch_id: str | None = None,
    limit: int = 100,
    date_type: str = "check_in",
) -> dict:
    """Top countries with reservation trend over 7 weeks/months."""
    params: dict = {"view": view, "limit": limit, "date_type": date_type}
    if branch_id:
        params["branch_id"] = branch_id
    return _get("/metrics/country-reservations", params) or {}


# ── Lead Time (per-country booking window) ───────────────────────────────────

def fetch_lead_time(
    branch_id: str | None = None,
    country_code: str | None = None,
    days_back: int = 180,
) -> dict:
    """Average + median booking lead time per country.

    Used by the recommendation framework to compute the target stay window:
        target_period = today + lead_time +/- 7 days
    """
    params: dict = {"days_back": days_back}
    if branch_id:
        params["branch_id"] = branch_id
    if country_code:
        params["country_code"] = country_code.upper()
    return _get("/lead-time", params) or {}


# ── Events & Holidays ────────────────────────────────────────────────────────

def fetch_events(
    branch_id: str | None = None,
    city: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    """Local events (festivals, conferences) that drive demand."""
    params: dict = {}
    if branch_id:
        params["branch_id"] = branch_id
    if city:
        params["city"] = city
    if date_from:
        params["date_from"] = date_from.isoformat()
    if date_to:
        params["date_to"] = date_to.isoformat()
    return _get("/events", params) or []


def fetch_upcoming_holidays(days: int = 60) -> list[dict]:
    """Upcoming holiday windows across all source markets — next N days."""
    return _get("/holidays/upcoming", {"days": days}) or []


def fetch_country_holidays(country_code: str) -> dict:
    """Full holiday detail for a source country (e.g. VN, JP, TW, KR, HK)."""
    return _get(f"/holidays/country/{country_code.upper()}") or {}


# ── Country Ranking & Trend ──────────────────────────────────────────────────

def fetch_country_ranking(
    branch_id: str | None = None,
    top_n: int = 30,
) -> list[dict]:
    """Country potential ranking with Hot/Warm/Cold tiers."""
    params: dict = {"top_n": top_n}
    if branch_id:
        params["branch_id"] = branch_id
    return _get("/countries/ranking", params) or []


def fetch_country_trend(
    country_code: str,
    branch_id: str | None = None,
    months: int = 24,
) -> dict:
    """Monthly booking trend for a specific country over the past N months."""
    params: dict = {"months": months}
    if branch_id:
        params["branch_id"] = branch_id
    return _get(f"/countries/{country_code.upper()}/trend", params) or {}


# ── Country Intelligence (richest single source for framework step 5) ────────

def fetch_country_intel(branch_id: str | None = None) -> list[dict]:
    """
    Per-branch country intelligence: top volume + top growth + KOL/Ads
    coverage + government visitor forecast + room-type stats.
    """
    params: dict = {}
    if branch_id:
        params["branch_id"] = branch_id
    return _get("/insights/country-intel", params) or []


# ── KPI Achievement (high/low OCC analog for budget rules) ───────────────────

def fetch_kpi_achievement(
    date_from: date,
    date_to: date,
    branch_id: str | None = None,
) -> list[dict]:
    """Revenue actual vs target for an arbitrary date range."""
    params: dict = {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
    }
    if branch_id:
        params["branch_id"] = branch_id
    return _get("/kpi/period-achievement", params) or []
