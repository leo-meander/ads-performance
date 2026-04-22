"""Cloudbeds PMS API client.

Cloudbeds exposes multiple auth flavours depending on how the API key was
generated (OAuth access token, personal API key, partner API key). We don't
yet know which one the user provisioned, so the probe() helper tries each
auth scheme against a harmless `getReservations` call and reports which one
works. The production fetch_reservations() then uses the proven scheme.

Docs: https://hotels.cloudbeds.com/api/v1.2/docs
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import requests

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = settings.CLOUDBEDS_API_BASE_URL.rstrip("/")

# Branch key → (api_key getter, property_id getter). Uses a getter so settings
# reloads (e.g. in tests) are picked up at call time, not import time.
_BRANCH_CREDS: dict[str, tuple[str, str]] = {
    "Saigon": ("CB_API_KEY_SAIGON", "CB_PROPERTY_ID_SAIGON"),
    "Taipei": ("CB_API_KEY_TAIPEI", "CB_PROPERTY_ID_TAIPEI"),
    "1948": ("CB_API_KEY_1948", "CB_PROPERTY_ID_1948"),
    "Osaka": ("CB_API_KEY_OSAKA", "CB_PROPERTY_ID_OSAKA"),
    "Oani": ("CB_API_KEY_OANI", "CB_PROPERTY_ID_OANI"),
}


def get_credentials(branch: str) -> tuple[str, str]:
    """Return (api_key, property_id) for a branch, raising if either missing."""
    mapping = _BRANCH_CREDS.get(branch)
    if not mapping:
        raise ValueError(
            f"Unknown Cloudbeds branch '{branch}'. "
            f"Known: {sorted(_BRANCH_CREDS)}"
        )
    api_key_attr, property_id_attr = mapping
    api_key = getattr(settings, api_key_attr, "") or ""
    property_id = getattr(settings, property_id_attr, "") or ""
    if not api_key or not property_id:
        raise ValueError(
            f"Cloudbeds credentials incomplete for branch '{branch}': "
            f"set {api_key_attr} and {property_id_attr}"
        )
    return api_key, property_id


def _auth_variants(api_key: str) -> list[dict[str, Any]]:
    """Every auth header shape we've seen Cloudbeds accept. Tried in order."""
    return [
        {
            "label": "authorization_bearer",
            "headers": {"Authorization": f"Bearer {api_key}"},
        },
        {
            "label": "x_api_key",
            "headers": {"x-api-key": api_key},
        },
        {
            "label": "authorization_bare",
            "headers": {"Authorization": api_key},
        },
    ]


def _short(body: Any, limit: int = 800) -> str:
    """Stringify a response body capped to a readable length for diagnostics."""
    text = str(body)
    if len(text) > limit:
        return text[:limit] + "...<truncated>"
    return text


def probe(branch: str, date_from: date, date_to: date) -> dict:
    """Hit getReservations with each auth flavour and report which one works.

    Used only by the /internal/cloudbeds-ping diagnostic endpoint — production
    sync paths should use fetch_reservations() directly once we've confirmed
    which auth style works.
    """
    api_key, property_id = get_credentials(branch)
    url = f"{BASE_URL}/getReservations"
    params = {
        "propertyID": property_id,
        "checkInFrom": date_from.isoformat(),
        "checkInTo": date_to.isoformat(),
        "pageNumber": 1,
        "pageSize": 3,
    }
    attempts: list[dict] = []
    chosen: str | None = None
    sample_reservation: dict | None = None
    sample_top_level_keys: list[str] | None = None

    for variant in _auth_variants(api_key):
        entry: dict[str, Any] = {"auth": variant["label"]}
        try:
            resp = requests.get(url, headers=variant["headers"], params=params, timeout=30)
            entry["status"] = resp.status_code
            entry["content_type"] = resp.headers.get("content-type")
            try:
                body = resp.json()
            except ValueError:
                body = None
                entry["body_text"] = _short(resp.text)
            if body is not None:
                entry["body_preview"] = _short(body)
                if isinstance(body, dict) and body.get("success") is True:
                    chosen = variant["label"]
                    entry["ok"] = True
                    data = body.get("data") or []
                    entry["total"] = body.get("total") or body.get("count")
                    entry["sample_count"] = len(data) if isinstance(data, list) else None
                    if isinstance(data, list) and data:
                        sample_reservation = data[0]
                        if isinstance(sample_reservation, dict):
                            sample_top_level_keys = sorted(sample_reservation.keys())
                    attempts.append(entry)
                    break
                else:
                    entry["ok"] = False
        except requests.RequestException as e:
            entry["error"] = str(e)
        attempts.append(entry)

    return {
        "branch": branch,
        "base_url": BASE_URL,
        "property_id": property_id,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "chosen_auth": chosen,
        "attempts": attempts,
        "sample_reservation": sample_reservation,
        "sample_top_level_keys": sample_top_level_keys,
    }


def fetch_reservations(
    branch: str,
    date_from: date,
    date_to: date,
    page_size: int = 100,
    auth_variant: str = "authorization_bearer",
) -> list[dict]:
    """Fetch every reservation for a branch in the given checkIn range.

    Cloudbeds pagination uses pageNumber (1-indexed) + pageSize. We loop until
    the returned page is smaller than page_size or data is empty.
    """
    api_key, property_id = get_credentials(branch)
    variant = next(
        (v for v in _auth_variants(api_key) if v["label"] == auth_variant),
        None,
    )
    if not variant:
        raise ValueError(f"Unknown auth_variant '{auth_variant}'")

    url = f"{BASE_URL}/getReservations"
    out: list[dict] = []
    page = 1
    while True:
        params = {
            "propertyID": property_id,
            "checkInFrom": date_from.isoformat(),
            "checkInTo": date_to.isoformat(),
            "pageNumber": page,
            "pageSize": page_size,
        }
        resp = requests.get(url, headers=variant["headers"], params=params, timeout=60)
        resp.raise_for_status()
        body = resp.json()
        if not body.get("success"):
            raise RuntimeError(f"Cloudbeds error: {body.get('message') or body}")
        data = body.get("data") or []
        if not isinstance(data, list):
            break
        out.extend(data)
        if len(data) < page_size:
            break
        page += 1

    logger.info(
        "Fetched %d Cloudbeds reservations for branch=%s (%s → %s)",
        len(out), branch, date_from, date_to,
    )
    return out
