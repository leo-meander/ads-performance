"""Conversion funnel recommendation analyzer.

Detects which step of the funnel (Impression → Click → Search → Add to cart →
Checkout → Booking) is leaking the most volume vs the previous period, broken
down by Channel × Country × Funnel stage × TA.

Each finding is mapped to a "root cause" with a deep-link to the page where the
user can investigate the root cause:

    Impression → Click   → ad creative (CTR)        → /creative
    Click → Search       → landing page (LP load + relevance)  → /landing-pages
    Search → Add to cart → offer / availability     → /country
    Add to cart → Checkout → cart UX, payment    → /country
    Checkout → Booking   → payment friction       → /country

The output is computed dynamically (not stored) so it always reflects the
current sync state of metrics_cache.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.ad import Ad
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.models.landing_page import LandingPage
from app.models.landing_page_ad_link import LandingPageAdLink
from app.models.metrics import MetricsCache
from app.services.country_utils import calc_change, country_name, get_prev_period


STEP_KEYS = ["impressions", "clicks", "searches", "add_to_cart", "checkouts", "bookings"]
STEP_LABELS = ["Impression", "Click", "Search", "Add to Cart", "Checkout", "Booking"]

# Map a funnel transition to (key, root cause label, deep-link target).
# Index i means "from STEP_KEYS[i] to STEP_KEYS[i+1]".
TRANSITION_META = [
    {
        "from": "impressions", "to": "clicks",
        "name": "Impression → Click",
        "root_cause": "Ad creative (CTR)",
        "hint": "Hook / thumbnail / opening 3s likely weak. Check losing ad names in Creative Library.",
        "target": "creative",
        "metric_label": "CTR",
    },
    {
        "from": "clicks", "to": "searches",
        "name": "Click → Search",
        "root_cause": "Landing page (load speed + relevance)",
        "hint": "Landing page hero / load time / message-match issue. Open the LP performance dashboard.",
        "target": "landing_page",
        "metric_label": "Search rate",
    },
    {
        "from": "searches", "to": "add_to_cart",
        "name": "Search → Add to Cart",
        "root_cause": "Offer / availability / pricing",
        "hint": "Search ran but no ATC: dates blocked, price too high, or wrong room shown. Check campaign + LP offer.",
        "target": "country",
        "metric_label": "ATC rate",
    },
    {
        "from": "add_to_cart", "to": "checkouts",
        "name": "Add to Cart → Checkout",
        "root_cause": "Cart UX / payment options",
        "hint": "Friction between cart and checkout — guest field count, payment selection, or shipping/tax surprise.",
        "target": "country",
        "metric_label": "Checkout rate",
    },
    {
        "from": "checkouts", "to": "bookings",
        "name": "Checkout → Booking",
        "root_cause": "Payment / form failures",
        "hint": "Checkout started but didn't book — payment gateway errors, OTP timeout, or required fields missing.",
        "target": "country",
        "metric_label": "Book rate",
    },
]


@dataclass
class FunnelBucket:
    """Aggregated funnel for one (channel, country, funnel_stage, ta) slice."""
    platform: str | None = None
    country: str | None = None
    funnel_stage: str | None = None
    ta: str | None = None
    impressions: int = 0
    clicks: int = 0
    searches: int = 0
    add_to_cart: int = 0
    checkouts: int = 0
    bookings: int = 0

    def get(self, key: str) -> int:
        return int(getattr(self, key, 0) or 0)


@dataclass
class Recommendation:
    rec_id: str
    severity: str
    score: float
    breakdown_dim: str
    dimension_label: str
    dimension_value: dict
    from_stage: str
    to_stage: str
    transition_name: str
    root_cause: str
    hint: str
    metric_label: str
    current_volume_in: int
    current_volume_out: int
    current_conversion_rate: float | None
    prev_conversion_rate: float | None
    conversion_rate_change: float | None
    current_drop_off: float | None
    prev_drop_off: float | None
    drop_off_change: float | None
    funnel_snapshot: list[dict]
    deep_link_target: str
    deep_link_url: str
    top_contributors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "rec_id": self.rec_id,
            "severity": self.severity,
            "score": round(self.score, 3),
            "breakdown_dim": self.breakdown_dim,
            "dimension_label": self.dimension_label,
            "dimension_value": self.dimension_value,
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
            "transition_name": self.transition_name,
            "root_cause": self.root_cause,
            "hint": self.hint,
            "metric_label": self.metric_label,
            "current_volume_in": self.current_volume_in,
            "current_volume_out": self.current_volume_out,
            "current_conversion_rate": _round(self.current_conversion_rate, 4),
            "prev_conversion_rate": _round(self.prev_conversion_rate, 4),
            "conversion_rate_change": _round(self.conversion_rate_change, 4),
            "current_drop_off": _round(self.current_drop_off, 4),
            "prev_drop_off": _round(self.prev_drop_off, 4),
            "drop_off_change": _round(self.drop_off_change, 4),
            "funnel_snapshot": self.funnel_snapshot,
            "deep_link_target": self.deep_link_target,
            "deep_link_url": self.deep_link_url,
            "top_contributors": self.top_contributors,
        }


def _round(v: float | None, digits: int) -> float | None:
    return None if v is None else round(v, digits)


# ---------- bucket aggregation ----------


def _group_buckets(
    db: Session,
    d_from: date,
    d_to: date,
    platform: str | None,
    account_ids: list[str] | None,
) -> list[FunnelBucket]:
    """Pull metrics_cache joined to campaign+adset, grouped by all 4 dimensions.

    Returns one FunnelBucket per (platform, country, funnel_stage, ta) cell.
    Caller can roll these up to any single dimension by summing.
    """
    q = (
        db.query(
            MetricsCache.platform.label("platform"),
            AdSet.country.label("country"),
            Campaign.funnel_stage.label("funnel_stage"),
            Campaign.ta.label("ta"),
            func.sum(MetricsCache.impressions).label("impressions"),
            func.sum(MetricsCache.clicks).label("clicks"),
            func.sum(MetricsCache.searches).label("searches"),
            func.sum(MetricsCache.add_to_cart).label("add_to_cart"),
            func.sum(MetricsCache.checkouts).label("checkouts"),
            func.sum(MetricsCache.conversions).label("bookings"),
        )
        .join(Campaign, Campaign.id == MetricsCache.campaign_id)
        .join(AdSet, AdSet.id == MetricsCache.ad_set_id)
        .filter(MetricsCache.ad_id.is_(None))
        .filter(MetricsCache.date >= d_from, MetricsCache.date <= d_to)
        .filter(
            AdSet.country.isnot(None),
            AdSet.country != "Unknown",
            (func.length(AdSet.country) == 2) | (AdSet.country == "ALL"),
        )
    )
    if platform:
        q = q.filter(MetricsCache.platform == platform)
    if account_ids is not None:
        q = q.filter(Campaign.account_id.in_(account_ids or ["__no_match__"]))

    q = q.group_by(MetricsCache.platform, AdSet.country, Campaign.funnel_stage, Campaign.ta)

    buckets: list[FunnelBucket] = []
    for row in q.all():
        buckets.append(FunnelBucket(
            platform=row.platform,
            country=row.country,
            funnel_stage=row.funnel_stage,
            ta=row.ta,
            impressions=int(row.impressions or 0),
            clicks=int(row.clicks or 0),
            searches=int(row.searches or 0),
            add_to_cart=int(row.add_to_cart or 0),
            checkouts=int(row.checkouts or 0),
            bookings=int(row.bookings or 0),
        ))
    return buckets


def _rollup(buckets: Iterable[FunnelBucket], dim: str | None) -> dict[str, FunnelBucket]:
    """Roll buckets up to a single dimension key.

    dim values:
      - "channel"   → group by platform
      - "country"   → group by country
      - "funnel"    → group by funnel_stage
      - "ta"        → group by ta
      - None        → single "Overall" bucket
    """
    out: dict[str, FunnelBucket] = {}
    for b in buckets:
        if dim is None:
            key = "__all__"
        elif dim == "channel":
            key = (b.platform or "unknown").lower()
        elif dim == "country":
            key = (b.country or "Unknown").upper()
        elif dim == "funnel":
            key = (b.funnel_stage or "Unknown").upper()
        elif dim == "ta":
            key = b.ta or "Unknown"
        else:
            raise ValueError(f"unknown dim: {dim}")

        if key not in out:
            out[key] = FunnelBucket(
                platform=b.platform if dim == "channel" else None,
                country=b.country if dim == "country" else None,
                funnel_stage=b.funnel_stage if dim == "funnel" else None,
                ta=b.ta if dim == "ta" else None,
            )
        agg = out[key]
        for sk in STEP_KEYS:
            setattr(agg, sk, agg.get(sk) + b.get(sk))
    return out


# ---------- finding scoring ----------


def _build_finding(
    *,
    breakdown_dim: str,
    dimension_label: str,
    key: str,
    cur: FunnelBucket,
    prev: FunnelBucket,
    overall_cur: FunnelBucket,
) -> list[Recommendation]:
    """For one slice, score every transition and return any that's a problem.

    A transition is a "problem" if:
      - current volume_in is meaningful (>=100 impressions for img→click, lower
        thresholds for downstream stages where natural volume is smaller),
      - AND either:
          a) the current conversion rate dropped vs prev period, OR
          b) the current drop-off is at least 2x worse than the slice's share of
             overall funnel (i.e. this slice is a hot spot now even without prev
             data).
    """
    findings: list[Recommendation] = []

    for i, meta in enumerate(TRANSITION_META):
        from_key = meta["from"]
        to_key = meta["to"]
        v_in = cur.get(from_key)
        v_out = cur.get(to_key)
        prev_in = prev.get(from_key) if prev else 0
        prev_out = prev.get(to_key) if prev else 0

        # Volume gate per stage (filters out noisy tiny slices).
        gate = {
            "impressions": 1000,  # need real impression volume
            "clicks": 50,
            "searches": 20,
            "add_to_cart": 10,
            "checkouts": 5,
        }[from_key]
        if v_in < gate:
            continue

        cur_cr = (v_out / v_in) if v_in > 0 else None
        prev_cr = (prev_out / prev_in) if prev_in > 0 else None
        cur_drop = (1 - cur_cr) if cur_cr is not None else None
        prev_drop = (1 - prev_cr) if prev_cr is not None else None

        cr_change = calc_change(cur_cr or 0, prev_cr or 0) if (cur_cr is not None and prev_cr is not None and prev_cr > 0) else None
        drop_change = calc_change(cur_drop or 0, prev_drop or 0) if (cur_drop is not None and prev_drop is not None and prev_drop > 0) else None

        # Slice's share of overall losses at this transition (so we surface the
        # slice that's *contributing the most absolute drop*, not just one with
        # a bad rate but tiny volume).
        overall_in = overall_cur.get(from_key)
        overall_out = overall_cur.get(to_key)
        overall_drop = (1 - (overall_out / overall_in)) if overall_in > 0 else 0
        slice_lost_volume = max(v_in - v_out, 0)  # absolute volume lost

        # Score components
        # 1) drop_change_score: how much worse vs prev (positive = worse)
        drop_change_score = max(drop_change or 0, 0)
        # 2) excess_drop_score: how much higher than overall baseline drop
        excess = (cur_drop - overall_drop) if (cur_drop is not None) else 0
        excess_drop_score = max(excess, 0)
        # 3) volume_score: log-ish so a slice with 10× volume isn't 10× more
        #    important than one with great rate
        from math import log10
        vol_score = log10(max(slice_lost_volume, 1)) / 6  # ~0..1 for 1..1M

        score = (
            drop_change_score * 0.55
            + excess_drop_score * 0.30
            + vol_score * 0.15
        )

        # Filter out non-problems: must have either (degraded vs prev) OR
        # (notably worse than overall baseline).
        is_degraded = (drop_change_score >= 0.05)  # 5%+ worse vs prev
        is_hotspot = (excess_drop_score >= 0.05) and (slice_lost_volume >= gate)
        if not (is_degraded or is_hotspot):
            continue

        # Severity buckets
        if score >= 0.5 or drop_change_score >= 0.30:
            severity = "critical"
        elif score >= 0.25 or drop_change_score >= 0.15:
            severity = "warning"
        else:
            severity = "info"

        # Funnel snapshot for the card chart
        snapshot = []
        for j, sk in enumerate(STEP_KEYS):
            snapshot.append({
                "key": sk,
                "label": STEP_LABELS[j],
                "value": cur.get(sk),
                "is_bottleneck_in": (sk == from_key),
                "is_bottleneck_out": (sk == to_key),
            })

        findings.append(Recommendation(
            rec_id=f"{breakdown_dim}:{key}:{from_key}->{to_key}",
            severity=severity,
            score=score,
            breakdown_dim=breakdown_dim,
            dimension_label=dimension_label,
            dimension_value={
                "platform": cur.platform,
                "country": cur.country,
                "funnel_stage": cur.funnel_stage,
                "ta": cur.ta,
                "key": key,
            },
            from_stage=from_key,
            to_stage=to_key,
            transition_name=meta["name"],
            root_cause=meta["root_cause"],
            hint=meta["hint"],
            metric_label=meta["metric_label"],
            current_volume_in=v_in,
            current_volume_out=v_out,
            current_conversion_rate=cur_cr,
            prev_conversion_rate=prev_cr,
            conversion_rate_change=cr_change,
            current_drop_off=cur_drop,
            prev_drop_off=prev_drop,
            drop_off_change=drop_change,
            funnel_snapshot=snapshot,
            deep_link_target=meta["target"],
            deep_link_url="",  # filled later once dimension context is known
        ))

    return findings


def _build_deep_link(rec: Recommendation, period_preset: str = "7d", branches: str | None = None) -> str:
    """Build the URL the recommendation card's CTA navigates to."""
    qp: dict[str, str] = {}
    dv = rec.dimension_value or {}
    platform = dv.get("platform")
    country = dv.get("country")
    funnel_stage = dv.get("funnel_stage")
    ta = dv.get("ta")

    if rec.deep_link_target == "creative":
        if platform == "meta" or platform is None:
            # Creative library is Meta-only.
            pass
        if country and len(country) == 2:
            qp["country"] = country
        if ta and ta != "Unknown":
            qp["ta"] = ta
        if branches:
            qp["branches"] = branches
        # Filter to losing combos so the user lands on the worst CTR ads.
        qp["verdict"] = "LOSE"
        path = "/creative"
    elif rec.deep_link_target == "landing_page":
        if branches:
            qp["branches"] = branches
        if country and len(country) == 2:
            qp["country"] = country
        qp["range"] = period_preset
        path = "/landing-pages"
    else:
        # Default: drill into Country Dashboard with the same filters
        path = "/country"
        if country and len(country) == 2:
            qp["country"] = country
        if platform:
            qp["platform"] = platform
        if funnel_stage and funnel_stage != "Unknown":
            qp["funnel"] = funnel_stage
        if branches:
            qp["branches"] = branches
        qp["range"] = period_preset

    if not qp:
        return path
    qs = "&".join(f"{k}={v}" for k, v in qp.items())
    return f"{path}?{qs}"


