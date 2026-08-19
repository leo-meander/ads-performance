import json
from datetime import date, timedelta
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.models.ad_angle import AdAngle
from app.models.ad_combo import AdCombo
from app.models.keypoint import BranchKeypoint
from app.models.winning_ad_month import WinningAdMonth
from app.services.winning_months_service import (
    SCOPE_KPI,
    compute_lifetime_benchmarks,
    is_excluded_branch,
    is_kol,
    normalize_scope,
)


def _default_dates() -> tuple[str, str]:
    today = date.today()
    return (today - timedelta(days=30)).isoformat(), today.isoformat()


# ─── Tool definitions ─────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_performance",
        "description": (
            "Get aggregated ad performance metrics (spend, ROAS, CTR, conversions, impressions, clicks) "
            "for a date range. Filter by platform or branch. Returns totals across all matching campaigns."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {
                    "type": "string",
                    "description": "Start date YYYY-MM-DD (default: 30 days ago)",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date YYYY-MM-DD (default: today)",
                },
                "platform": {
                    "type": "string",
                    "enum": ["meta", "google", "tiktok"],
                    "description": "Filter to a single platform",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch name substring, e.g. 'Saigon', 'Oani', 'Osaka'",
                },
            },
        },
    },
    {
        "name": "get_country_breakdown",
        "description": (
            "Get ad spend and performance broken down by country/market. "
            "Returns top countries ranked by spend."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "Start date YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "End date YYYY-MM-DD"},
                "platform": {
                    "type": "string",
                    "enum": ["meta", "google", "tiktok"],
                },
                "branch": {"type": "string"},
                "limit": {
                    "type": "integer",
                    "description": "Max countries to return (default 20)",
                },
            },
        },
    },
    {
        "name": "get_angle_performance",
        "description": (
            "Rank creative angles by performance. Aggregates every ad combo grouped by its "
            "marketing angle — one of 13 fixed strategic approaches (e.g. 'Use an authority', "
            "'Before and After', 'Stress the exclusiveness of the claim') — returning combo "
            "count, spend, ROAS, CTR, conversions and cost-per-conversion per angle. Use this "
            "to answer 'which angle is winning' overall or for a given branch / audience / "
            "country. Metrics are lifetime cached combo totals, NOT date-bounded."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "branch": {
                    "type": "string",
                    "description": "Branch name substring, e.g. 'Saigon', 'Oani', 'Osaka'",
                },
                "target_audience": {
                    "type": "string",
                    "description": "Filter by audience: Solo, Couple, Friend, Group, or Business",
                },
                "country": {
                    "type": "string",
                    "description": "ISO-2 country code, e.g. 'JP', 'PH', 'AU'",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max angles to return (default 20)",
                },
            },
        },
    },
    {
        "name": "get_keypoint_performance",
        "description": (
            "Rank selling-point keypoints by performance. A combo can carry several keypoints "
            "(category is location / amenity / experience / value); this expands them and "
            "aggregates spend, ROAS, CTR, conversions per keypoint. Use this to find which "
            "specific selling points actually convert, overall or for a given branch / "
            "audience / country. Metrics are lifetime cached combo totals, NOT date-bounded; "
            "a combo with multiple keypoints contributes to each."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "branch": {
                    "type": "string",
                    "description": "Branch name substring, e.g. 'Saigon', 'Oani', 'Osaka'",
                },
                "target_audience": {
                    "type": "string",
                    "description": "Filter by audience: Solo, Couple, Friend, Group, or Business",
                },
                "country": {
                    "type": "string",
                    "description": "ISO-2 country code, e.g. 'JP', 'PH', 'AU'",
                },
                "category": {
                    "type": "string",
                    "description": "Filter by keypoint category: location, amenity, experience, or value",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max keypoints to return (default 25)",
                },
            },
        },
    },
    {
        "name": "get_campaigns",
        "description": (
            "List ad campaigns with their performance metrics. "
            "Useful for spotting top performers or underperformers."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string"},
                "date_to": {"type": "string"},
                "platform": {"type": "string", "enum": ["meta", "google", "tiktok"]},
                "status": {
                    "type": "string",
                    "enum": ["ACTIVE", "PAUSED", "ARCHIVED"],
                    "description": "Filter by campaign status",
                },
                "branch": {"type": "string"},
                "limit": {
                    "type": "integer",
                    "description": "Max campaigns to return (default 20)",
                },
            },
        },
    },
    {
        "name": "get_budget_status",
        "description": (
            "Get current monthly budget plans and actual spend vs. allocated budget "
            "for each branch and channel."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "branch": {
                    "type": "string",
                    "description": "Filter by branch (e.g. 'Saigon', 'Oani')",
                },
                "month": {
                    "type": "string",
                    "description": "Month in YYYY-MM format (default: current month)",
                },
            },
        },
    },
    {
        "name": "get_branches",
        "description": "List all hotel/restaurant branches with their ad account counts and platforms.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_ad_count",
        "description": (
            "Count distinct ads at the AD (creative) level that ran with spend in a date "
            "range, broken down by branch. This is the true ad/creative count — finer than "
            "get_campaigns, which only counts campaigns (one campaign holds many ads). "
            "Sourced from Meta ad-level daily insights; Google/TikTok ad-level counts are "
            "NOT included. Use to size creative production needs (e.g. 'how many ads are "
            "live with spend per branch')."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {
                    "type": "string",
                    "description": "Start date YYYY-MM-DD (default: 30 days ago)",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date YYYY-MM-DD (default: today)",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch name substring, e.g. 'Saigon', 'Oani', 'Osaka'",
                },
                "min_spend": {
                    "type": "number",
                    "description": (
                        "Only count ads whose TOTAL spend over the window exceeds this "
                        "(default 0 = any spend at all)."
                    ),
                },
            },
        },
    },
    {
        "name": "get_winning_ads",
        "description": (
            "List individual ADS (creatives) with their performance and WIN/LOSE/TEST "
            "verdict — the ad-level detail behind get_ad_count, which only returns counts. "
            "One row per (branch, ad_name) over the date window: spend, impressions, clicks, "
            "conversions (bookings), revenue, ROAS, CTR, cost-per-conversion, plus the "
            "combo's angle / keypoints / target audience / country when the ad is mapped in "
            "the Creative Library. Meta only (ad_daily_metrics is the sole ad-grain table). "
            "The verdict is the FROZEN one from winning_ad_months — awarded once, ever, the "
            "month the ad first crossed the test threshold, judged against the account's "
            "lifetime blended ROAS; ads never decided come back as TEST. Always check the "
            "returned `coverage` block before trusting totals: ad-level ingest is a rolling "
            "window, so a requested range can be only partly populated."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {
                    "type": "string",
                    "description": "Start date YYYY-MM-DD (default: 30 days ago)",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date YYYY-MM-DD (default: today)",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch name substring, e.g. 'Saigon', 'Oani', 'Osaka'",
                },
                "scope": {
                    "type": "string",
                    "enum": ["kpi", "all"],
                    "description": (
                        "Verdict universe (default 'kpi'). 'kpi' = the design-team KPI: "
                        "drops ads with KOL in the name and the Bread branch. 'all' = every "
                        "ad, no exclusions. The two are judged against different benchmarks "
                        "and never mix."
                    ),
                },
                "verdict": {
                    "type": "string",
                    "enum": ["WIN", "LOSE", "TEST"],
                    "description": "Only return ads with this verdict",
                },
                "min_spend": {
                    "type": "number",
                    "description": (
                        "Only return ads whose TOTAL spend over the window exceeds this "
                        "(default 0 = any spend at all). Native account currency."
                    ),
                },
                "sort_by": {
                    "type": "string",
                    "enum": ["roas", "spend", "conversions", "revenue"],
                    "description": "Sort key, always descending (default 'roas')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max ads to return (default 50, max 200)",
                },
            },
        },
    },
]


