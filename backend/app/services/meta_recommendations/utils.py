"""Shared helpers for Meta recommendation detectors.

Keep utilities narrow and stateless. Metrics helpers read from MetricsCache
at the campaign, ad_set, or ad level — the sync engine populates these rows
with omni_purchase-derived revenue, CTR, frequency, and CPM values.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ad import Ad
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.models.metrics import MetricsCache

# Meta playbook benchmarks (Section E.1: The Three Audience Temperatures).
# Used by LowCTR + HighCTRLowCVR detectors when no audience temperature can
# be inferred, we fall back to the moderate cold/warm band.
CTR_COLD_MIN = 0.008  # 0.8%
CTR_WARM_MIN = 0.015  # 1.5%
# CVR is benchmarked per-campaign against its own trailing 30-day rate
# rather than a fixed floor — hospitality CVR varies too much by branch,
# funnel stage, and offer mix for a single absolute number to be meaningful.
# We fire when the 7d CVR drops to less than half the 30d baseline.
CVR_ALERT_RATIO = 0.5
# Minimum 30d clicks before the baseline is treated as stable enough to
# compare against. Below this, the campaign is too noisy to call a regression.
CVR_BASELINE_MIN_CLICKS = 500

FUNNEL_STAGE_RE = re.compile(r"\[(TOF|MOF|BOF)\]", re.IGNORECASE)


def parse_funnel_stage(name: str | None) -> str | None:
    """Best-effort funnel stage extraction from the campaign name.

    Aligned with .claude/rules/parsing-rules.md — regex is the authoritative
    source; if the campaign row already has funnel_stage populated, prefer
    that.
    """
    if not name:
        return None
    m = FUNNEL_STAGE_RE.search(name)
    if not m:
        return None
    return m.group(1).upper()


# ── Metric aggregation helpers ───────────────────────────────────────────

def _aggregate(
    db: Session,
    *,
    campaign_id: str | None = None,
    ad_set_id: str | None = None,
    ad_id: str | None = None,
    metric: str,
    days: int,
    today: date | None = None,
) -> Decimal:
    """Sum a metric over the last N days at the requested granularity."""
    today = today or date.today()
    date_from = today - timedelta(days=days - 1)
    col = getattr(MetricsCache, metric)
    q = (
        db.query(func.coalesce(func.sum(col), 0))
        .filter(MetricsCache.platform == "meta")
        .filter(MetricsCache.date >= date_from)
        .filter(MetricsCache.date <= today)
    )
    if ad_id is not None:
        q = q.filter(MetricsCache.ad_id == ad_id)
    elif ad_set_id is not None:
        q = (
            q.filter(MetricsCache.ad_set_id == ad_set_id)
            .filter(MetricsCache.ad_id.is_(None))
        )
    elif campaign_id is not None:
        q = (
            q.filter(MetricsCache.campaign_id == campaign_id)
            .filter(MetricsCache.ad_set_id.is_(None))
            .filter(MetricsCache.ad_id.is_(None))
        )
    return Decimal(str(q.scalar() or 0))


def sum_campaign(db: Session, campaign_id: str, metric: str, days: int, today: date | None = None) -> Decimal:
    return _aggregate(db, campaign_id=campaign_id, metric=metric, days=days, today=today)


def sum_ad_set(db: Session, ad_set_id: str, metric: str, days: int, today: date | None = None) -> Decimal:
    return _aggregate(db, ad_set_id=ad_set_id, metric=metric, days=days, today=today)


def sum_ad(db: Session, ad_id: str, metric: str, days: int, today: date | None = None) -> Decimal:
    return _aggregate(db, ad_id=ad_id, metric=metric, days=days, today=today)


def avg_ad(db: Session, ad_id: str, metric: str, days: int, today: date | None = None) -> Decimal | None:
    """Average a ratio metric (CTR, frequency, CPM) over N days at ad level."""
    today = today or date.today()
    date_from = today - timedelta(days=days - 1)
    col = getattr(MetricsCache, metric)
    row = (
        db.query(func.avg(col))
        .filter(MetricsCache.platform == "meta")
        .filter(MetricsCache.ad_id == ad_id)
        .filter(MetricsCache.date >= date_from)
        .filter(MetricsCache.date <= today)
        .scalar()
    )
    return Decimal(str(row)) if row is not None else None


def snapshot_ad(db: Session, ad_id: str, today: date | None = None) -> dict[str, float]:
    """7d + 30d aggregate snapshot for a single ad."""
    today = today or date.today()
    out: dict[str, float] = {}
    for window in (7, 30):
        suffix = f"_{window}d"
        spend = sum_ad(db, ad_id, "spend", window, today)
        impr = sum_ad(db, ad_id, "impressions", window, today)
        clicks = sum_ad(db, ad_id, "clicks", window, today)
        conv = sum_ad(db, ad_id, "conversions", window, today)
        rev = sum_ad(db, ad_id, "revenue", window, today)
        out[f"spend{suffix}"] = float(spend)
        out[f"impressions{suffix}"] = float(impr)
        out[f"clicks{suffix}"] = float(clicks)
        out[f"conversions{suffix}"] = float(conv)
        out[f"revenue{suffix}"] = float(rev)
        out[f"ctr{suffix}"] = float(clicks / impr) if impr > 0 else 0.0
        out[f"roas{suffix}"] = float(rev / spend) if spend > 0 else 0.0
        out[f"cpa{suffix}"] = float(spend / conv) if conv > 0 else 0.0
    freq = avg_ad(db, ad_id, "frequency", 7, today)
    out["frequency_7d_avg"] = float(freq) if freq is not None else 0.0
    return out


def snapshot_campaign(db: Session, campaign_id: str, today: date | None = None) -> dict[str, float]:
    today = today or date.today()
    out: dict[str, float] = {}
    for window in (7, 30):
        suffix = f"_{window}d"
        spend = sum_campaign(db, campaign_id, "spend", window, today)
        impr = sum_campaign(db, campaign_id, "impressions", window, today)
        clicks = sum_campaign(db, campaign_id, "clicks", window, today)
        conv = sum_campaign(db, campaign_id, "conversions", window, today)
        rev = sum_campaign(db, campaign_id, "revenue", window, today)
        out[f"spend{suffix}"] = float(spend)
        out[f"impressions{suffix}"] = float(impr)
        out[f"clicks{suffix}"] = float(clicks)
        out[f"conversions{suffix}"] = float(conv)
        out[f"revenue{suffix}"] = float(rev)
        out[f"ctr{suffix}"] = float(clicks / impr) if impr > 0 else 0.0
        out[f"roas{suffix}"] = float(rev / spend) if spend > 0 else 0.0
        out[f"cvr{suffix}"] = float(conv / clicks) if clicks > 0 else 0.0
    return out


def ad_age_days(ad: Ad, today: date | None = None) -> int | None:
    """Ad age — falls back to created_at since Meta ads don't always have a start_date."""
    today = today or date.today()
    created = ad.created_at.date() if ad.created_at else None
    if created is None:
        return None
    return max(0, (today - created).days)


def campaign_funnel_stage(camp: Campaign) -> str | None:
    """Prefer sync-time parsed column; fall back to name regex."""
    if camp.funnel_stage and camp.funnel_stage != "Unknown":
        return camp.funnel_stage
    return parse_funnel_stage(camp.name)


def ad_set_targeted_country(ad_set: AdSet) -> str | None:
    """Return the ad_set's parsed ISO-2 country, skipping Unknown/empty."""
    c = (ad_set.country or "").strip().upper()
    if not c or c == "UNKNOWN":
        return None
    return c[:2]
