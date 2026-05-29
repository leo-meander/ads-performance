"""Meta Insights API caller for today's intraday metrics.

Single function: `fetch_today_metrics(access_token, platform_campaign_id)`
returns `{spend, revenue, conversions, raw}` aggregated for the campaign
from the start of the account's local day to "now" — same data Meta Ads
Manager UI shows but via API.

We compute ROAS as `revenue / spend` rather than trusting Meta's
`purchase_roas` field. Reason: the rest of the codebase aggregates only
`omni_purchase`, while `purchase_roas` mixes all purchase action types.
Keeping a single semantic across sync_engine, daily_ad_metrics_sync, and
this module avoids cross-source drift.

NOTE on time semantics: `date_preset='today'` is computed by Meta in the
AD ACCOUNT's timezone. Our SurfRun uses the BRANCH timezone (which is
usually the same as the account tz, but not always). The engine treats the
returned numbers as "spend so far today (account-local-day)" — close enough
for threshold crossing, with up to ~1h drift in edge cases (e.g. account
set to UTC while branch is Asia/Ho_Chi_Minh).
"""

from __future__ import annotations

import logging
from typing import Any

from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount
from facebook_business.api import FacebookAdsApi

logger = logging.getLogger(__name__)


# Same vocabulary as backend/app/services/meta_client.py:218 +
# backend/app/services/daily_ad_metrics_sync.py:144 — keep aligned so cross-
# surface comparisons (intraday vs daily) match.
_PURCHASE_TYPES = {"omni_purchase"}

# Minimal field set — anything more bloats the response and we never use it
# for threshold/tier decisions.
_INSIGHT_FIELDS = ["spend", "actions", "action_values", "campaign_id"]


def fetch_today_metrics(
    *,
    access_token: str,
    platform_account_id: str,
    platform_campaign_id: str,
) -> dict[str, Any]:
    """Return today's accumulated metrics for one campaign.

    Returns:
      {
        "spend":       float,   # native account currency
        "revenue":     float,   # omni_purchase action_values
        "conversions": int,     # omni_purchase action counts
        "roas":        float | None,  # revenue/spend or None if spend=0
        "raw":         dict,    # the raw Meta row for forward-compat audit
      }

    Raises on Meta API errors — caller decides whether to mark the run as
    errored or just log and retry.
    """
    FacebookAdsApi.init(app_id="", app_secret="", access_token=access_token)

    # AdAccount ID expected by SDK starts with 'act_'. Some callers already
    # pass it with the prefix; some don't.
    acc_id = (
        platform_account_id
        if platform_account_id.startswith("act_")
        else f"act_{platform_account_id}"
    )
    fb = FBAdAccount(acc_id)

    rows = list(
        fb.get_insights(
            fields=_INSIGHT_FIELDS,
            params={
                "level": "campaign",
                # date_preset='today' = since account-local midnight.
                "date_preset": "today",
                # filter to this single campaign — no time_increment so we
                # get one accumulated row, not a per-hour breakdown.
                "filtering": [
                    {"field": "campaign.id", "operator": "EQUAL",
                     "value": platform_campaign_id},
                ],
            },
        )
    )

    if not rows:
        # No spend yet today → Meta returns no rows. Treat as zero, not as
        # error: the campaign is live but hasn't fired any impressions yet.
        logger.info(
            "[surf-meta] no insights for campaign %s today (zero spend)",
            platform_campaign_id,
        )
        return {
            "spend": 0.0,
            "revenue": 0.0,
            "conversions": 0,
            "roas": None,
            "raw": {},
        }

    # Defensive: Meta should return exactly 1 row given the campaign filter,
    # but if it returns more (e.g. campaign duplicated) we sum.
    spend = 0.0
    revenue = 0.0
    conversions = 0
    raw_dump = []
    for row in rows:
        spend += float(row.get("spend", 0) or 0)
        for a in row.get("actions") or []:
            if a.get("action_type") in _PURCHASE_TYPES:
                conversions += int(a.get("value", 0) or 0)
        for av in row.get("action_values") or []:
            if av.get("action_type") in _PURCHASE_TYPES:
                revenue += float(av.get("value", 0) or 0)
        raw_dump.append(dict(row))

    roas: float | None = None
    if spend > 0:
        roas = revenue / spend

    return {
        "spend": spend,
        "revenue": revenue,
        "conversions": conversions,
        "roas": roas,
        "raw": {"rows": raw_dump},
    }
