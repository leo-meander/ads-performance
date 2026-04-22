"""Google Analytics 4 Data API client.

SDK: google-analytics-data (v1beta)
Auth: Service Account JSON (must be granted Viewer role on each GA4 property).

Env vars:
    GA4_SERVICE_ACCOUNT_JSON_B64   Preferred. Base64-encoded full JSON.
                                    Used because some deploy target UIs
                                    mangle multi-line private_key fields.
    GA4_SERVICE_ACCOUNT_JSON       Fallback. Raw JSON string.

The client is built lazily on first use and cached at module level — the
service account credential + gRPC channel are both safe to reuse.
"""
from __future__ import annotations

import base64
import json
import logging
from datetime import date
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_client = None


def _load_credentials_info() -> dict[str, Any]:
    """Parse the service account JSON from env. Prefers base64 field."""
    b64 = (settings.GA4_SERVICE_ACCOUNT_JSON_B64 or "").strip()
    raw = (settings.GA4_SERVICE_ACCOUNT_JSON or "").strip()
    if b64:
        try:
            decoded = base64.b64decode(b64).decode("utf-8")
            return json.loads(decoded)
        except Exception as e:
            raise ValueError(f"GA4_SERVICE_ACCOUNT_JSON_B64 decode failed: {e}") from e
    if raw:
        return json.loads(raw)
    raise RuntimeError(
        "No GA4 service account configured — set GA4_SERVICE_ACCOUNT_JSON_B64 "
        "or GA4_SERVICE_ACCOUNT_JSON in env"
    )


def get_client():
    """Return a cached BetaAnalyticsDataClient."""
    global _client
    if _client is not None:
        return _client
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.oauth2 import service_account

    info = _load_credentials_info()
    creds = service_account.Credentials.from_service_account_info(info)
    _client = BetaAnalyticsDataClient(credentials=creds)
    logger.info("[ga4] client initialized for project=%s email=%s",
                info.get("project_id"), info.get("client_email"))
    return _client


def run_report(
    property_id: str,
    *,
    date_from: date,
    date_to: date,
    dimensions: list[str],
    metrics: list[str],
    dimension_filter: dict[str, Any] | None = None,
    limit: int = 100_000,
) -> list[dict[str, Any]]:
    """Run a GA4 report and return a list of {dim1, dim2, ..., metric1, ...} dicts.

    Numeric metrics are coerced to int or float. Missing / empty values come
    back as 0 or 0.0.
    """
    from google.analytics.data_v1beta.types import (
        DateRange,
        Dimension,
        FilterExpression,
        Metric,
        RunReportRequest,
    )

    client = get_client()
    prop = property_id if property_id.startswith("properties/") else f"properties/{property_id}"

    req = RunReportRequest(
        property=prop,
        date_ranges=[DateRange(start_date=date_from.isoformat(), end_date=date_to.isoformat())],
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        limit=limit,
    )
    if dimension_filter is not None:
        req.dimension_filter = FilterExpression(**dimension_filter)

    resp = client.run_report(req)

    out: list[dict[str, Any]] = []
    for row in resp.rows:
        item: dict[str, Any] = {}
        for i, d in enumerate(resp.dimension_headers):
            item[d.name] = row.dimension_values[i].value if i < len(row.dimension_values) else ""
        for i, m in enumerate(resp.metric_headers):
            raw_val = row.metric_values[i].value if i < len(row.metric_values) else ""
            # Coerce numeric: integer-metrics → int, else → float
            mtype = str(m.type_) if hasattr(m, "type_") else ""
            if "INTEGER" in mtype or "TYPE_INTEGER" in mtype:
                try:
                    item[m.name] = int(raw_val or 0)
                except (TypeError, ValueError):
                    item[m.name] = 0
            else:
                try:
                    item[m.name] = float(raw_val or 0)
                except (TypeError, ValueError):
                    item[m.name] = 0.0
        out.append(item)

    logger.info("[ga4] %s dims=%s metrics=%s rows=%d", prop, dimensions, metrics, len(out))
    return out
