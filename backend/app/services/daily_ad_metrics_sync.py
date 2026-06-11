"""Sync DAILY ad-level performance metrics from Meta into ad_daily_metrics.

Backs the "Ad Name Performance" page. Unlike combo_metrics_sync (one aggregated
row per ad_name for the whole window), this pulls a per-DAY breakdown
(`time_increment: 1`) and keeps the Meta platform identity at all three levels
(campaign / adset / ad) so each ad can be tracked day-by-day.

Only rows with spend > 0 are stored — Mason only cares about ads that actually
spent money.

Idempotent: for each account the window [since_date, today] is DELETED then
re-inserted, so re-runs (and Meta's attribution-window drift, where past days'
numbers shift slightly on re-fetch) never double-count.

Purchases use omni_purchase (Meta's pre-deduped unified purchase metric).
Leads sum the lead action types (website `lead` + instant-form lead actions).

The caller owns the transaction — sync_*_for_account does NOT commit.
"""
import logging
from datetime import date

from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount
from facebook_business.api import FacebookAdsApi
from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.ad_daily_metric import AdDailyMetric

logger = logging.getLogger(__name__)

# Mason: pull from May 2026 onward only — no need for deep history.
DEFAULT_SINCE = date(2026, 5, 1)

# Per-day, ad-level insight fields (time_increment=1 gives one row per ad/day).
_INSIGHT_FIELDS = [
    "campaign_id", "campaign_name", "adset_id", "adset_name",
    "ad_id", "ad_name",
    "spend", "impressions", "clicks",
    "actions", "action_values",
    "video_thruplay_watched_actions", "video_p100_watched_actions",
    "video_play_actions", "inline_post_engagement",
]

# Meta action_types that count as a "lead". Covers website pixel leads and
# instant-form (lead-gen) leads under the various groupings Meta returns.
_LEAD_ACTION_TYPES = {
    "lead",
    "onsite_conversion.lead_grouped",
    "leadgen_grouped",
    "leadgen.other",
}


def _first_value(arr) -> int:
    """Pull the integer value from Meta's [{'action_type':..., 'value':...}] list."""
    if not arr:
        return 0
    try:
        return int(arr[0].get("value", 0))
    except (KeyError, ValueError, TypeError):
        return 0


def _sum_actions(arr, action_types: set[str]) -> float:
    """Sum the values of actions whose action_type is in `action_types`."""
    total = 0.0
    for a in arr or []:
        if a.get("action_type") in action_types:
            try:
                total += float(a.get("value", 0))
            except (ValueError, TypeError):
                pass
    return total