# ─── Tool dispatcher ──────────────────────────────────────────────────────────

def call_tool(name: str, arguments: dict, db: Session) -> Any:
    handlers = {
        "get_performance": _get_performance,
        "get_country_breakdown": _get_country_breakdown,
        "get_angle_performance": _get_angle_performance,
        "get_keypoint_performance": _get_keypoint_performance,
        "get_campaigns": _get_campaigns,
        "get_budget_status": _get_budget_status,
        "get_branches": _get_branches,
        "get_ad_count": _get_ad_count,
        "get_winning_ads": _get_winning_ads,
    }
    handler = handlers.get(name)
    if not handler:
        raise ValueError(f"Unknown tool: {name}")
    return handler(arguments, db)


# ─── Tool implementations ─────────────────────────────────────────────────────

def _get_performance(args: dict, db: Session) -> dict:
    date_from, date_to = _default_dates()
    date_from = args.get("date_from", date_from)
    date_to = args.get("date_to", date_to)
    platform = args.get("platform")
    branch = args.get("branch")

    filters = ["m.date BETWEEN :date_from AND :date_to"]
    params: dict = {"date_from": date_from, "date_to": date_to}

    if platform:
        filters.append("m.platform = :platform")
        params["platform"] = platform
    if branch:
        filters.append("a.account_name ILIKE :branch")
        params["branch"] = f"%{branch}%"

    where = " AND ".join(filters)
    sql = text(f"""
        SELECT
            m.platform,
            COUNT(DISTINCT m.campaign_id)        AS campaigns,
            SUM(m.spend)::float                  AS spend,
            SUM(m.impressions)                   AS impressions,
            SUM(m.clicks)                        AS clicks,
            SUM(m.conversions)                   AS conversions,
            SUM(m.revenue)::float                AS revenue,
            CASE WHEN SUM(m.spend) > 0
                 THEN ROUND((SUM(m.revenue) / SUM(m.spend))::numeric, 2)::float
            END AS roas,
            CASE WHEN SUM(m.impressions) > 0
                 THEN ROUND((SUM(m.clicks)::numeric / SUM(m.impressions) * 100), 2)::float
            END AS ctr_pct
        FROM metrics_cache m
        JOIN campaigns c ON c.id = m.campaign_id
        JOIN ad_accounts a ON a.id = c.account_id
        WHERE {where}
        GROUP BY m.platform
        ORDER BY SUM(m.spend) DESC
    """)

    rows = db.execute(sql, params).mappings().all()
    by_platform = [dict(r) for r in rows]
    return {
        "date_from": date_from,
        "date_to": date_to,
        "by_platform": by_platform,
        "totals": {
            "spend": sum(float(r["spend"] or 0) for r in by_platform),
            "impressions": sum(int(r["impressions"] or 0) for r in by_platform),
            "clicks": sum(int(r["clicks"] or 0) for r in by_platform),
            "conversions": sum(int(r["conversions"] or 0) for r in by_platform),
            "revenue": sum(float(r["revenue"] or 0) for r in by_platform),
        },
    }