# ---------- top contributors ----------


def _ad_contributors(
    db: Session,
    *,
    d_from: date,
    d_to: date,
    platform: str | None,
    country: str | None,
    funnel_stage: str | None,
    ta: str | None,
    account_ids: list[str] | None,
    limit: int = 5,
) -> list[dict]:
    """Top worst Meta ad-name contributors at the Impression→Click step."""
    q = (
        db.query(
            Ad.id.label("ad_id"),
            Ad.name.label("ad_name"),
            Ad.account_id.label("account_id"),
            func.sum(MetricsCache.impressions).label("impressions"),
            func.sum(MetricsCache.clicks).label("clicks"),
            func.sum(MetricsCache.spend).label("spend"),
        )
        .join(MetricsCache, MetricsCache.ad_id == Ad.id)
        .join(AdSet, AdSet.id == Ad.ad_set_id)
        .join(Campaign, Campaign.id == Ad.campaign_id)
        .filter(MetricsCache.ad_id.isnot(None))
        .filter(MetricsCache.date >= d_from, MetricsCache.date <= d_to)
    )
    if platform:
        q = q.filter(Ad.platform == platform)
    if country and len(country) == 2:
        q = q.filter(AdSet.country == country.upper())
    if funnel_stage and funnel_stage != "Unknown":
        q = q.filter(Campaign.funnel_stage == funnel_stage.upper())
    if ta and ta != "Unknown":
        q = q.filter(Campaign.ta == ta)
    if account_ids is not None:
        q = q.filter(Ad.account_id.in_(account_ids or ["__no_match__"]))

    q = q.group_by(Ad.id, Ad.name, Ad.account_id)
    rows = q.all()

    items: list[dict] = []
    for r in rows:
        imps = int(r.impressions or 0)
        clicks = int(r.clicks or 0)
        if imps < 500:
            continue
        ctr = clicks / imps if imps > 0 else 0
        items.append({
            "kind": "ad",
            "id": r.ad_id,
            "name": r.ad_name,
            "impressions": imps,
            "clicks": clicks,
            "ctr": round(ctr, 4),
            "spend": float(r.spend or 0),
            "account_id": r.account_id,
        })
    items.sort(key=lambda x: (x["ctr"], -x["impressions"]))
    return items[:limit]


