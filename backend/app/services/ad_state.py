"""Read-side helpers over meta_ad_states — "is this ad still running, and
where do I look at it".

The rows are written by meta_ad_state_sync; this module is only about folding
them into an answer for one table row / drawer. It lives on its own so the Ad
Name Performance pivot and the Creative Library drawer cannot drift apart on
what "this creative is active" means.

Two ads can share an ad_name (same creative shipped into several campaigns),
so every lookup returns a fold, never a single row.
"""
from collections import Counter

from sqlalchemy.orm import Session

from app.models.meta_ad_state import MetaAdState

# Shape returned when nothing is known — an ad deleted from the account after
# it spent, or a branch that has not been synced yet. Rendered as "—".
NO_AD_STATE = {
    "effective_status": None,
    "active_count": 0,
    "state_count": 0,
    "preview_url": None,
}


def summarize_states(states: list) -> dict:
    """Fold the states of the ads behind one row into one verdict.

    A row is "on" if ANY of its ads is still delivering — that is the question
    being asked. The preview link prefers a live ad, so it opens something that
    is actually running.
    """
    if not states:
        return dict(NO_AD_STATE)
    active = [s for s in states if s.effective_status == "ACTIVE"]
    if active:
        status = "ACTIVE"
    else:
        common = Counter(
            s.effective_status for s in states if s.effective_status
        ).most_common(1)
        status = common[0][0] if common else None
    preview = next((s.preview_url for s in active if s.preview_url), None) or next(
        (s.preview_url for s in states if s.preview_url), None
    )
    return {
        "effective_status": status,
        "active_count": len(active),
        "state_count": len(states),
        "preview_url": preview,
    }


def state_for_ad_name(db: Session, account_id: str | None, ad_name: str | None) -> dict:
    """State of every ad called `ad_name` inside one branch.

    Matching is by NAME, not ad_id: ad_combos never stores the Meta ad_id. So a
    creative renamed on Meta after launch stops matching and reads as unknown —
    which is the honest answer, better than linking the wrong ad.
    """
    if not account_id or not ad_name:
        return dict(NO_AD_STATE)
    rows = (
        db.query(MetaAdState)
        .filter(MetaAdState.account_id == account_id, MetaAdState.ad_name == ad_name)
        .all()
    )
    return summarize_states(rows)
