"""Budget allocation suggestion service.

Analyses last month's ads performance (ROAS/CPA/spend by channel × TA ×
country) together with HiD hotel-intelligence signals (OTA mix, KPI
achievement, upcoming holidays, top guest markets) and asks Claude Sonnet
for an optimised channel_pct breakdown for next month.

The result is transient — it is never persisted to the DB. The caller
presents it to the user who can apply it to the BudgetMonthlySplit form.
"""
from __future__ import annotations

import json
import logging
from calendar import monthrange
from datetime import date, timedelta
from typing import Any

from anthropic import Anthropic
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.account import AdAccount
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.models.metrics import MetricsCache
from app.services import pms_client
from app.services.budget_service import _get_account_ids_for_branch

logger = logging.getLogger(__name__)

SUGGESTION_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1200

SYSTEM_PROMPT = """You are a performance-marketing budget strategist for MEANDER Group hotels.

Given last month's paid-ads performance (ROAS/CPA/spend by channel × target-audience × country)
AND hotel-intelligence signals (OTA vs Direct mix, KPI achievement vs target, upcoming holidays,
top guest source markets), suggest an optimised channel budget split % for next month.

Your goal: maximise direct bookings and blended ROAS.

Rules:
- channel_pct values must sum to exactly 100.
- Only include channels that had spend last month OR are explicitly justified by the signals.
- If a channel had < 5 % of total spend, flag it as low-confidence.
- Ground every recommendation in the data provided. Do NOT invent numbers or claims.
- Output STRICT JSON only — no markdown, no commentary outside the JSON block.

Output schema:
{
  "channel_pct": {"meta": 65, "google": 25, "tiktok": 10},
  "ta_focus": {
    "meta": ["Couple", "Solo"],
    "google": ["Business"],
    "tiktok": ["Solo"]
  },
  "country_focus": {
    "meta": ["VN", "TW"],
    "google": ["VN"]
  },
  "rationale": "2-4 sentence explanation citing the key signals that drove the recommendation.",
  "data_highlights": [
    {"channel": "meta", "ta": "Couple", "country": "VN", "roas": 5.1, "spend_pct": 38}
  ],
  "hid_signals_used": ["string description of each HiD signal that influenced the output"],
  "warnings": ["any caveats, e.g. channel with < 5 % spend is low-confidence"]
}"""


def _last_month(target_month: date) -> tuple[date, date]:
    """Return (first_day, last_day) of the month before target_month."""
    first_of_target = target_month.replace(day=1)
    last_day_prev = first_of_target - timedelta(days=1)
    first_day_prev = last_day_prev.replace(day=1)
    return first_day_prev, last_day_prev


def get_last_month_perf(
    db: Session,
    branch: str,
    ref_month_start: date,
) -> list[dict]:
    """Aggregate MetricsCache for ref_month by platform × TA × country.

    Returns campaign-level rows only (ad_set_id IS NULL) to avoid
    double-counting. Country comes from AdSet.country when available,
    falling back to Campaign.country (Google).
    """
    account_ids = _get_account_ids_for_branch(db, branch)
    if not account_ids:
        return []

    ref_month_end = ref_month_start.replace(
        day=monthrange(ref_month_start.year, ref_month_start.month)[1]
    )

    rows = (
        db.query(
            Campaign.platform,
            Campaign.ta,
            func.coalesce(AdSet.country, Campaign.country, "Unknown").label("country"),
            func.sum(MetricsCache.spend).label("spend"),
            func.sum(MetricsCache.revenue).label("revenue"),
            func.sum(MetricsCache.conversions).label("conversions"),
        )
        .join(Campaign, MetricsCache.campaign_id == Campaign.id)
        .outerjoin(
            AdSet,
            (AdSet.campaign_id == Campaign.id) & (MetricsCache.ad_set_id == AdSet.id),
        )
        .filter(
            Campaign.account_id.in_(account_ids),
            MetricsCache.ad_set_id.is_(None),
            MetricsCache.ad_id.is_(None),
            MetricsCache.date >= ref_month_start,
            MetricsCache.date <= ref_month_end,
        )
        .group_by(Campaign.platform, Campaign.ta, func.coalesce(AdSet.country, Campaign.country, "Unknown"))
        .all()
    )

    total_spend = sum(float(r.spend or 0) for r in rows)
    result = []
    for r in rows:
        spend = float(r.spend or 0)
        revenue = float(r.revenue or 0)
        conversions = float(r.conversions or 0)
        roas = round(revenue / spend, 2) if spend > 0 else 0.0
        cpa = round(spend / conversions, 2) if conversions > 0 else None
        spend_pct = round(spend / total_spend * 100, 1) if total_spend > 0 else 0.0
        result.append({
            "channel": r.platform,
            "ta": r.ta or "Unknown",
            "country": r.country,
            "spend": round(spend, 2),
            "spend_pct": spend_pct,
            "revenue": round(revenue, 2),
            "roas": roas,
            "cpa": cpa,
            "conversions": round(conversions, 1),
        })

    return sorted(result, key=lambda x: -x["spend"])


def _resolve_branch_hid_id(branch: str) -> str | None:
    """Map an internal branch name to its HiD branch UUID."""
    try:
        branches = pms_client.fetch_branches()
        for b in branches:
            name: str = b.get("name", "")
            if branch.lower() in name.lower() or name.lower() in branch.lower():
                return b.get("id")
    except Exception:
        logger.warning("fetch_branches failed — HiD context unavailable")
    return None


