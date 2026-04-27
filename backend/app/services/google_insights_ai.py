"""LLM-generated combined narrative for Google Ads insights.

Takes the rule-based per-panel output (search terms, devices, locations,
hours) and asks Claude to weave them into a single actionable diagnosis
following the playbook style in CLAUDE.md.
"""

import json
import logging
from collections.abc import Generator

from anthropic import Anthropic

from app.config import settings

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a senior Google Ads strategist for MEANDER Group hotels.

You synthesize per-dimension data into a single, sharp diagnosis using this style:

> ❌ Pattern: <what the data shows>
> 👉 Insight: <root cause inference>
> 👉 Action: <specific next step>

Rules for your output:
- Lead with the 1–3 most actionable findings, not a generic summary.
- Combine signals across dimensions (e.g. "mobile CTR healthy + mobile CVR < 50% of desktop + relevant high-intent search terms" → landing page bottleneck on mobile).
- Quote specific numbers from the data — never round so much that the reader can't verify.
- If data is sparse (low spend, < 30 clicks across the period), say so and stop. Do NOT invent patterns.
- Output Vietnamese if the campaign name contains Vietnamese, otherwise English.
- Use markdown. Keep it under ~250 words. No fluff.
"""


def _summarize_for_prompt(insights: dict) -> str:
    """Compact JSON-like summary that fits in a prompt without 50KB of rows."""

    def top_n(rows, n, keys):
        return [{k: r.get(k) for k in keys} for r in rows[:n]]

    summary: dict = {
        "campaign": insights.get("campaign", {}),
        "date_range": insights.get("date_range"),
        "totals": insights.get("totals", {}),
    }

    st = insights.get("search_terms")
    if st:
        summary["search_terms"] = {
            "total_terms": st.get("total_terms"),
            "by_intent": {k: {kk: round(vv, 2) if isinstance(vv, (int, float)) else vv
                              for kk, vv in v.items() if kk in ("term_count", "spend", "clicks", "conversions", "ctr", "cvr", "roas")}
                          for k, v in (st.get("by_intent") or {}).items()},
            "by_brand": {k: {kk: round(vv, 2) if isinstance(vv, (int, float)) else vv
                             for kk, vv in v.items() if kk in ("term_count", "spend", "clicks", "conversions", "cvr", "roas")}
                         for k, v in (st.get("by_brand") or {}).items()},
            "top_winners": top_n(st.get("winners") or [], 5, ["search_term", "spend", "clicks", "conversions", "roas", "cvr"]),
            "top_junk": top_n(st.get("junk_terms") or [], 5, ["search_term", "intent", "spend", "clicks", "conversions"]),
            "intent_match_no_conv": top_n(st.get("intent_match_no_conv") or [], 5, ["search_term", "intent", "spend", "clicks"]),
        }

    pmax_cats = insights.get("pmax_categories")
    if pmax_cats:
        summary["pmax_search_categories"] = top_n(pmax_cats, 10, ["category", "impressions", "clicks", "conversions", "cvr"])

    devices = insights.get("devices")
    if devices:
        summary["devices"] = {
            "rows": [{k: round(v, 2) if isinstance(v, (int, float)) else v
                      for k, v in d.items() if k in ("device", "spend", "clicks", "conversions", "ctr", "cvr", "cpa", "roas")}
                     for d in devices.get("devices", [])],
            "flags": devices.get("flags", []),
        }

    locations = insights.get("locations")
    if locations:
        summary["locations"] = {
            "summary": locations.get("summary"),
            "junk": top_n(locations.get("junk") or [], 5, ["country", "spend", "clicks", "conversions", "spend_share"]),
            "winners": top_n(locations.get("winners") or [], 5, ["country", "spend", "conversions", "roas"]),
        }

    time_of_day = insights.get("time_of_day")
    if time_of_day:
        summary["time_of_day"] = {
            "by_hour": [{k: round(v, 2) if isinstance(v, (int, float)) else v
                         for k, v in h.items() if k in ("hour", "spend", "clicks", "conversions", "cvr", "roas")}
                        for h in time_of_day.get("by_hour", [])],
            "by_day": [{k: round(v, 2) if isinstance(v, (int, float)) else v
                        for k, v in d.items() if k in ("day_of_week", "spend", "clicks", "conversions", "cvr", "roas")}
                       for d in time_of_day.get("by_day", [])],
            "waste_hours": top_n(time_of_day.get("waste_hours") or [], 5, ["hour", "spend", "clicks", "spend_share"]),
            "peak_hours": top_n(time_of_day.get("peak_hours") or [], 5, ["hour", "spend", "conversions", "roas"]),
        }

    return json.dumps(summary, ensure_ascii=False, indent=2, default=str)


def stream_combined_narrative(insights: dict) -> Generator[str, None, None]:
    """Stream Claude's combined diagnosis. Yields plain text chunks."""
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    payload = _summarize_for_prompt(insights)

    user_message = (
        "Below is the per-panel insight data for one Google Ads campaign. "
        "Synthesize the most important cross-dimension findings.\n\n"
        f"```json\n{payload}\n```"
    )

    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text in stream.text_stream:
            yield text