def _get_country_breakdown(args: dict, db: Session) -> dict:
    date_from, date_to = _default_dates()
    date_from = args.get("date_from", date_from)
    date_to = args.get("date_to", date_to)
    platform = args.get("platform")
    branch = args.get("branch")
    limit = min(int(args.get("limit", 20)), 50)

    filters = ["cm.date BETWEEN :date_from AND :date_to"]
    params: dict = {"date_from": date_from, "date_to": date_to, "limit": limit}

    if platform:
        filters.append("cm.platform = :platform")
        params["platform"] = platform
    if branch:
        filters.append("a.account_name ILIKE :branch")
        params["branch"] = f"%{branch}%"

    where = " AND ".join(filters)
    sql = text(f"""
        SELECT
            cm.country,
            cm.platform,
            SUM(cm.spend)::float                                    AS spend,
            SUM(cm.impressions)                                     AS impressions,
            SUM(cm.clicks)                                          AS clicks,
            SUM(cm.revenue_website + cm.revenue_offline)::float     AS revenue,
            SUM(cm.conversions_website + cm.conversions_offline)    AS conversions
        FROM ad_country_metrics cm
        JOIN campaigns c ON c.id = cm.campaign_id
        JOIN ad_accounts a ON a.id = c.account_id
        WHERE {where}
        GROUP BY cm.country, cm.platform
        ORDER BY SUM(cm.spend) DESC
        LIMIT :limit
    """)

    rows = db.execute(sql, params).mappings().all()
    return {
        "date_from": date_from,
        "date_to": date_to,
        "countries": [dict(r) for r in rows],
    }


