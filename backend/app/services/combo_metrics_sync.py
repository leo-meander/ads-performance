"""Sync ad-level performance metrics from Meta into the ad_combos table.

A combo == a unique ad_name within a branch. Multiple Meta ads can share the
same name (different ad_ids); their metrics are SUMMED into the one combo row.

Idempotent: metrics are OVERWRITTEN on the combo row (combo.spend = ..., never
+=), so re-running for any window — including overlapping windows — recomputes
the totals from scratch and never double-counts.

Purchases use omni_purchase — Meta's pre-deduped unified purchase metric
(pixel + onsite + in-store + app). See memory: feedback_meta_action_types.
"""
import logging
from collections import defaultdict
from datetime import date, timedelta

from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount
from facebook_business.api import FacebookAdsApi
from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.ad_combo import AdCombo

logger = logging.getLogger(__name__)

# Ad-level insight fields. No time_increment is requested — we want one
# aggregated row per ad for the whole window, not a daily breakdown.
_INSIGHT_FIELDS = [
    "ad_name", "spend", "impressions", "clicks",
    "actions", "action_values",
    "video_thruplay_watched_actions", "video_p100_watched_actions",
    "video_play_actions", "inline_post_engagement",
]


def _first_value(arr) -> int:
    """Pull the integer value from Meta's [{'action_type':..., 'value':...}] list."""
    if not arr:
        return 0
    try:
        return int(arr[0].get("value", 0))
    except (KeyError, ValueError, TypeError):
        return 0


def sync_combo_metrics_for_account(
    db: Session, account: AdAccount, days_back: int = 45
) -> dict:
    """Pull ad-level insights for one Meta account over the last `days_back`
    days and overwrite the matching ad_combos rows. Does NOT commit — the
    caller owns the transaction.
    """
    summary = {"combos_updated": 0, "ad_names": 0, "errors": []}

    if account.platform != "meta" or not account.access_token_enc:
        return summary

    acc_id = (
        account.account_id
        if account.account_id.startswith("act_")
        else f"act_{account.account_id}"
    )
    date_to = date.today()
    date_from = date_to - timedelta(days=days_back)

    # (ad_name) -> aggregated totals. Reset per account.
    agg: dict[str, dict] = defaultdict(lambda: {
        "spend": 0.0, "impressions": 0, "clicks": 0,
        "conversions": 0, "revenue": 0.0, "engagement": 0,
        "video_plays": 0, "thruplay": 0, "video_p100": 0,
    })

    try:
        FacebookAdsApi.init(app_id="", app_secret="", access_token=account.access_token_enc)
        fb = FBAdAccount(acc_id)
        # One paginated account-level call at ad granularity — far cheaper than
        # one get_insights() per ad. Naturally covers every ad that delivered
        # in the window (active, paused, or archived).
        rows = fb.get_insights(
            fields=_INSIGHT_FIELDS,
            params={
                "level": "ad",
                "time_range": {"since": date_from.isoformat(), "until": date_to.isoformat()},
            },
        )
    except Exception as e:
        logger.exception(
            "Combo metrics sync: failed to fetch insights for %s", account.account_id
        )
        summary["errors"].append(f"fetch insights: {e}")
        return summary

    for row in rows:
        ad_name = (row.get("ad_name") or "").strip()
        if not ad_name:
            continue
        b = agg[ad_name]
        b["spend"] += float(row.get("spend", 0) or 0)
        b["impressions"] += int(row.get("impressions", 0) or 0)
        b["clicks"] += int(row.get("clicks", 0) or 0)
        b["engagement"] += int(row.get("inline_post_engagement", 0) or 0)
        for a in row.get("actions") or []:
            if a.get("action_type") == "omni_purchase":
                b["conversions"] += int(a.get("value", 0))
        for av in row.get("action_values") or []:
            if av.get("action_type") == "omni_purchase":
                b["revenue"] += float(av.get("value", 0))
        b["video_plays"] += _first_value(row.get("video_play_actions"))
        b["thruplay"] += _first_value(row.get("video_thruplay_watched_actions"))
        b["video_p100"] += _first_value(row.get("video_p100_watched_actions"))

    summary["ad_names"] = len(agg)

    # Overwrite metrics on the matching combo row. Assignment (=) not += — this
    # is what keeps repeated/overlapping runs free of double-counting.
    for ad_name, m in agg.items():
        combo = (
            db.query(AdCombo)
            .filter(AdCombo.branch_id == account.id, AdCombo.ad_name == ad_name)
            .first()
        )
        if not combo:
            continue

        spend = m["spend"]
        impressions = m["impressions"]
        clicks = m["clicks"]
        conversions = m["conversions"]
        revenue = m["revenue"]
        engagement = m["engagement"]
        video_plays = m["video_plays"]
        thruplay = m["thruplay"]
        video_p100 = m["video_p100"]

        combo.spend = spend
        combo.impressions = impressions
        combo.clicks = clicks
        combo.conversions = conversions
        combo.revenue = revenue
        combo.engagement = engagement
        combo.video_plays = video_plays or None
        combo.thruplay = thruplay or None
        combo.video_p100 = video_p100 or None

        combo.roas = (revenue / spend) if spend > 0 else 0
        combo.cost_per_purchase = (spend / conversions) if conversions > 0 else None
        combo.ctr = (clicks / impressions) if impressions > 0 else None
        combo.engagement_rate = (engagement / impressions) if impressions > 0 else None
        combo.hook_rate = (video_plays / impressions) if video_plays and impressions > 0 else None
        combo.thruplay_rate = (thruplay / video_plays) if thruplay and video_plays > 0 else None
        combo.video_complete_rate = (video_p100 / video_plays) if video_p100 and video_plays > 0 else None

        summary["combos_updated"] += 1

    return summary


def sync_all_combo_metrics(db: Session, days_back: int = 45) -> dict:
    """Sync combo metrics for every active Meta account. Commits once at the end."""
    accounts = db.query(AdAccount).filter(AdAccount.is_active.is_(True)).all()
    totals = {"accounts": 0, "combos_updated": 0, "errors": []}

    for account in accounts:
        if account.platform != "meta" or not account.access_token_enc:
            continue
        totals["accounts"] += 1
        res = sync_combo_metrics_for_account(db, account, days_back=days_back)
        totals["combos_updated"] += res["combos_updated"]
        totals["errors"].extend(f"{account.account_name}: {e}" for e in res["errors"])
        logger.info(
            "[combo-metrics] %s: %d combos updated (%d ad_names, %d errors)",
            account.account_name, res["combos_updated"], res["ad_names"], len(res["errors"]),
        )

    db.commit()
    logger.info(
        "[combo-metrics] done: %d combos updated across %d accounts (days_back=%d)",
        totals["combos_updated"], totals["accounts"], days_back,
    )
    return totals