def _landing_page_contributors(
    db: Session,
    *,
    d_from: date,
    d_to: date,
    platform: str | None,
    country: str | None,
    account_ids: list[str] | None,
    limit: int = 5,
) -> list[dict]:
    """Top worst landing pages at Click → Search.

    Aggregates impressions / clicks per LP via the join table, sorted by lowest
    "search rate" (clicks → searches happens off-platform on the LP itself, but
    this list gives the user the LPs that are absorbing the most clicks; pair
    with the per-LP Clarity dashboard for the search-rate detail).
    """
    q = (
        db.query(
            LandingPage.id.label("lp_id"),
            LandingPage.title.label("title"),
            LandingPage.domain.label("domain"),
            LandingPage.slug.label("slug"),
            func.sum(MetricsCache.impressions).label("impressions"),
            func.sum(MetricsCache.clicks).label("clicks"),
            func.sum(MetricsCache.spend).label("spend"),
        )
        .join(LandingPageAdLink, LandingPageAdLink.landing_page_id == LandingPage.id)
        .join(MetricsCache, MetricsCache.ad_id == LandingPageAdLink.ad_id)
        .join(AdSet, AdSet.id == MetricsCache.ad_set_id)
        .filter(MetricsCache.ad_id.isnot(None))
        .filter(LandingPageAdLink.ad_id.isnot(None))
        .filter(MetricsCache.date >= d_from, MetricsCache.date <= d_to)
    )
    if platform:
        q = q.filter(LandingPageAdLink.platform == platform)
    if country and len(country) == 2:
        q = q.filter(AdSet.country == country.upper())
    if account_ids is not None:
        q = q.join(Ad, Ad.id == MetricsCache.ad_id).filter(Ad.account_id.in_(account_ids or ["__no_match__"]))

    q = q.group_by(LandingPage.id, LandingPage.title, LandingPage.domain, LandingPage.slug)
    rows = q.all()

    items: list[dict] = []
    for r in rows:
        imps = int(r.impressions or 0)
        clicks = int(r.clicks or 0)
        if clicks < 30:
            continue
        items.append({
            "kind": "landing_page",
            "id": r.lp_id,
            "name": r.title or f"{r.domain}/{r.slug or ''}",
            "url": f"https://{r.domain}/{r.slug or ''}",
            "impressions": imps,
            "clicks": clicks,
            "ctr": round(clicks / imps, 4) if imps > 0 else 0,
            "spend": float(r.spend or 0),
        })
    items.sort(key=lambda x: -x["clicks"])
    return items[:limit]


