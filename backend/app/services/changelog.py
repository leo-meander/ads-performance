"""Changelog helper — single write path for ChangeLogEntry.

Every call site (rule engine, launch service, manual POST route) goes through
``log_change(...)``. The helper resolves entity context (country, branch,
platform) from whichever FK IDs the caller passes, captures a baseline metrics
snapshot on demand, and formats before/after diffs.

Invariant: log_change NEVER raises. Any exception inside is swallowed + logged,
so a changelog write can never break the underlying ad operation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.branches import resolve_branch_for_account_name
from app.models.account import AdAccount
from app.models.ad import Ad
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.models.change_log_entry import ALL_CATEGORIES, ChangeLogEntry
from app.services.metrics_snapshot import get_metrics_snapshot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Context resolution
# ---------------------------------------------------------------------------

def resolve_entity_context(
    db: Session,
    *,
    ad_id: str | None = None,
    ad_set_id: str | None = None,
    campaign_id: str | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Walk the FK chain upward and return the full entity context.

    Returns dict with keys: country, branch, platform, account_id, campaign_id,
    ad_set_id, ad_id. Any field that can't be resolved is None.
    """
    ctx: dict[str, Any] = {
        "ad_id": ad_id,
        "ad_set_id": ad_set_id,
        "campaign_id": campaign_id,
        "account_id": account_id,
        "platform": None,
        "country": None,
        "branch": None,
    }

    ad = None
    ad_set = None
    campaign = None
    account = None

    if ad_id:
        ad = db.query(Ad).filter(Ad.id == ad_id).first()
        if ad:
            ctx["ad_set_id"] = ctx["ad_set_id"] or ad.ad_set_id
            ctx["campaign_id"] = ctx["campaign_id"] or ad.campaign_id
            ctx["account_id"] = ctx["account_id"] or ad.account_id
            ctx["platform"] = ctx["platform"] or ad.platform

    if ctx["ad_set_id"]:
        ad_set = db.query(AdSet).filter(AdSet.id == ctx["ad_set_id"]).first()
        if ad_set:
            ctx["campaign_id"] = ctx["campaign_id"] or ad_set.campaign_id
            ctx["account_id"] = ctx["account_id"] or ad_set.account_id
            ctx["platform"] = ctx["platform"] or ad_set.platform
            ctx["country"] = ctx["country"] or ad_set.country

    if not ctx["country"] and ctx["campaign_id"]:
        # Derive country from any adset of the campaign. Multi-country → 'ALL'.
        adset_countries = (
            db.query(AdSet.country)
            .filter(AdSet.campaign_id == ctx["campaign_id"])
            .distinct()
            .all()
        )
        distinct_countries = {c[0] for c in adset_countries if c[0]}
        if len(distinct_countries) == 1:
            ctx["country"] = distinct_countries.pop()
        elif len(distinct_countries) > 1:
            ctx["country"] = "ALL"

    if ctx["campaign_id"]:
        campaign = db.query(Campaign).filter(Campaign.id == ctx["campaign_id"]).first()
        if campaign:
            ctx["account_id"] = ctx["account_id"] or campaign.account_id
            ctx["platform"] = ctx["platform"] or campaign.platform

    if ctx["account_id"]:
        account = db.query(AdAccount).filter(AdAccount.id == ctx["account_id"]).first()
        if account:
            ctx["platform"] = ctx["platform"] or account.platform
            ctx["branch"] = resolve_branch_for_account_name(account.account_name)

    return ctx


# ---------------------------------------------------------------------------
# Baseline capture
# ---------------------------------------------------------------------------

def capture_baseline_snapshot(
    db: Session,
    *,
    ad_id: str | None = None,
    ad_set_id: str | None = None,
    campaign_id: str | None = None,
    days: int = 7,
) -> dict | None:
    """Capture an aggregated N-day metrics snapshot for the most-specific scope
    provided. Returns None if no scope or if the query fails — never raises."""
    try:
        if ad_id:
            return get_metrics_snapshot(db, ad_id, "ad", days=days)
        if ad_set_id:
            return get_metrics_snapshot(db, ad_set_id, "ad_set", days=days)
        if campaign_id:
            return get_metrics_snapshot(db, campaign_id, "campaign", days=days)
    except Exception:
        logger.exception("capture_baseline_snapshot failed")
    return None


