"""Google Ads insight rules: classification + diagnosis flags.

Pure functions — no DB / no API. Take metric rows from
google_insights_client and produce structured grouping + flag output for
the per-panel UI. The combined narrative is generated separately by an LLM.
"""

from __future__ import annotations

import re
from typing import Any

# ── Search term classification ──────────────────────────────

# Brand tokens: anything containing these counts as "brand" intent.
BRAND_TOKENS = {"meander", "oani", "1948"}

PRICE_TOKENS = {
    "cheap", "free", "budget", "discount", "deal", "promo", "promotion",
    "low cost", "low-cost", "lowcost", "affordable", "$", "under",
    "rẻ", "giá rẻ", "khuyến mãi", "miễn phí",
    "格安", "安い", "激安",
    "便宜", "免費", "優惠",
}
QUALITY_TOKENS = {
    "boutique", "premium", "luxury", "best", "top", "5 star", "5-star",
    "high end", "high-end", "design", "stylish", "rooftop",
    "cao cấp", "sang trọng",
    "高級", "ラグジュアリー",
    "精品", "豪華", "頂級",
}
HIGH_INTENT_TOKENS = {
    "book", "booking", "reserve", "reservation", "near me", "tonight",
    "rooms available", "check in", "stay", "deals tonight",
    "đặt phòng", "đặt", "khách sạn quận 1", "phòng",
    "予約", "宿泊",
    "訂房", "訂", "預訂",
}
JOB_OR_INFO_TOKENS = {
    "jobs", "job", "career", "salary", "wikipedia", "history", "what is",
    "work", "internship", "review", "reviews",
    "tuyển dụng", "việc làm", "lương",
    "求人", "アルバイト",
    "工作", "招聘",
}


def _has_token(text: str, tokens: set[str]) -> bool:
    text = text.lower()
    return any(t in text for t in tokens)


def _classify_intent(term: str) -> str:
    """Return one of HIGH / MID / LOW / JUNK."""
    if _has_token(term, JOB_OR_INFO_TOKENS):
        return "JUNK"
    if _has_token(term, HIGH_INTENT_TOKENS):
        return "HIGH"
    # Hostel/hotel + location word = mid intent
    if re.search(r"hotel|hostel|stay|accommodation|khách sạn|ホテル|飯店|酒店|旅館", term, re.IGNORECASE):
        return "MID"
    return "LOW"


def _classify_brand(term: str) -> str:
    return "BRAND" if _has_token(term, BRAND_TOKENS) else "NON_BRAND"


def _classify_price_quality(term: str) -> str:
    has_price = _has_token(term, PRICE_TOKENS)
    has_quality = _has_token(term, QUALITY_TOKENS)
    if has_price and not has_quality:
        return "PRICE"
    if has_quality and not has_price:
        return "QUALITY"
    if has_price and has_quality:
        return "MIXED"
    return "NEUTRAL"


def classify_search_terms(terms: list[dict]) -> dict[str, Any]:
    """Tag every term + roll up totals per bucket."""
    enriched = []
    for t in terms:
        term = t["search_term"]
        intent = _classify_intent(term)
        brand = _classify_brand(term)
        pq = _classify_price_quality(term)
        flags = _flag_search_term(t, intent)
        enriched.append({**t, "intent": intent, "brand": brand, "price_quality": pq, "flags": flags})

    def _agg(rows: list[dict]) -> dict:
        spend = sum(r["spend"] for r in rows)
        clicks = sum(r["clicks"] for r in rows)
        conv = sum(r["conversions"] for r in rows)
        revenue = sum(r["revenue"] for r in rows)
        impr = sum(r["impressions"] for r in rows)
        return {
            "term_count": len(rows),
            "spend": spend, "impressions": impr, "clicks": clicks,
            "conversions": conv, "revenue": revenue,
            "ctr": (clicks / impr * 100) if impr > 0 else 0,
            "cvr": (conv / clicks * 100) if clicks > 0 else 0,
            "roas": (revenue / spend) if spend > 0 else 0,
            "cpa": (spend / conv) if conv > 0 else None,
        }

    by_intent = {k: _agg([r for r in enriched if r["intent"] == k]) for k in ("HIGH", "MID", "LOW", "JUNK")}
    by_brand = {k: _agg([r for r in enriched if r["brand"] == k]) for k in ("BRAND", "NON_BRAND")}
    by_pq = {k: _agg([r for r in enriched if r["price_quality"] == k]) for k in ("PRICE", "QUALITY", "MIXED", "NEUTRAL")}

    junk_terms = [r for r in enriched if "WASTE" in r["flags"] or r["intent"] == "JUNK"]
    junk_terms.sort(key=lambda r: r["spend"], reverse=True)

    winners = [r for r in enriched if "WINNER" in r["flags"]]
    winners.sort(key=lambda r: r["roas"], reverse=True)

    mismatch = [r for r in enriched if "INTENT_MATCH_NO_CONV" in r["flags"]]
    mismatch.sort(key=lambda r: r["spend"], reverse=True)

    return {
        "terms": enriched,
        "by_intent": by_intent,
        "by_brand": by_brand,
        "by_price_quality": by_pq,
        "junk_terms": junk_terms[:20],
        "winners": winners[:20],
        "intent_match_no_conv": mismatch[:20],
        "total_terms": len(enriched),
    }