def _campaign_contributors(
    db: Session,
    *,
    d_from: date,
    d_to: date,
    platform: str | None,
    country: str | None,
    funnel_stage: str | None,
    ta: str | None,
    account_ids: list[str] | None,
    metric: str,  # which step to optimize for
    limit: int = 5,
) -> list[dict]:
    """Top campaigns where the requested step is leaking the most."""
    q = (
        db.query(
            Campaign.id.label("campaign_id"),
            Campaign.name.label("campaign_name"),
            AdAccount.account_name.label("account_name"),
            Campaign.platform.label("platform"),
            func.sum(MetricsCache.impressions).label("impressions"),
            func.sum(MetricsCache.clicks).label("clicks"),
            func.sum(MetricsCache.searches).label("searches"),
            func.sum(MetricsCache.add_to_cart).label("add_to_cart"),
            func.sum(MetricsCache.checkouts).label("checkouts"),
            func.sum(MetricsCache.conversions).label("bookings"),
            func.sum(MetricsCache.spend).label("spend"),
        )
        .join(MetricsCache, MetricsCache.campaign_id == Campaign.id)
        .join(AdSet, AdSet.id == MetricsCache.ad_set_id)
        .join(AdAccount, AdAccount.id == Campaign.account_id)
        .filter(MetricsCache.ad_id.is_(None))
        .filter(MetricsCache.date >= d_from, MetricsCache.date <= d_to)
    )
    if platform:
        q = q.filter(Campaign.platform == platform)
    if country and len(country) == 2:
        q = q.filter(AdSet.country == country.upper())
    if funnel_stage and funnel_stage != "Unknown":
        q = q.filter(Campaign.funnel_stage == funnel_stage.upper())
    if ta and ta != "Unknown":
        q = q.filter(Campaign.ta == ta)
    if account_ids is not None:
        q = q.filter(Campaign.account_id.in_(account_ids or ["__no_match__"]))

    q = q.group_by(Campaign.id, Campaign.name, AdAccount.account_name, Campaign.platform)
    rows = q.all()

    # Pick the upstream step that maps to this metric
    metric_to_in = {
        "searches": "impressions",
        "add_to_cart": "searches",
        "checkouts": "add_to_cart",
        "bookings": "checkouts",
    }
    in_key = metric_to_in.get(metric, "impressions")

    items: list[dict] = []
    for r in rows:
        in_v = int(getattr(r, in_key) or 0)
        out_v = int(getattr(r, metric) or 0)
        gate = {"impressions": 200, "searches": 30, "add_to_cart": 10, "checkouts": 5}[in_key]
        if in_v < gate:
            continue
        rate = out_v / in_v if in_v > 0 else 0
        items.append({
            "kind": "campaign",
            "id": r.campaign_id,
            "name": r.campaign_name,
            "account_name": r.account_name,
            "platform": r.platform,
            "in": in_v,
            "out": out_v,
            "rate": round(rate, 4),
            "spend": float(r.spend or 0),
        })
    items.sort(key=lambda x: (x["rate"], -x["in"]))
    return items[:limit]