# ---------------------------------------------------------------------------
# Diff description
# ---------------------------------------------------------------------------

def describe_diff(before: dict | None, after: dict | None) -> str | None:
    """Produce a short human title for a before/after pair. Returns None if
    nothing meaningful can be described."""
    if not before and not after:
        return None
    before = before or {}
    after = after or {}

    # Status flip
    if "status" in before or "status" in after:
        b = before.get("status", "?")
        a = after.get("status", "?")
        if b != a:
            return f"Status {b} → {a}"

    # Budget change (daily or lifetime)
    for key, label in (("daily_budget", "Daily budget"), ("lifetime_budget", "Lifetime budget")):
        if key in before or key in after:
            b = before.get(key)
            a = after.get(key)
            if b is None and a is None:
                continue
            if b and a:
                try:
                    pct = (float(a) - float(b)) / float(b) * 100 if float(b) > 0 else 0
                    sign = "+" if pct >= 0 else ""
                    return f"{label} {_fmt_money(b)} → {_fmt_money(a)} ({sign}{pct:.0f}%)"
                except (TypeError, ValueError):
                    pass
            return f"{label} {_fmt_money(b)} → {_fmt_money(a)}"

    # Fallback: list keys that differ
    keys = sorted(set(before.keys()) | set(after.keys()))
    diff_keys = [k for k in keys if before.get(k) != after.get(k)]
    if diff_keys:
        return f"Changed: {', '.join(diff_keys)}"
    return None


def _fmt_money(val: Any) -> str:
    if val is None:
        return "?"
    try:
        n = float(val)
        if n == int(n):
            return f"{int(n):,}"
        return f"{n:,.2f}"
    except (TypeError, ValueError):
        return str(val)


# ---------------------------------------------------------------------------
# Core write path
# ---------------------------------------------------------------------------

def log_change(
    db: Session,
    *,
    category: str,
    title: str,
    source: str = "auto",
    triggered_by: str = "rule",
    occurred_at: datetime | None = None,
    description: str | None = None,
    country: str | None = None,
    branch: str | None = None,
    platform: str | None = None,
    account_id: str | None = None,
    campaign_id: str | None = None,
    ad_set_id: str | None = None,
    ad_id: str | None = None,
    before_value: dict | None = None,
    after_value: dict | None = None,
    metrics_snapshot: dict | None = None,
    source_url: str | None = None,
    author_user_id: str | None = None,
    action_log_id: str | None = None,
    rule_id: str | None = None,
    commit: bool = False,
) -> ChangeLogEntry | None:
    """Write one ChangeLogEntry. Auto-resolves country/branch/platform/account
    from ad/ad_set/campaign/account IDs for any fields the caller left None.

    Never raises — failures are logged and return None so a changelog bug can
    never roll back the underlying ad operation.
    """
    try:
        if category not in ALL_CATEGORIES:
            logger.warning("log_change: unknown category %r", category)
            return None

        if source not in {"auto", "manual"}:
            logger.warning("log_change: invalid source %r", source)
            return None

        ctx = resolve_entity_context(
            db,
            ad_id=ad_id,
            ad_set_id=ad_set_id,
            campaign_id=campaign_id,
            account_id=account_id,
        )

        entry = ChangeLogEntry(
            occurred_at=occurred_at or datetime.now(timezone.utc),
            category=category,
            source=source,
            triggered_by=triggered_by,
            title=title[:200],
            description=description,
            country=country if country is not None else ctx["country"],
            branch=branch if branch is not None else ctx["branch"],
            platform=platform if platform is not None else ctx["platform"],
            account_id=account_id if account_id is not None else ctx["account_id"],
            campaign_id=campaign_id if campaign_id is not None else ctx["campaign_id"],
            ad_set_id=ad_set_id if ad_set_id is not None else ctx["ad_set_id"],
            ad_id=ad_id if ad_id is not None else ctx["ad_id"],
            before_value=before_value,
            after_value=after_value,
            metrics_snapshot=metrics_snapshot,
            source_url=source_url,
            author_user_id=author_user_id,
            action_log_id=action_log_id,
            rule_id=rule_id,
            is_deleted=False,
        )
        db.add(entry)
        if commit:
            db.commit()
        else:
            db.flush()
        return entry
    except Exception:
        logger.exception("log_change failed — swallowed to protect caller")
        try:
            db.rollback()
        except Exception:
            pass
        return None