def sync_daily_ad_metrics_for_account(
    db: Session,
    account: AdAccount,
    since_date: date = DEFAULT_SINCE,
    until_date: date | None = None,
) -> dict:
    """Pull per-day ad-level insights for one Meta account over
    [since_date, until_date] (until_date defaults to today) and replace the
    ad_daily_metrics rows for exactly that account window.

    Does NOT commit — the caller owns the transaction.
    """
    summary = {"rows_written": 0, "rows_skipped_no_spend": 0, "errors": []}

    if account.platform != "meta" or not account.access_token_enc:
        return summary

    acc_id = (
        account.account_id
        if account.account_id.startswith("act_")
        else f"act_{account.account_id}"
    )
    date_to = until_date or date.today()

    try:
        FacebookAdsApi.init(app_id="", app_secret="", access_token=account.access_token_enc)
        fb = FBAdAccount(acc_id)
        # One paginated account-level call at ad granularity, broken out per day.
        rows = fb.get_insights(
            fields=_INSIGHT_FIELDS,
            params={
                "level": "ad",
                "time_increment": 1,
                "time_range": {"since": since_date.isoformat(), "until": date_to.isoformat()},
            },
        )
    except Exception as e:
        logger.exception(
            "Daily ad metrics sync: failed to fetch insights for %s", account.account_id
        )
        summary["errors"].append(f"fetch insights: {e}")
        return summary

    # Delete-then-insert the window for this account. Done before iterating so a
    # fetch that returns fewer ads (paused/stopped spending) doesn't leave stale
    # rows behind.
    db.query(AdDailyMetric).filter(
        AdDailyMetric.account_id == account.id,
        AdDailyMetric.date >= since_date,
        AdDailyMetric.date <= date_to,
    ).delete(synchronize_session=False)

    for row in rows:
        spend = float(row.get("spend", 0) or 0)
        if spend <= 0:
            summary["rows_skipped_no_spend"] += 1
            continue

        ad_id = (row.get("ad_id") or "").strip()
        day_str = (row.get("date_start") or "").strip()
        if not ad_id or not day_str:
            continue
        try:
            day = date.fromisoformat(day_str)
        except ValueError:
            continue

        conversions = int(_sum_actions(row.get("actions"), {"omni_purchase"}))
        revenue = _sum_actions(row.get("action_values"), {"omni_purchase"})
        leads = int(_sum_actions(row.get("actions"), _LEAD_ACTION_TYPES))
        # video_view = Meta's 3-second video plays — the Ads Manager "Hook rate"
        # numerator. NOT video_play_actions, which counts every autoplay start.
        video_3s = int(_sum_actions(row.get("actions"), {"video_view"}))

        db.add(AdDailyMetric(
            account_id=account.id,
            campaign_id=(row.get("campaign_id") or None),
            campaign_name=(row.get("campaign_name") or None),
            adset_id=(row.get("adset_id") or None),
            adset_name=(row.get("adset_name") or None),
            ad_id=ad_id,
            ad_name=(row.get("ad_name") or None),
            date=day,
            spend=spend,
            impressions=int(row.get("impressions", 0) or 0),
            clicks=int(row.get("clicks", 0) or 0),
            conversions=conversions,
            revenue=revenue,
            leads=leads,
            engagement=int(row.get("inline_post_engagement", 0) or 0),
            video_plays=_first_value(row.get("video_play_actions")) or None,
            video_3s=video_3s or None,
            thruplay=_first_value(row.get("video_thruplay_watched_actions")) or None,
            video_p100=_first_value(row.get("video_p100_watched_actions")) or None,
        ))
        summary["rows_written"] += 1

    return summary


def sync_all_daily_ad_metrics(
    db: Session,
    since_date: date = DEFAULT_SINCE,
    until_date: date | None = None,
    account_ids: list[str] | None = None,
) -> dict:
    """Sync daily ad metrics over [since_date, until_date] (until_date defaults
    to today). When `account_ids` is given, only those accounts are synced;
    otherwise every active Meta account is. Commits once."""
    q = db.query(AdAccount).filter(AdAccount.is_active.is_(True))
    if account_ids is not None:
        q = q.filter(AdAccount.id.in_(account_ids or ["__no_match__"]))
    accounts = q.all()
    totals = {"accounts": 0, "rows_written": 0, "errors": []}

    for account in accounts:
        if account.platform != "meta" or not account.access_token_enc:
            continue
        totals["accounts"] += 1
        res = sync_daily_ad_metrics_for_account(
            db, account, since_date=since_date, until_date=until_date
        )
        totals["rows_written"] += res["rows_written"]
        totals["errors"].extend(f"{account.account_name}: {e}" for e in res["errors"])
        logger.info(
            "[ad-daily] %s: %d rows written (%d skipped no-spend, %d errors)",
            account.account_name, res["rows_written"],
            res["rows_skipped_no_spend"], len(res["errors"]),
        )

    db.commit()
    logger.info(
        "[ad-daily] done: %d rows across %d accounts (since=%s until=%s)",
        totals["rows_written"], totals["accounts"], since_date.isoformat(),
        (until_date or date.today()).isoformat(),
    )
    return totals