# ---------- public entry ----------


DIM_LABELS = {
    None: "Overall",
    "channel": "Channel",
    "country": "Country",
    "funnel": "Funnel Stage",
    "ta": "Target Audience",
}


def _slice_label(dim: str | None, key: str, cur: FunnelBucket) -> str:
    if dim is None:
        return "Overall (last 7 days)"
    if dim == "channel":
        return (cur.platform or "Unknown").capitalize()
    if dim == "country":
        return f"{country_name(cur.country) or cur.country}"
    if dim == "funnel":
        fs = (cur.funnel_stage or "Unknown").upper()
        names = {"TOF": "TOF — Top of Funnel", "MOF": "MOF — Remarketing", "BOF": "BOF — Bottom of Funnel"}
        return names.get(fs, fs)
    if dim == "ta":
        return cur.ta or "Unknown"
    return key


def analyze_funnel(
    db: Session,
    *,
    d_from: date,
    d_to: date,
    platform: str | None = None,
    account_ids: list[str] | None = None,
    branches_param: str | None = None,
    max_results: int = 12,
    enrich_top_contributors: bool = True,
) -> dict:
    """Run the funnel analyzer for one window. Returns a payload with overview
    + ranked recommendations across all dimensions.
    """
    prev_from, prev_to = get_prev_period(d_from, d_to)

    cur_buckets = _group_buckets(db, d_from, d_to, platform, account_ids)
    prev_buckets = _group_buckets(db, prev_from, prev_to, platform, account_ids)

    overall_cur = _rollup(cur_buckets, None).get("__all__") or FunnelBucket()
    overall_prev = _rollup(prev_buckets, None).get("__all__") or FunnelBucket()

    # Build the overall funnel (mirror of /api/dashboard/funnel) so the panel
    # can render its own snapshot without a second round-trip.
    overall_stages = []
    for i, key in enumerate(STEP_KEYS):
        cv = overall_cur.get(key)
        pv = overall_prev.get(key)
        change = calc_change(cv, pv)
        if i == 0:
            drop = None
            drop_prev = None
            drop_change = None
        else:
            cv_prev_step = overall_cur.get(STEP_KEYS[i - 1])
            pv_prev_step = overall_prev.get(STEP_KEYS[i - 1])
            drop = 1 - (cv / cv_prev_step) if cv_prev_step > 0 else None
            drop_prev = 1 - (pv / pv_prev_step) if pv_prev_step > 0 else None
            if drop is not None and drop_prev is not None and drop_prev > 0:
                drop_change = (drop - drop_prev) / abs(drop_prev)
            else:
                drop_change = None
        overall_stages.append({
            "key": key,
            "label": STEP_LABELS[i],
            "value": cv,
            "change": _round(change, 4),
            "drop_off": _round(drop, 4),
            "drop_off_change": _round(drop_change, 4),
        })

    # For each dimension, run the rollup + score
    findings: list[Recommendation] = []
    for dim in (None, "channel", "country", "funnel", "ta"):
        cur_map = _rollup(cur_buckets, dim)
        prev_map = _rollup(prev_buckets, dim)
        for key, cur in cur_map.items():
            prev = prev_map.get(key) or FunnelBucket()
            slice_label = _slice_label(dim, key, cur)
            slice_findings = _build_finding(
                breakdown_dim=dim or "overall",
                dimension_label=slice_label,
                key=key,
                cur=cur,
                prev=prev,
                overall_cur=overall_cur,
            )
            findings.extend(slice_findings)

    # Rank globally and de-duplicate near-identical messages (same dim+from+to)
    findings.sort(key=lambda f: -f.score)

    # Build URLs + enrich top contributors for the highest-scored items only.
    enriched: list[Recommendation] = []
    seen_keys: set[str] = set()
    for f in findings:
        k = f"{f.breakdown_dim}|{f.from_stage}->{f.to_stage}|{f.dimension_value.get('key')}"
        if k in seen_keys:
            continue
        seen_keys.add(k)
        f.deep_link_url = _build_deep_link(f, branches=branches_param)
        if enrich_top_contributors and len(enriched) < max_results:
            f.top_contributors = _resolve_contributors(
                db, finding=f, d_from=d_from, d_to=d_to,
                platform=platform, account_ids=account_ids,
            )
        enriched.append(f)
        if len(enriched) >= max_results:
            break

    return {
        "period": {"from": d_from.isoformat(), "to": d_to.isoformat()},
        "prev_period": {"from": prev_from.isoformat(), "to": prev_to.isoformat()},
        "overall_funnel": overall_stages,
        "recommendations": [r.to_dict() for r in enriched],
        "summary": _build_summary(enriched),
    }


