"""Read-side helpers over the `ads` table — "is this ad still running, and
where do I look at it".

The rows are written by sync_engine.sync_meta_account (twice-daily platform
cron); this module is only about folding them into an answer for one table row
or drawer. It lives on its own so the Ad Name Performance pivot and the
Creative Library drawer cannot drift apart on what "this creative is active"
means.

Two ads can share an ad_name — the same creative shipped into several
campaigns — so every lookup returns a fold, never a single row. That is also
why the whole creative subsystem is keyed by ad_name rather than ad_id, and
why renames are carried over by creative_sync.apply_ad_renames instead of
being routed around with a second id-based link.
"""
from collections import Counter

from sqlalchemy.orm import Session

from app.models.ad import Ad

# Shape returned when nothing is known — an ad archived or deleted on Meta
# (fetch_ads only returns live-ish ads), or an account not synced yet.
# Rendered as "—".
NO_AD_STATE = {
    "effective_status": None,
    "active_count": 0,
    "state_count": 0,
    "preview_url": None,
}


def summarize_states(ads: list) -> dict:
    """Fold the ads behind one row into one verdict.

    A row is "on" if ANY of its ads is still delivering — that is the question
    being asked. The preview link prefers a live ad, so it opens something that
    is actually running.

    Falls back to `status` (the ad's own switch) when `effective_status` is
    missing, which is every row synced before migration 070.
    """
    if not ads:
        return dict(NO_AD_STATE)
    resolved = [(a, a.effective_status or a.status) for a in ads]
    active = [a for a, st in resolved if st == "ACTIVE"]
    if active:
        status = "ACTIVE"
    else:
        common = Counter(st for _, st in resolved if st).most_common(1)
        status = common[0][0] if common else None
    preview = next((a.preview_url for a in active if a.preview_url), None) or next(
        (a.preview_url for a in ads if a.preview_url), None
    )
    return {
        "effective_status": status,
        "active_count": len(active),
        "state_count": len(ads),
        "preview_url": preview,
    }


def state_for_ad_name(db: Session, account_id: str | None, ad_name: str | None) -> dict:
    """State of every Meta ad called `ad_name` inside one branch."""
    if not account_id or not ad_name:
        return dict(NO_AD_STATE)
    rows = (
        db.query(Ad)
        .filter(
            Ad.account_id == account_id,
            Ad.platform == "meta",
            Ad.name == ad_name,
        )
        .all()
    )
    return summarize_states(rows)