def _get_angle_performance(args: dict, db: Session) -> dict:
    branch = args.get("branch")
    ta = args.get("target_audience")
    country = args.get("country")
    limit = min(int(args.get("limit", 20)), 50)

    filters = ["cb.angle_id IS NOT NULL"]
    params: dict = {"limit": limit}
    if branch:
        filters.append("a.account_name ILIKE :branch")
        params["branch"] = f"%{branch}%"
    if ta:
        filters.append("cb.target_audience = :ta")
        params["ta"] = ta
    if country:
        filters.append("UPPER(cb.country) = :country")
        params["country"] = country.upper()

    where = " AND ".join(filters)
    sql = text(f"""
        SELECT
            cb.angle_id,
            MAX(aa.angle_type)              AS angle_type,
            MAX(aa.status)                  AS angle_status,
            COUNT(*)                        AS combos,
            SUM(cb.spend)::float            AS spend,
            SUM(cb.impressions)             AS impressions,
            SUM(cb.clicks)                  AS clicks,
            SUM(cb.conversions)             AS conversions,
            SUM(cb.revenue)::float          AS revenue,
            CASE WHEN SUM(cb.spend) > 0
                 THEN ROUND((SUM(cb.revenue) / SUM(cb.spend))::numeric, 2)::float
            END AS roas,
            CASE WHEN SUM(cb.impressions) > 0
                 THEN ROUND((SUM(cb.clicks)::numeric / SUM(cb.impressions) * 100), 2)::float
            END AS ctr_pct,
            CASE WHEN SUM(cb.conversions) > 0
                 THEN ROUND((SUM(cb.spend) / SUM(cb.conversions))::numeric, 2)::float
            END AS cost_per_conversion
        FROM ad_combos cb
        JOIN ad_accounts a ON a.id = cb.branch_id
        LEFT JOIN ad_angles aa ON aa.angle_id = cb.angle_id
        WHERE {where}
        GROUP BY cb.angle_id
        ORDER BY roas DESC NULLS LAST, SUM(cb.spend) DESC
        LIMIT :limit
    """)

    rows = db.execute(sql, params).mappings().all()
    return {
        "filters": {"branch": branch, "target_audience": ta, "country": country},
        "note": "Lifetime cached combo metrics, not date-bounded. Ordered by ROAS desc.",
        "angles": [dict(r) for r in rows],
    }


