"""Monthly winning-creative awards — computed from ad_daily_metrics, then FROZEN.

Why this exists
---------------
The Creative Library verdict is dynamic: each combo's LIFETIME ROAS is compared
against the account's CURRENT blended ROAS. Move the benchmark and yesterday's
WIN becomes today's LOSE, so "how many winners did we ship in May?" has no
stable answer.

This module answers it. For every (account, calendar month) it aggregates
ad_daily_metrics per ad_name, computes that month's benchmark, applies the
same verdict rules the Library uses, and INSERTs the winners into
winning_ad_months. Rows are append-only: re-running can award NEW winners to a
past month, but never rewrites or removes one that was already awarded — the
roas / benchmark / bookings stored on the row are the numbers as of the award.

Scope: only ads whose name contains "CRTV" (the creative-team naming
convention). The filter applies to candidates AND to the benchmark, so KOL and
other non-creative traffic never moves the bar.
"""
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func as sf
from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_daily_metric import AdDailyMetric
from app.models.winning_ad_month import WinningAdMonth
from app.services.creative_service import classify_verdict

logger = logging.getLogger(__name__)

# Creative-team naming convention. Case-insensitive so "crtv"/"Crtv" also match.
CRTV_TOKEN = "CRTV"
_CRTV_LIKE = f"%{CRTV_TOKEN}%"


def is_crtv(ad_name: str | None) -> bool:
    return bool(ad_name) and CRTV_TOKEN in ad_name.upper()


def month_start(d: date) -> date:
    return d.replace(day=1)


def month_end(d: date) -> date:
    """Last day of the month `d` falls in."""
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def months_between(first: date, last: date) -> list[date]:
    """Every month start from `first`'s month through `last`'s month."""
    out: list[date] = []
    cur = month_start(first)
    stop = month_start(last)
    while cur <= stop:
        out.append(cur)
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)
    return out


def compute_month_winners(db: Session, account_id: str, month: date) -> tuple[list[dict], float]:
    """Aggregate one account-month and pick the winners.

    Returns (winners, benchmark_roas). `winners` carries the frozen numbers;
    `benchmark_roas` is the account's blended CRTV ROAS for that month — the
    bar every candidate was measured against.
    """
    start = month_start(month)
    end = month_end(start)

    rows = (
        db.query(
            AdDailyMetric.ad_name.label("ad_name"),
            sf.sum(AdDailyMetric.spend).label("spend"),
            sf.sum(AdDailyMetric.revenue).label("revenue"),
            sf.sum(AdDailyMetric.impressions).label("impressions"),
            sf.sum(AdDailyMetric.clicks).label("clicks"),
            sf.sum(AdDailyMetric.conversions).label("conversions"),
        )
        .filter(
            AdDailyMetric.account_id == account_id,
            AdDailyMetric.date >= start,
            AdDailyMetric.date <= end,
            AdDailyMetric.ad_name.isnot(None),
            AdDailyMetric.ad_name.ilike(_CRTV_LIKE),
        )
        .group_by(AdDailyMetric.ad_name)
        .all()
    )
    if not rows:
        return [], 0.0

    total_spend = sum(float(r.spend or 0) for r in rows)
    total_revenue = sum(float(r.revenue or 0) for r in rows)
    benchmark = total_revenue / total_spend if total_spend > 0 else 0.0

    winners: list[dict] = []
    for r in rows:
        spend = float(r.spend or 0)
        revenue = float(r.revenue or 0)
        clicks = int(r.clicks or 0)
        conversions = int(r.conversions or 0)
        roas = revenue / spend if spend > 0 else 0.0
        if classify_verdict(clicks, conversions, roas, benchmark) != "WIN":
            continue
        winners.append({
            "ad_name": r.ad_name,
            "spend": spend,
            "revenue": revenue,
            "impressions": int(r.impressions or 0),
            "clicks": clicks,
            "conversions": conversions,
            "roas": roas,
        })
    return winners, benchmark


