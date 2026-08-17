"""Sync the CURRENT state of every Meta ad into meta_ad_states.

Backs the Status + Preview columns on the "Ad Name Performance" page.

ad_daily_metrics answers "what did this ad spend on day X"; this answers "is
that ad still running, and where can I look at it". Two Meta fields carry it:

  effective_status        what Meta actually delivers — folds the parent
                          adset/campaign switch and ad review into one value
                          (ACTIVE, PAUSED, ADSET_PAUSED, CAMPAIGN_PAUSED,
                          DISAPPROVED, PENDING_REVIEW, ARCHIVED, ...)
  preview_shareable_link  Meta's own render of the ad. Long-lived — unlike the
                          CDN asset URLs frozen by creative_sync — but only
                          openable by someone with access to the ad account.

One paginated get_ads() call per account, then delete-then-insert that
account's rows, so a re-run never leaves a stale status behind.

The caller owns the transaction — sync_meta_ad_states_for_account does NOT
commit.
"""
import logging
from datetime import datetime, timezone

from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount
from facebook_business.api import FacebookAdsApi
from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.meta_ad_state import MetaAdState

logger = logging.getLogger(__name__)

_AD_FIELDS = ["name", "status", "effective_status", "preview_shareable_link"]

# Ads the page can show. An ad that spent inside the window may since have been
# paused, archived or rejected, so the default get_ads() filter (active-ish
# only) would leave exactly the rows Mason most wants explained as "Unknown".
# DELETED is left out — Meta drops those from insights too.
_EFFECTIVE_STATUSES = [
    "ACTIVE", "PAUSED", "CAMPAIGN_PAUSED", "ADSET_PAUSED", "ARCHIVED",
    "DISAPPROVED", "PENDING_REVIEW", "PREAPPROVED", "PENDING_BILLING_INFO",
    "IN_PROCESS", "WITH_ISSUES",
]

_MAX_PREVIEW_URL = 1000


def sync_meta_ad_states_for_account(db: Session, account: AdAccount) -> dict:
    """Refresh meta_ad_states for one Meta account. Does NOT commit."""
    summary = {"rows_written": 0, "errors": []}

    if account.platform != "meta" or not account.access_token_enc:
        return summary

    acc_id = (
        account.account_id
        if account.account_id.startswith("act_")
        else f"act_{account.account_id}"
    )

    try:
        FacebookAdsApi.init(app_id="", app_secret="", access_token=account.access_token_enc)
        fb = FBAdAccount(acc_id)
        ads = fb.get_ads(
            fields=_AD_FIELDS,
            params={
                "limit": 500,
                "filtering": [
                    {"field": "ad.effective_status", "operator": "IN",
                     "value": _EFFECTIVE_STATUSES},
                ],
            },
        )
        # Materialise the paginated cursor BEFORE deleting: a mid-iteration API
        # failure would otherwise wipe the account's states and replace them
        # with a partial set.
        rows = list(ads)
    except Exception as e:
        logger.exception("[ad-state] failed to fetch ads for %s", account.account_name)
        summary["errors"].append(f"fetch ads: {e}")
        return summary

    db.query(MetaAdState).filter(
        MetaAdState.account_id == account.id
    ).delete(synchronize_session=False)

    now = datetime.now(timezone.utc)
    seen: set[str] = set()
    for ad in rows:
        ad_id = str(ad.get("id") or "").strip()
        if not ad_id or ad_id in seen:
            continue
        seen.add(ad_id)

        preview = ad.get("preview_shareable_link") or None
        if preview and len(preview) > _MAX_PREVIEW_URL:
            preview = None

        db.add(MetaAdState(
            account_id=account.id,
            ad_id=ad_id,
            ad_name=(ad.get("name") or None),
            status=(ad.get("status") or None),
            effective_status=(ad.get("effective_status") or None),
            preview_url=preview,
            synced_at=now,
        ))
        summary["rows_written"] += 1

    return summary


def sync_all_meta_ad_states(
    db: Session, account_ids: list[str] | None = None
) -> dict:
    """Refresh meta_ad_states for every active Meta account (or just
    `account_ids` when given). Commits once per account so one dead token
    cannot roll back the branches that succeeded."""
    q = db.query(AdAccount).filter(AdAccount.is_active.is_(True))
    if account_ids is not None:
        q = q.filter(AdAccount.id.in_(account_ids or ["__no_match__"]))
    accounts = q.all()
    totals = {"accounts": 0, "rows_written": 0, "errors": []}

    for account in accounts:
        if account.platform != "meta" or not account.access_token_enc:
            continue
        totals["accounts"] += 1
        try:
            res = sync_meta_ad_states_for_account(db, account)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.exception("[ad-state] sync failed for %s", account.account_name)
            totals["errors"].append(f"{account.account_name}: {e}")
            continue
        totals["rows_written"] += res["rows_written"]
        totals["errors"].extend(f"{account.account_name}: {e}" for e in res["errors"])
        logger.info(
            "[ad-state] %s: %d ads (%d errors)",
            account.account_name, res["rows_written"], len(res["errors"]),
        )

    logger.info(
        "[ad-state] done: %d ads across %d accounts",
        totals["rows_written"], totals["accounts"],
    )
    return totals