def _flag_search_term(t: dict, intent: str) -> list[str]:
    flags: list[str] = []
    clicks = t["clicks"]
    conv = t["conversions"]
    spend = t["spend"]
    cvr = t.get("cvr") or 0
    roas = t.get("roas") or 0

    # Wasted spend: spent money, no conversion, ≥5 clicks
    if conv == 0 and clicks >= 5 and spend > 0:
        flags.append("WASTE")

    # Right intent, no conversion = ad copy / landing page mismatch
    if intent in ("HIGH", "MID") and conv == 0 and clicks >= 10:
        flags.append("INTENT_MATCH_NO_CONV")

    # Strong winner: ≥1 conv and ROAS ≥ 3 (or CVR ≥ 3% with at least 10 clicks)
    if (conv >= 1 and roas >= 3) or (cvr >= 3 and clicks >= 10):
        flags.append("WINNER")

    # Negative-keyword candidate: junk intent with any spend
    if intent == "JUNK" and spend > 0:
        flags.append("NEGATIVE_CANDIDATE")

    return flags


# ── Device diagnosis ────────────────────────────────────────


def diagnose_devices(rows: list[dict]) -> dict[str, Any]:
    by_dev = {r["device_raw"]: r for r in rows}
    mobile = by_dev.get("MOBILE")
    desktop = by_dev.get("DESKTOP")

    flags: list[str] = []
    if mobile and desktop:
        m_cvr = mobile.get("cvr") or 0
        d_cvr = desktop.get("cvr") or 0
        m_ctr = mobile.get("ctr") or 0
        d_ctr = desktop.get("ctr") or 0

        # Mobile UX broken: mobile CTR healthy (≥1%) but CVR < 50% of desktop
        if m_ctr >= 1.0 and d_cvr > 0 and m_cvr < d_cvr * 0.5:
            flags.append("MOBILE_UX_BROKEN")

        # Cross-device research pattern: mobile clicks dominate, desktop CVR much higher
        m_clicks = mobile["clicks"]
        d_clicks = desktop["clicks"]
        if m_clicks > d_clicks * 1.5 and d_cvr > m_cvr * 1.5:
            flags.append("CROSS_DEVICE_RESEARCH")

        # Healthy: mobile CVR within 30% of desktop
        if d_cvr > 0 and m_cvr >= d_cvr * 0.7 and "MOBILE_UX_BROKEN" not in flags:
            flags.append("HEALTHY")

    return {"devices": rows, "flags": flags}


# ── Location diagnosis ──────────────────────────────────────


# MEANDER's high-value source markets — used as comparison baseline only
HIGH_VALUE_MARKETS = {"US", "GB", "AU", "DE", "FR", "JP", "TW", "SG", "KR"}