def _get_keypoint_performance(args: dict, db: Session) -> dict:
    branch = args.get("branch")
    ta = args.get("target_audience")
    country = args.get("country")
    category = args.get("category")
    limit = min(int(args.get("limit", 25)), 100)

    # keypoint_ids is a JSON array (a combo carries several keypoints), so we
    # fetch the matching combos and expand the array in Python — mirrors the
    # canonical aggregation in the /keypoints endpoint rather than relying on
    # DB-specific JSON unnesting.
    filters = ["cb.keypoint_ids IS NOT NULL"]
    params: dict = {}
    if branch:
        filters.append("a.account_name ILIKE :branch")
        params["branch"] = f"%{branch}%"
    if ta:
        filters.append("cb.target_audience = :ta")
        params["ta"] = ta
    if country:
        filters.append("UPPER(cb.country) = :country")
        params["country"] = country.upper()

    where = " AND ".join(filters)
    sql = text(f"""
        SELECT cb.keypoint_ids, cb.spend, cb.revenue,
               cb.impressions, cb.clicks, cb.conversions
        FROM ad_combos cb
        JOIN ad_accounts a ON a.id = cb.branch_id
        WHERE {where}
    """)
    combo_rows = db.execute(sql, params).mappings().all()

    agg: dict[str, dict] = {}
    for r in combo_rows:
        # Postgres (psycopg2) hands back a parsed list; other drivers may return
        # the raw JSON string — coerce either way.
        raw = r["keypoint_ids"]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (ValueError, TypeError):
                raw = []
        ids = raw if isinstance(raw, list) else []
        for kid in ids:
            m = agg.setdefault(
                kid,
                {"combos": 0, "spend": 0.0, "revenue": 0.0,
                 "impressions": 0, "clicks": 0, "conversions": 0},
            )
            m["combos"] += 1
            m["spend"] += float(r["spend"] or 0)
            m["revenue"] += float(r["revenue"] or 0)
            m["impressions"] += int(r["impressions"] or 0)
            m["clicks"] += int(r["clicks"] or 0)
            m["conversions"] += int(r["conversions"] or 0)

    meta: dict[str, dict] = {}
    if agg:
        stmt = text(
            "SELECT id, title, category, is_active "
            "FROM branch_keypoints WHERE id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        for k in db.execute(stmt, {"ids": list(agg.keys())}).mappings().all():
            meta[k["id"]] = {
                "title": k["title"],
                "category": k["category"],
                "is_active": k["is_active"],
            }

    result = []
    for kid, m in agg.items():
        info = meta.get(kid, {})
        if category and info.get("category") != category:
            continue
        spend = m["spend"]
        revenue = m["revenue"]
        impressions = m["impressions"]
        conversions = m["conversions"]
        result.append({
            "keypoint_id": kid,
            "title": info.get("title", "(deleted keypoint)"),
            "category": info.get("category", ""),
            "is_active": info.get("is_active"),
            "combos": m["combos"],
            "spend": round(spend, 2),
            "revenue": round(revenue, 2),
            "roas": round(revenue / spend, 2) if spend > 0 else None,
            "impressions": impressions,
            "clicks": m["clicks"],
            "conversions": conversions,
            "ctr_pct": round(m["clicks"] / impressions * 100, 2) if impressions > 0 else None,
            "cost_per_conversion": round(spend / conversions, 2) if conversions > 0 else None,
        })

    # ROAS desc, keypoints with no spend/ROAS last, ties broken by spend.
    result.sort(key=lambda x: (x["roas"] is not None, x["roas"] or 0, x["spend"]), reverse=True)
    return {
        "filters": {"branch": branch, "target_audience": ta, "country": country, "category": category},
        "note": (
            "Lifetime cached combo metrics, not date-bounded. Ordered by ROAS desc. "
            "A combo with multiple keypoints contributes to each."
        ),
        "keypoints": result[:limit],
    }


def _get_campaigns(args: dict, db: Session) -> dict:
    date_from, date_to = _default_dates()
    date_from = args.get("date_from", date_from)
    date_to = args.get("date_to", date_to)
    platform = args.get("platform")
    status = args.get("status")
    branch = args.get("branch")
    limit = min(int(args.get("limit", 20)), 100)

    c_filters = ["1=1"]
    params: dict = {"date_from": date_from, "date_to": date_to, "limit": limit}

    if platform:
        c_filters.append("c.platform = :platform")
        params["platform"] = platform
    if status:
        c_filters.append("c.status = :status")
        params["status"] = status
    if branch:
        c_filters.append("a.account_name ILIKE :branch")
        params["branch"] = f"%{branch}%"

    c_where = " AND ".join(c_filters)
    sql = text(f"""
        SELECT
            c.name,
            c.platform,
            c.status,
            c.ta,
            c.funnel_stage,
            a.account_name                  AS branch,
            SUM(m.spend)::float             AS spend,
            SUM(m.impressions)              AS impressions,
            SUM(m.clicks)                   AS clicks,
            SUM(m.conversions)              AS conversions,
            SUM(m.revenue)::float           AS revenue,
            CASE WHEN SUM(m.spend) > 0
                 THEN ROUND((SUM(m.revenue) / SUM(m.spend))::numeric, 2)::float
            END AS roas
        FROM campaigns c
        JOIN ad_accounts a ON a.id = c.account_id
        LEFT JOIN metrics_cache m
            ON m.campaign_id = c.id
            AND m.date BETWEEN :date_from AND :date_to
        WHERE {c_where}
        GROUP BY c.id, c.name, c.platform, c.status, c.ta, c.funnel_stage, a.account_name
        ORDER BY SUM(m.spend) DESC NULLS LAST
        LIMIT :limit
    """)

    rows = db.execute(sql, params).mappings().all()
    return {
        "date_from": date_from,
        "date_to": date_to,
        "campaigns": [dict(r) for r in rows],
        "count": len(rows),
    }


def _get_budget_status(args: dict, db: Session) -> dict:
    branch = args.get("branch")
    month_str = args.get("month")

    if month_str:
        year, mo = month_str.split("-")
        month_start = date(int(year), int(mo), 1)
    else:
        today = date.today()
        month_start = today.replace(day=1)

    if month_start.month == 12:
        month_end = date(month_start.year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)

    b_filters = ["bp.month = :month AND bp.is_active = true"]
    params: dict = {
        "month": month_start,
        "date_from": month_start,
        "date_to": month_end,
    }

    if branch:
        b_filters.append("bp.branch ILIKE :branch")
        params["branch"] = f"%{branch}%"

    b_where = " AND ".join(b_filters)
    sql = text(f"""
        SELECT
            bp.branch,
            bp.channel,
            bp.total_budget::float  AS budget,
            bp.currency,
            COALESCE(
                (SELECT SUM(m.spend)::float
                 FROM campaigns c
                 JOIN ad_accounts a ON a.id = c.account_id
                 JOIN metrics_cache m ON m.campaign_id = c.id
                 WHERE c.platform = bp.channel
                   AND a.account_name ILIKE '%' || bp.branch || '%'
                   AND m.date BETWEEN :date_from AND :date_to),
                0
            ) AS actual_spend
        FROM budget_plans bp
        WHERE {b_where}
        ORDER BY bp.branch, bp.channel
    """)

    rows = db.execute(sql, params).mappings().all()
    result = []
    for r in rows:
        d = dict(r)
        budget = float(d["budget"] or 0)
        spend = float(d["actual_spend"] or 0)
        d["pacing_pct"] = round(spend / budget * 100, 1) if budget > 0 else 0
        result.append(d)

    return {
        "month": month_start.strftime("%Y-%m"),
        "plans": result,
    }


def _get_ad_count(args: dict, db: Session) -> dict:
    """Count distinct ads (creatives) that spent in the window, per branch.

    Meta ad-level only — ad_daily_metrics is the sole table at ad grain. The
    grain of ad_daily_metrics is (account, ad_id, day), so we first collapse
    the daily rows to one window-total per (branch, ad_id), drop ads at/below
    min_spend, then COUNT the survivors per branch. Counting distinct ad_id is
    what makes this an AD-level count rather than the campaign-level count that
    get_campaigns returns.
    """
    date_from, date_to = _default_dates()
    date_from = args.get("date_from", date_from)
    date_to = args.get("date_to", date_to)
    branch = args.get("branch")
    min_spend = float(args.get("min_spend", 0) or 0)

    filters = ["m.date BETWEEN :date_from AND :date_to"]
    params: dict = {"date_from": date_from, "date_to": date_to, "min_spend": min_spend}
    if branch:
        # LOWER(...) LIKE LOWER(...) instead of ILIKE so the query runs on both
        # Postgres (prod) and SQLite (tests).
        filters.append("LOWER(a.account_name) LIKE LOWER(:branch)")
        params["branch"] = f"%{branch}%"

    where = " AND ".join(filters)
    sql = text(f"""
        SELECT
            branch,
            COUNT(*)                        AS ads_with_spend,
            CAST(SUM(ad_spend) AS FLOAT)    AS spend
        FROM (
            SELECT
                a.account_name      AS branch,
                m.ad_id             AS ad_id,
                SUM(m.spend)        AS ad_spend
            FROM ad_daily_metrics m
            JOIN ad_accounts a ON a.id = m.account_id
            WHERE {where}
            GROUP BY a.account_name, m.ad_id
            HAVING SUM(m.spend) > :min_spend
        ) t
        GROUP BY branch
        ORDER BY ads_with_spend DESC
    """)

    rows = db.execute(sql, params).mappings().all()
    by_branch = [dict(r) for r in rows]
    return {
        "date_from": date_from,
        "date_to": date_to,
        "min_spend": min_spend,
        "note": (
            "Ad-level (creative) counts from Meta ad insights only. "
            "Google/TikTok ad-level data is not tracked at this grain."
        ),
        "by_branch": by_branch,
        "total_ads_with_spend": sum(int(r["ads_with_spend"] or 0) for r in by_branch),
    }


def _get_branches(args: dict, db: Session) -> dict:
    sql = text("""
        SELECT
            account_name                                    AS branch,
            COUNT(DISTINCT platform)                        AS platform_count,
            ARRAY_AGG(DISTINCT platform ORDER BY platform)  AS platforms,
            COUNT(DISTINCT id)                              AS account_count,
            SUM(CASE WHEN is_active THEN 1 ELSE 0 END)     AS active_accounts
        FROM ad_accounts
        GROUP BY account_name
        ORDER BY account_name
    """)
    rows = db.execute(sql).mappings().all()
    return {
        "branches": [
            {
                "branch": r["branch"],
                "platform_count": r["platform_count"],
                "platforms": list(r["platforms"]),
                "account_count": r["account_count"],
                "active_accounts": r["active_accounts"],
            }
            for r in rows
        ]
    }


def _get_winning_ads(args: dict, db: Session) -> dict:
    """List ads (creatives) with their metrics and frozen WIN/LOSE/TEST verdict.

    This is get_ad_count's missing half: same source table, same grain, but it
    returns the ads themselves instead of counting them. Grain is (account,
    ad_name) — NOT ad_id — because a verdict is awarded per ad_name (an ad
    duplicated across adsets is one creative, judged once); `ad_count` says how
    many platform ad_ids collapsed into the row.

    Three lookups hang off the aggregate, all keyed in Python so the SQL stays
    portable (SQLite in tests, Postgres in prod):
      * winning_ad_months -> the FROZEN verdict. Written once, ever, the month
        the ad first crossed the test threshold; absent = never decided = TEST.
      * ad_combos (+ ad_angles, branch_keypoints) -> angle / keypoints / TA /
        country, best-effort: an ad with no combo row simply has nulls.
      * compute_lifetime_benchmarks -> the bar itself, so a still-TEST ad can be
        read against the same number a frozen verdict was judged on.

    `coverage` is not decoration: ad_daily_metrics is refreshed by a rolling
    14-day cron (sync-daily-ad-metrics), and older days exist only where a
    manual backfill put them. A window can therefore be silently half-empty,
    which reads as "these ads underspent" rather than "we never ingested those
    days" — so every response carries the days actually present per branch.
    """
    date_from, date_to = _default_dates()
    date_from = args.get("date_from", date_from)
    date_to = args.get("date_to", date_to)
    branch = args.get("branch")
    scope = normalize_scope(args.get("scope"))
    verdict_filter = (args.get("verdict") or "").strip().upper() or None
    min_spend = float(args.get("min_spend", 0) or 0)
    sort_by = args.get("sort_by") or "roas"
    limit = min(int(args.get("limit", 50) or 50), 200)

    filters = ["m.date BETWEEN :date_from AND :date_to", "m.ad_name IS NOT NULL"]
    params: dict = {"date_from": date_from, "date_to": date_to, "min_spend": min_spend}
    if branch:
        # LOWER(...) LIKE LOWER(...) instead of ILIKE so the query runs on both
        # Postgres (prod) and SQLite (tests).
        filters.append("LOWER(a.account_name) LIKE LOWER(:branch)")
        params["branch"] = f"%{branch}%"
    where = " AND ".join(filters)

    sql = text(f"""
        SELECT
            m.account_id                    AS account_id,
            a.account_name                  AS branch,
            m.ad_name                       AS ad_name,
            COUNT(DISTINCT m.ad_id)         AS ad_count,
            MIN(m.ad_id)                    AS ad_id,
            COUNT(DISTINCT m.date)          AS days_with_spend,
            CAST(SUM(m.spend) AS FLOAT)     AS spend,
            SUM(m.impressions)              AS impressions,
            SUM(m.clicks)                   AS clicks,
            SUM(m.conversions)              AS conversions,
            CAST(SUM(m.revenue) AS FLOAT)   AS revenue
        FROM ad_daily_metrics m
        JOIN ad_accounts a ON a.id = m.account_id
        WHERE {where}
        GROUP BY m.account_id, a.account_name, m.ad_name
        HAVING SUM(m.spend) > :min_spend
    """)
    rows = [dict(r) for r in db.execute(sql, params).mappings().all()]

    # Scope exclusions mirror winning_months_service exactly: judging a KOL ad
    # against the KPI bar (which its own spend was kept out of) would measure it
    # against a benchmark it never belonged to.
    rows = [
        r for r in rows
        if not (
            scope == SCOPE_KPI
            and (is_kol(r["ad_name"]) or is_excluded_branch(r["branch"], scope))
        )
    ]

    account_ids = sorted({str(r["account_id"]) for r in rows})

    # Frozen verdicts. An ad_name is decided once per (account, scope); if two
    # rows somehow exist, the earliest month is the real decision.
    frozen: dict[tuple, Any] = {}
    if account_ids:
        for wam in (
            db.query(WinningAdMonth)
            .filter(
                WinningAdMonth.scope == scope,
                WinningAdMonth.account_id.in_(account_ids),
            )
            .order_by(WinningAdMonth.month.asc())
            .all()
        ):
            frozen.setdefault((str(wam.account_id), wam.ad_name), wam)

    # Creative Library mapping. Filtered by branch only, then matched on ad_name
    # in Python — an IN() over every ad_name would blow SQLite's parameter cap.
    combos: dict[tuple, Any] = {}
    angle_types: dict[str, Any] = {}
    keypoint_ids: set[str] = set()
    if account_ids:
        for combo, angle in (
            db.query(AdCombo, AdAngle)
            .outerjoin(AdAngle, AdAngle.angle_id == AdCombo.angle_id)
            .filter(AdCombo.branch_id.in_(account_ids), AdCombo.ad_name.isnot(None))
            .all()
        ):
            combos.setdefault((str(combo.branch_id), combo.ad_name), combo)
            if angle is not None:
                angle_types[combo.angle_id] = angle.angle_type
            for kp_id in (combo.keypoint_ids or []):
                keypoint_ids.add(str(kp_id))

    keypoint_titles: dict[str, str] = {}
    if keypoint_ids:
        for kp in (
            db.query(BranchKeypoint)
            .filter(BranchKeypoint.id.in_(sorted(keypoint_ids)))
            .all()
        ):
            keypoint_titles[str(kp.id)] = kp.title

    benchmarks = compute_lifetime_benchmarks(db, account_ids, scope)

    ads = []
    for r in rows:
        acc_id = str(r["account_id"])
        key = (acc_id, r["ad_name"])
        spend = float(r["spend"] or 0)
        impressions = int(r["impressions"] or 0)
        clicks = int(r["clicks"] or 0)
        conversions = int(r["conversions"] or 0)
        revenue = float(r["revenue"] or 0)
        roas = round(revenue / spend, 2) if spend > 0 else None

        wam = frozen.get(key)
        combo = combos.get(key)
        benchmark = benchmarks.get(acc_id)

        ad = {
            "branch": r["branch"],
            "ad_name": r["ad_name"],
            "ad_id": r["ad_id"],
            "ad_count": int(r["ad_count"] or 0),
            "days_with_spend": int(r["days_with_spend"] or 0),
            "spend": round(spend, 2),
            "impressions": impressions,
            "clicks": clicks,
            "conversions": conversions,
            "revenue": round(revenue, 2),
            "roas": roas,
            "ctr_pct": round(clicks / impressions * 100, 2) if impressions > 0 else None,
            "cost_per_conversion": round(spend / conversions, 2) if conversions > 0 else None,
            # Frozen verdict — never recomputed from the numbers above.
            "verdict": wam.verdict if wam else "TEST",
            "verdict_month": wam.month.strftime("%Y-%m") if wam else None,
            "verdict_source": wam.verdict_source if wam else None,
            "verdict_roas": float(wam.roas) if wam and wam.roas is not None else None,
            "verdict_benchmark_roas": (
                float(wam.benchmark_roas) if wam and wam.benchmark_roas is not None else None
            ),
            # The bar as of RIGHT NOW, for reading a still-TEST ad against.
            "benchmark_roas_now": round(benchmark, 2) if benchmark else None,
            "above_benchmark_now": (
                (roas >= benchmark) if roas is not None and benchmark else None
            ),
            # Creative Library — null when the ad has no combo row.
            "combo_id": combo.combo_id if combo else None,
            "target_audience": combo.target_audience if combo else None,
            "country": combo.country if combo else None,
            "angle_id": combo.angle_id if combo else None,
            "angle_type": angle_types.get(combo.angle_id) if combo else None,
            "keypoints": (
                [
                    keypoint_titles[str(k)]
                    for k in (combo.keypoint_ids or [])
                    if str(k) in keypoint_titles
                ]
                if combo else []
            ),
        }
        if verdict_filter and ad["verdict"] != verdict_filter:
            continue
        ads.append(ad)

    sort_key = {
        "roas": lambda a: a["roas"] or 0,
        "spend": lambda a: a["spend"] or 0,
        "conversions": lambda a: a["conversions"] or 0,
        "revenue": lambda a: a["revenue"] or 0,
    }.get(sort_by, lambda a: a["roas"] or 0)
    ads.sort(key=sort_key, reverse=True)

    # What the ad-level table actually holds for this window, per branch — the
    # tell for a half-ingested range (see the docstring).
    cov_sql = text(f"""
        SELECT
            a.account_name          AS branch,
            COUNT(DISTINCT m.date)  AS days_with_data,
            MIN(m.date)             AS first_day,
            MAX(m.date)             AS last_day
        FROM ad_daily_metrics m
        JOIN ad_accounts a ON a.id = m.account_id
        WHERE {where}
        GROUP BY a.account_name
        ORDER BY a.account_name
    """)
    cov_params = {k: v for k, v in params.items() if k != "min_spend"}
    days_requested = (date.fromisoformat(date_to) - date.fromisoformat(date_from)).days + 1
    coverage = []
    for c in db.execute(cov_sql, cov_params).mappings().all():
        days_with_data = int(c["days_with_data"] or 0)
        coverage.append({
            "branch": c["branch"],
            "days_with_data": days_with_data,
            "days_requested": days_requested,
            "coverage_pct": (
                round(days_with_data / days_requested * 100, 1) if days_requested else None
            ),
            "first_day": str(c["first_day"]),
            "last_day": str(c["last_day"]),
        })

    return {
        "date_from": date_from,
        "date_to": date_to,
        "scope": scope,
        "filters": {"branch": branch, "verdict": verdict_filter, "min_spend": min_spend},
        "note": (
            "Meta ad-level only (ad_daily_metrics); Google/TikTok are not tracked at this "
            "grain. One row per (branch, ad_name). Verdict is the frozen winning_ad_months "
            "decision — TEST means never decided, not 'currently below the bar'. Spend and "
            "revenue are in each account's native currency, so do NOT sum across branches. "
            "Check `coverage`: any branch below ~100% means the window is only partly "
            "ingested and its totals understate reality."
        ),
        "coverage": coverage,
        "total_matching": len(ads),
        "returned": min(len(ads), limit),
        "ads": ads[:limit],
    }