def freeze_winning_months(
    db: Session, account_ids: list[str] | None = None, since: date | None = None
) -> dict:
    """Award (and permanently freeze) monthly winners across every Meta account.

    Idempotent and append-only: an (account, month, ad_name) that already has a
    row is left untouched — its frozen roas/benchmark stay as first written.
    Commits once at the end.
    """
    accounts = db.query(AdAccount).filter(
        AdAccount.platform == "meta", AdAccount.is_active.is_(True)
    )
    if account_ids is not None:
        accounts = accounts.filter(AdAccount.id.in_(account_ids or ["__no_match__"]))
    accounts = accounts.all()

    now = datetime.now(timezone.utc)
    summary = {"accounts": 0, "months": 0, "awarded": 0, "already_frozen": 0}

    for acc in accounts:
        bounds = (
            db.query(sf.min(AdDailyMetric.date), sf.max(AdDailyMetric.date))
            .filter(AdDailyMetric.account_id == acc.id)
            .first()
        )
        if not bounds or not bounds[0]:
            continue
        first, last = bounds[0], bounds[1]
        if since and since > first:
            first = since
        if first > last:
            continue
        summary["accounts"] += 1

        # ad_name → combo, so an award can deep-link into the Creative Library.
        combo_map = {
            c.ad_name: c
            for c in db.query(AdCombo).filter(AdCombo.branch_id == acc.id).all()
            if c.ad_name
        }

        for m in months_between(first, last):
            winners, benchmark = compute_month_winners(db, acc.id, m)
            if not winners:
                continue
            summary["months"] += 1

            existing = {
                r[0]
                for r in db.query(WinningAdMonth.ad_name)
                .filter(WinningAdMonth.account_id == acc.id, WinningAdMonth.month == m)
                .all()
            }
            for w in winners:
                if w["ad_name"] in existing:
                    summary["already_frozen"] += 1
                    continue
                combo = combo_map.get(w["ad_name"])
                db.add(WinningAdMonth(
                    account_id=acc.id,
                    month=m,
                    ad_name=w["ad_name"],
                    combo_id=combo.combo_id if combo else None,
                    target_audience=combo.target_audience if combo else None,
                    country=combo.country if combo else None,
                    spend=w["spend"],
                    revenue=w["revenue"],
                    impressions=w["impressions"],
                    clicks=w["clicks"],
                    conversions=w["conversions"],
                    roas=w["roas"],
                    benchmark_roas=benchmark,
                    frozen_at=now,
                ))
                summary["awarded"] += 1

    db.commit()
    logger.info(
        "[winning-months] %d newly awarded, %d already frozen across %d accounts",
        summary["awarded"], summary["already_frozen"], summary["accounts"],
    )
    return summary


def list_winning_months(
    db: Session,
    account_ids: list[str] | None = None,
    branch_id: str | None = None,
    month: str | None = None,
) -> dict:
    """Frozen awards grouped by month, newest month first.

    `account_ids=None` means "no scoping" (admin). `month` (YYYY-MM) narrows
    the ad list to one month; the per-month counts always cover every month so
    the trend never collapses to a single bar.
    """
    q = db.query(WinningAdMonth)
    if branch_id:
        q = q.filter(WinningAdMonth.account_id == branch_id)
    elif account_ids is not None:
        q = q.filter(WinningAdMonth.account_id.in_(account_ids or ["__no_match__"]))
    rows = q.order_by(WinningAdMonth.month.desc(), WinningAdMonth.roas.desc().nullslast()).all()

    acc_names = {
        a.id: a.account_name
        for a in db.query(AdAccount.id, AdAccount.account_name).all()
    }

    buckets: dict[str, dict] = {}
    for r in rows:
        key = r.month.isoformat()[:7]
        b = buckets.setdefault(key, {
            "month": key, "count": 0, "spend": 0.0, "revenue": 0.0,
            "conversions": 0, "by_branch": {}, "ads": [],
        })
        b["count"] += 1
        b["spend"] += float(r.spend or 0)
        b["revenue"] += float(r.revenue or 0)
        b["conversions"] += int(r.conversions or 0)
        name = acc_names.get(r.account_id, "—")
        b["by_branch"][name] = b["by_branch"].get(name, 0) + 1
        b["ads"].append({
            "id": r.id,
            "ad_name": r.ad_name,
            "account_id": r.account_id,
            "branch_name": name,
            "combo_id": r.combo_id,
            "target_audience": r.target_audience,
            "country": r.country,
            "spend": float(r.spend) if r.spend is not None else None,
            "revenue": float(r.revenue) if r.revenue is not None else None,
            "impressions": r.impressions,
            "clicks": r.clicks,
            "conversions": r.conversions,
            "roas": float(r.roas) if r.roas is not None else None,
            "benchmark_roas": float(r.benchmark_roas) if r.benchmark_roas is not None else None,
            "frozen_at": r.frozen_at.isoformat() if r.frozen_at else None,
        })

    months = []
    for key in sorted(buckets, reverse=True):
        b = buckets[key]
        b["roas"] = b["revenue"] / b["spend"] if b["spend"] > 0 else None
        b["by_branch"] = [
            {"branch_name": n, "count": c}
            for n, c in sorted(b["by_branch"].items(), key=lambda kv: -kv[1])
        ]
        if month and key != month:
            b["ads"] = []
        months.append(b)

    return {
        "months": months,
        "total_wins": len(rows),
        # Distinct creatives — one ad can win in several months.
        "distinct_ads": len({(r.account_id, r.ad_name) for r in rows}),
        "scope_note": f'Only ads whose name contains "{CRTV_TOKEN}" are counted.',
    }