def get_hid_context(branch_hid_id: str | None, last_month_start: date, last_month_end: date) -> dict[str, Any]:
    """Fetch HiD signals. Each call is wrapped so a single failure is non-fatal."""
    ctx: dict[str, Any] = {}

    try:
        ctx["upcoming_holidays"] = pms_client.fetch_upcoming_holidays(days=60)
    except Exception:
        logger.warning("fetch_upcoming_holidays failed")

    try:
        ctx["ota_mix"] = pms_client.fetch_ota_mix(
            branch_id=branch_hid_id,
            date_from=last_month_start,
            date_to=last_month_end,
        )
    except Exception:
        logger.warning("fetch_ota_mix failed")

    try:
        ctx["kpi_achievement"] = pms_client.fetch_kpi_achievement(
            date_from=last_month_start,
            date_to=last_month_end,
            branch_id=branch_hid_id,
        )
    except Exception:
        logger.warning("fetch_kpi_achievement failed")

    try:
        ctx["country_intel"] = pms_client.fetch_country_intel(branch_id=branch_hid_id)
    except Exception:
        logger.warning("fetch_country_intel failed")

    return ctx


def _format_perf_table(perf: list[dict]) -> str:
    if not perf:
        return "No ads spend data found for last month."
    lines = ["channel | ta | country | spend_pct | roas | cpa | conversions"]
    lines.append("-" * 70)
    for r in perf[:30]:  # cap prompt size
        cpa_str = f"{r['cpa']:.2f}" if r["cpa"] is not None else "n/a"
        lines.append(
            f"{r['channel']} | {r['ta']} | {r['country']} | "
            f"{r['spend_pct']}% | {r['roas']}x | {cpa_str} | {r['conversions']}"
        )
    return "\n".join(lines)


def _format_hid_context(ctx: dict) -> str:
    parts = []

    ota = ctx.get("ota_mix") or []
    if ota:
        total_bookings = sum(r.get("bookings", 0) for r in ota)
        direct_pct = 0.0
        for r in ota:
            cat = (r.get("source_category") or "").lower()
            if cat == "direct":
                b = r.get("bookings", 0)
                direct_pct = round(b / total_bookings * 100, 1) if total_bookings else 0
        ota_pct = round(100 - direct_pct, 1)
        parts.append(f"OTA share last month: {ota_pct}% (Direct: {direct_pct}%)")

    kpi = ctx.get("kpi_achievement") or []
    if kpi:
        for k in kpi:
            ach = k.get("achievement_pct") or k.get("achievement")
            if ach is not None:
                parts.append(f"KPI revenue achievement last month: {round(float(ach), 1)}%")
                break

    holidays = ctx.get("upcoming_holidays") or []
    if holidays:
        names = [h.get("name") or h.get("holiday_name", "") for h in holidays[:4]]
        parts.append(f"Upcoming holidays (next 60 days): {', '.join(n for n in names if n)}")

    intel = ctx.get("country_intel") or []
    if intel:
        top = [c.get("country_code") or c.get("country", "") for c in intel[:5]]
        parts.append(f"Top guest source markets: {', '.join(t for t in top if t)}")

    return "\n".join(parts) if parts else "HiD signals not available."


def generate_budget_suggestion(
    db: Session,
    branch: str,
    target_month: date,
    total_vnd: float | None = None,
) -> dict[str, Any]:
    """Generate an AI budget allocation suggestion for target_month.

    Returns suggestion dict with channel_pct, ta_focus, country_focus,
    rationale, data_highlights, hid_signals_used, warnings.
    """
    if not settings.ANTHROPIC_API_KEY:
        return {"error": "ANTHROPIC_API_KEY not configured"}

    last_month_start, last_month_end = _last_month(target_month)

    perf = get_last_month_perf(db, branch, last_month_start)

    branch_hid_id = _resolve_branch_hid_id(branch)
    hid_ctx = get_hid_context(branch_hid_id, last_month_start, last_month_end)

    perf_text = _format_perf_table(perf)
    hid_text = _format_hid_context(hid_ctx)

    budget_str = f"{total_vnd:,.0f} VND" if total_vnd else "unknown"

    user_message = f"""Branch: {branch}
Target month: {target_month.strftime('%B %Y')}
Monthly budget: {budget_str}

=== LAST MONTH ADS PERFORMANCE ({last_month_start.strftime('%B %Y')}) ===
{perf_text}

=== HOTEL INTELLIGENCE SIGNALS ===
{hid_text}

Please suggest the optimal channel_pct split for {target_month.strftime('%B %Y')}. Return STRICT JSON only."""

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        resp = client.messages.create(
            model=SUGGESTION_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        logger.exception("Budget suggestion model call failed")
        return {"error": f"model_error: {e!r}"[:300]}

    text_blocks = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    raw = (text_blocks[0] if text_blocks else "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].lstrip()

    try:
        suggestion = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Budget suggestion returned non-JSON: %s", raw[:300])
        return {"error": "model returned non-JSON response", "raw": raw[:500]}

    # Normalise channel_pct to exactly 100 to guard against rounding drift
    channel_pct: dict[str, float] = suggestion.get("channel_pct", {})
    pct_sum = sum(channel_pct.values())
    if pct_sum > 0 and abs(pct_sum - 100) > 0.5:
        factor = 100 / pct_sum
        channel_pct = {k: round(v * factor, 1) for k, v in channel_pct.items()}
        suggestion["channel_pct"] = channel_pct

    suggestion["meta"] = {
        "branch": branch,
        "target_month": target_month.isoformat(),
        "last_month": last_month_start.isoformat(),
        "total_vnd": total_vnd,
        "perf_rows": len(perf),
        "hid_available": bool(hid_ctx),
    }

    return suggestion
