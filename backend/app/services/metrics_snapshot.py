"""Shared metrics snapshot helper.

Used by rule_engine (audit log) and changelog (baseline capture). Keep the
output shape stable — it's persisted in JSON columns.
"""
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.metrics import MetricsCache


def _metric_base_filter(entity_id: str, entity_level: str):
    """Filter clauses for metric rollup at the given entity level."""
    if entity_level == "ad":
        return [MetricsCache.ad_id == entity_id]
    if entity_level == "ad_set":
        return [MetricsCache.ad_set_id == entity_id, MetricsCache.ad_id.is_(None)]
    # campaign
    return [
        MetricsCache.campaign_id == entity_id,
        MetricsCache.ad_set_id.is_(None),
        MetricsCache.ad_id.is_(None),
    ]


def get_metrics_snapshot(
    db: Session,
    entity_id: str,
    entity_level: str,
    days: int = 7,
) -> dict:
    """Return an aggregated metric snapshot for an entity over the last N days.

    Shape is stable and persisted to JSON columns in change_log_entries and
    action_logs — do not change field names without a data-migration plan.
    """
    date_from = date.today() - timedelta(days=days)
    filters = _metric_base_filter(entity_id, entity_level) + [
        MetricsCache.date >= date_from
    ]

    row = (
        db.query(
            func.sum(MetricsCache.spend).label("spend"),
            func.sum(MetricsCache.impressions).label("impressions"),
            func.sum(MetricsCache.clicks).label("clicks"),
            func.sum(MetricsCache.conversions).label("conversions"),
            func.sum(MetricsCache.revenue).label("revenue"),
        )
        .filter(*filters)
        .one()
    )

    spend = float(row.spend or 0)
    impressions = int(row.impressions or 0)
    clicks = int(row.clicks or 0)
    conversions = int(row.conversions or 0)
    revenue = float(row.revenue or 0)

    return {
        "days": days,
        "spend": spend,
        "impressions": impressions,
        "clicks": clicks,
        "conversions": conversions,
        "revenue": revenue,
        "roas": revenue / spend if spend > 0 else 0,
        "ctr": clicks / impressions if impressions > 0 else 0,
        "cpc": spend / clicks if clicks > 0 else 0,
        "cpa": spend / conversions if conversions > 0 else 0,
    }