def _resolve_contributors(
    db: Session, *, finding: Recommendation,
    d_from: date, d_to: date,
    platform: str | None,
    account_ids: list[str] | None,
) -> list[dict]:
    dv = finding.dimension_value or {}
    plat = dv.get("platform") or platform
    country = dv.get("country")
    funnel_stage = dv.get("funnel_stage")
    ta = dv.get("ta")

    if finding.deep_link_target == "creative":
        return _ad_contributors(
            db,
            d_from=d_from, d_to=d_to,
            platform=plat or "meta",  # creative library is Meta only
            country=country, funnel_stage=funnel_stage, ta=ta,
            account_ids=account_ids,
        )
    if finding.deep_link_target == "landing_page":
        return _landing_page_contributors(
            db,
            d_from=d_from, d_to=d_to,
            platform=plat,
            country=country,
            account_ids=account_ids,
        )
    return _campaign_contributors(
        db,
        d_from=d_from, d_to=d_to,
        platform=plat,
        country=country, funnel_stage=funnel_stage, ta=ta,
        account_ids=account_ids,
        metric=finding.to_stage,
    )


def _build_summary(findings: list[Recommendation]) -> dict:
    by_severity = defaultdict(int)
    by_transition = defaultdict(int)
    for f in findings:
        by_severity[f.severity] += 1
        by_transition[f.transition_name] += 1

    worst = findings[0] if findings else None
    return {
        "total": len(findings),
        "by_severity": dict(by_severity),
        "by_transition": dict(by_transition),
        "worst_transition": worst.transition_name if worst else None,
        "worst_dimension": worst.dimension_label if worst else None,
    }
