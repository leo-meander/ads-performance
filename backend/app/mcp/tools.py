from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


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
]


# ─── Tool dispatcher ──────────────────────────────────────────────────────────

def call_tool(name: str, arguments: dict, db: Session) -> Any:
    handlers = {
        "get_performance": _get_performance,
        "get_country_breakdown": _get_country_breakdown,
        "get_campaigns": _get_campaigns,
        "get_budget_status": _get_budget_status,
        "get_branches": _get_branches,
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