def diagnose_locations(rows: list[dict]) -> dict[str, Any]:
    """Tag countries as junk / cheap-no-value / profitable / promising."""
    if not rows:
        return {"locations": [], "junk": [], "winners": [], "summary": {}}

    total_spend = sum(r["spend"] for r in rows)
    enriched = []

    for r in rows:
        spend = r["spend"]
        clicks = r["clicks"]
        conv = r["conversions"]
        revenue = r["revenue"]
        roas = r.get("roas") or 0
        cvr = r.get("cvr") or 0
        spend_share = (spend / total_spend) if total_spend > 0 else 0

        flags: list[str] = []
        # Junk: ≥1% of spend share, ≥30 clicks, zero conversions
        if spend_share >= 0.01 and clicks >= 30 and conv == 0:
            flags.append("CHEAP_TRAFFIC_NO_VALUE")
        # Profitable: ROAS ≥ 2 with ≥1 conversion
        if conv >= 1 and roas >= 2:
            flags.append("PROFITABLE")
        # Premium market expensive but profitable
        if r["country"] in HIGH_VALUE_MARKETS and roas >= 1.5 and conv >= 1:
            flags.append("HIGH_VALUE_MARKET")

        enriched.append({**r, "spend_share": spend_share, "flags": flags})

    junk = [r for r in enriched if "CHEAP_TRAFFIC_NO_VALUE" in r["flags"]]
    junk.sort(key=lambda r: r["spend"], reverse=True)
    winners = [r for r in enriched if "PROFITABLE" in r["flags"]]
    winners.sort(key=lambda r: r["roas"], reverse=True)

    return {
        "locations": enriched,
        "junk": junk[:10],
        "winners": winners[:10],
        "summary": {
            "country_count": len(enriched),
            "junk_count": len(junk),
            "profitable_count": len(winners),
        },
    }


# ── Hour × day diagnosis ────────────────────────────────────


def diagnose_time_of_day(rows: list[dict]) -> dict[str, Any]:
    if not rows:
        return {"cells": [], "by_hour": [], "by_day": [], "waste_hours": [], "peak_hours": []}

    # By-hour rollup (sum across days)
    by_hour: dict[int, dict] = {}
    for r in rows:
        h = r["hour"]
        cur = by_hour.setdefault(h, {
            "hour": h, "spend": 0.0, "clicks": 0,
            "conversions": 0.0, "revenue": 0.0, "impressions": 0,
        })
        cur["spend"] += r["spend"]
        cur["clicks"] += r["clicks"]
        cur["conversions"] += r["conversions"]
        cur["revenue"] += r["revenue"]
        cur["impressions"] += r["impressions"]

    by_hour_list = []
    for h in range(24):
        v = by_hour.get(h, {"hour": h, "spend": 0, "clicks": 0, "conversions": 0, "revenue": 0, "impressions": 0})
        spend = v["spend"]
        clicks = v["clicks"]
        conv = v["conversions"]
        v["cvr"] = (conv / clicks * 100) if clicks > 0 else 0
        v["roas"] = (v["revenue"] / spend) if spend > 0 else 0
        v["cpa"] = (spend / conv) if conv > 0 else None
        by_hour_list.append(v)

    # By day-of-week rollup
    by_day: dict[str, dict] = {}
    for r in rows:
        d = r["day_of_week"]
        cur = by_day.setdefault(d, {
            "day_of_week": d, "spend": 0.0, "clicks": 0,
            "conversions": 0.0, "revenue": 0.0, "impressions": 0,
        })
        cur["spend"] += r["spend"]
        cur["clicks"] += r["clicks"]
        cur["conversions"] += r["conversions"]
        cur["revenue"] += r["revenue"]
        cur["impressions"] += r["impressions"]

    day_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    by_day_list = []
    for d in day_order:
        v = by_day.get(d, {"day_of_week": d, "spend": 0, "clicks": 0, "conversions": 0, "revenue": 0, "impressions": 0})
        spend = v["spend"]
        clicks = v["clicks"]
        conv = v["conversions"]
        v["cvr"] = (conv / clicks * 100) if clicks > 0 else 0
        v["roas"] = (v["revenue"] / spend) if spend > 0 else 0
        by_day_list.append(v)

    total_spend = sum(v["spend"] for v in by_hour_list)
    waste_hours = []
    peak_hours = []
    if total_spend > 0:
        for v in by_hour_list:
            spend_share = v["spend"] / total_spend
            # Waste: ≥3% spend share, zero conversions
            if spend_share >= 0.03 and v["conversions"] == 0:
                waste_hours.append({**v, "spend_share": spend_share})
            # Peak: ROAS ≥ 2 and ≥3% spend share
            if v["roas"] >= 2 and spend_share >= 0.03:
                peak_hours.append({**v, "spend_share": spend_share})

    waste_hours.sort(key=lambda v: v["spend"], reverse=True)
    peak_hours.sort(key=lambda v: v["roas"], reverse=True)

    return {
        "cells": rows,
        "by_hour": by_hour_list,
        "by_day": by_day_list,
        "waste_hours": waste_hours,
        "peak_hours": peak_hours,
    }
