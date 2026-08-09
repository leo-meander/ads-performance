"""Monthly winning-creative awards — computed from ad_daily_metrics, then FROZEN.

Why this exists
---------------
The Creative Library verdict is dynamic: each combo's LIFETIME ROAS is compared
against the account's CURRENT blended ROAS. Move the benchmark and yesterday's
WIN becomes today's LOSE, so "how many winners did we ship in May?" has no
stable answer.

This module answers it. For every (account, calendar month) it aggregates
that month's ad_daily_metrics per ad_name, compares each candidate's MONTHLY
roas against the account's LIFETIME (all-time-to-date) blended non-KOL roas —
same "current benchmark" the Library compares combos against, per Mason:
"hiện tại" means lifetime, not that month's isolated cohort — applies the
same WIN/LOSE/TEST rule the Library uses, and INSERTs the decided ads into
winning_ad_months. Rows are append-only: re-running can award NEW verdicts to
a past month, but never rewrites or removes one that was already frozen —
the roas / benchmark / bookings stored on the row are the numbers as of the
award, so a month's win_rate never drifts later just because the lifetime
benchmark kept moving.

Note the split: the BENCHMARK is lifetime, but the REPORTING window is
year-to-date — list_winning_months buckets only the selected calendar year,
so the headline "% win rate" resets each January without changing how any
individual verdict was decided.

Two rules that make the win-rate % meaningful instead of misleading:

1. Only ads that cleared the TEST threshold that month (enough clicks or
   bookings — see classify_verdict) are counted at all. An ad still in TEST
   is not a candidate yet and isn't counted in either the numerator or the
   denominator.
2. Once an ad_name has a decided verdict (WIN or LOSE) for an account — in
   ANY month — it is never re-evaluated in a later month. Without this, a
   perpetually-running winning ad would re-win every month forever and
   inflate both the win count and the tested count month after month for
   what is really the same one decision.

win_rate for a month = WIN count / (WIN count + LOSE count) among ads
decided that month — i.e. wins divided by everything that crossed the test
threshold, per Mason's spec.

Caveat: LOSE only freezes for a CLOSED month (see freeze_winning_months) —
the account's current/most-recent synced month is still accumulating data,
so its win_rate looks artificially high (or is None) until the month
closes and its stragglers get their final LOSE.

Scope: every ad EXCEPT ones whose name contains "KOL" (paid amplification of
KOL-sourced content — testing someone else's creative, not the design team's).
Everything else — CRTV-tagged or not — counts. The filter applies to
candidates AND to the lifetime benchmark, so KOL traffic never moves the bar.
Per Mason: previously only "CRTV"-named ads counted; now it's "all ads, minus
KOL."

Branch scope: EXCLUDED_BRANCHES (currently Bread, the restaurant) is out of
this KPI entirely — no new rows are frozen for it and already-frozen ones are
hidden from every read path.
"""
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func as sf
from sqlalchemy.orm import Session

from app.core.branches import resolve_branch_for_account_name
from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_daily_metric import AdDailyMetric
from app.models.winning_ad_month import WinningAdMonth
from app.services.creative_service import classify_verdict

logger = logging.getLogger(__name__)

# Paid amplification of KOL content — the one category excluded from "all
# ads." Case-insensitive so "kol"/"Kol" also match.
KOL_TOKEN = "KOL"
_KOL_LIKE = f"%{KOL_TOKEN}%"

# Branches this KPI does not cover. Bread (Bread Espresso) is the restaurant,
# not a hotel — its ads aren't part of the design team's creative-test cycle,
# so counting them would distort the win rate. Canonical BRANCH_ACCOUNT_MAP
# keys; matched via resolve_branch_for_account_name so the account-name
# patterns stay in one place.
EXCLUDED_BRANCHES = {"Bread"}


def is_kol(ad_name: str | None) -> bool:
    return bool(ad_name) and KOL_TOKEN in ad_name.upper()


def is_excluded_branch(account_name: str | None) -> bool:
    return resolve_branch_for_account_name(account_name or "") in EXCLUDED_BRANCHES


def excluded_account_ids(db: Session) -> set[str]:
    """Every account id belonging to an EXCLUDED_BRANCHES branch.

    Used to keep already-frozen rows for those branches out of the read paths
    too — the table is append-only, so an award frozen before a branch was
    excluded can only be hidden, never deleted.
    """
    return {
        a.id
        for a in db.query(AdAccount.id, AdAccount.account_name).all()
        if is_excluded_branch(a.account_name)
    }


def eligible_accounts(db: Session) -> list[AdAccount]:
    """Active Meta accounts this KPI covers, minus EXCLUDED_BRANCHES."""
    accounts = (
        db.query(AdAccount)
        .filter(AdAccount.platform == "meta", AdAccount.is_active.is_(True))
        .all()
    )
    return [a for a in accounts if not is_excluded_branch(a.account_name)]


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


def compute_lifetime_benchmark(db: Session, account_id: str) -> float:
    """The account's all-time blended (non-KOL) ROAS — the "current" benchmark.

    Per Mason: "hiện tại" (current) means lifetime-to-date, not that one
    month's isolated cohort and not year-to-date either. This mirrors the
    Creative Library's own bar — "each combo's LIFETIME ROAS vs the account's
    CURRENT blended ROAS" — just excluding KOL ads, same as everywhere else in
    this module, so KOL traffic never moves it. No date filter: every day ever
    synced for this account counts.

    The year-to-date scoping added alongside this lives in
    list_winning_months, on the REPORTING side only — it never touches how a
    verdict is decided.
    """
    total_spend, total_revenue = (
        db.query(sf.sum(AdDailyMetric.spend), sf.sum(AdDailyMetric.revenue))
        .filter(
            AdDailyMetric.account_id == account_id,
            AdDailyMetric.ad_name.isnot(None),
            ~AdDailyMetric.ad_name.ilike(_KOL_LIKE),
        )
        .first()
    )
    total_spend = float(total_spend or 0)
    total_revenue = float(total_revenue or 0)
    return total_revenue / total_spend if total_spend > 0 else 0.0


def compute_month_verdicts(
    db: Session,
    account_id: str,
    month: date,
    benchmark: float,
    already_decided: set[str] | None = None,
) -> list[dict]:
    """Aggregate one account-month and decide every candidate that qualifies.

    `benchmark` is the bar every candidate is measured against — the
    account's CURRENT (lifetime-to-date) blended non-KOL ROAS, from
    compute_lifetime_benchmark, NOT recomputed from this month's cohort
    alone. Only the candidate's own roas is month-scoped: that's the whole
    point of "winning BY MONTH" — did this ad's performance THIS MONTH clear
    the account's current bar.

    `already_decided` is the set of ad_names that already have a frozen
    verdict from an earlier month for this account — they're skipped as
    candidates entirely (not counted as WIN, LOSE, or TEST) so an ad already
    judged doesn't get re-judged.

    Returns one dict per ad that crossed the test threshold this month
    (verdict WIN or LOSE — ads still in TEST are omitted).
    """
    already_decided = already_decided or set()
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
            ~AdDailyMetric.ad_name.ilike(_KOL_LIKE),
        )
        .group_by(AdDailyMetric.ad_name)
        .all()
    )
    if not rows:
        return []

    decided: list[dict] = []
    for r in rows:
        if r.ad_name in already_decided:
            continue
        spend = float(r.spend or 0)
        revenue = float(r.revenue or 0)
        clicks = int(r.clicks or 0)
        conversions = int(r.conversions or 0)
        roas = revenue / spend if spend > 0 else 0.0
        verdict = classify_verdict(clicks, conversions, roas, benchmark)
        if verdict not in ("WIN", "LOSE"):
            continue  # still TEST — insufficient data, stays eligible next month
        decided.append({
            "ad_name": r.ad_name,
            "verdict": verdict,
            "spend": spend,
            "revenue": revenue,
            "impressions": int(r.impressions or 0),
            "clicks": clicks,
            "conversions": conversions,
            "roas": roas,
        })
    return decided


def freeze_winning_months(
    db: Session, account_ids: list[str] | None = None, since: date | None = None
) -> dict:
    """Decide (and permanently freeze) monthly verdicts across every Meta account.

    Idempotent and append-only: an (account, month, ad_name) that already has a
    row is left untouched — its frozen roas/benchmark/verdict stay as first
    written. Months are processed oldest → newest per account so that an ad
    decided in an earlier month is excluded from candidacy before a later
    month is computed — see compute_month_verdicts. Commits once at the end.

    The benchmark is computed ONCE per account per call — the account's
    current (lifetime-to-date) blended non-KOL ROAS, via
    compute_lifetime_benchmark — and reused as the bar for every month
    processed this run, rather than recomputed from each month's own isolated
    cohort.

    LOSE verdicts are only frozen for a CLOSED month — one strictly before
    the account's most-recent synced month. The most-recent month is still
    "open": data keeps arriving for it, so an ad sitting at LOSE today could
    still climb to WIN before the month ends. Freezing that LOSE now would
    permanently lock it out (rows are insert-only, and the unique
    (account, month, ad_name) constraint means it could never be replaced
    with a WIN later). WIN verdicts for the open month freeze immediately,
    same as before this change — only the LOSE side waits for the month to
    close. Once a later month's data shows up, this month is closed on the
    next freeze pass and its still-undecided ads get their final verdict.

    Accounts belonging to an EXCLUDED_BRANCHES branch are skipped entirely —
    no new rows are ever written for them.
    """
    accounts = [
        a for a in eligible_accounts(db)
        if account_ids is None or a.id in set(account_ids or [])
    ]

    now = datetime.now(timezone.utc)
    summary = {"accounts": 0, "months": 0, "awarded": 0, "lost": 0, "already_frozen": 0}

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

        # An ad already decided (WIN or LOSE) in ANY past month — including
        # months before `first`/`since` — is never a candidate again.
        decided_ad_names = {
            r[0]
            for r in db.query(WinningAdMonth.ad_name)
            .filter(WinningAdMonth.account_id == acc.id)
            .distinct()
            .all()
        }

        # One "current" bar for every month processed this run — the
        # account's lifetime-to-date blended non-KOL ROAS, not a per-month
        # recomputation. See compute_lifetime_benchmark.
        benchmark = compute_lifetime_benchmark(db, acc.id)

        open_month = month_start(last)  # data can still change this month's outcome

        for m in months_between(first, last):
            decided = compute_month_verdicts(db, acc.id, m, benchmark, decided_ad_names)
            if m == open_month:
                # Don't lock in a LOSE the month could still climb out of.
                decided = [d for d in decided if d["verdict"] == "WIN"]
            if not decided:
                continue
            summary["months"] += 1

            existing = {
                r[0]
                for r in db.query(WinningAdMonth.ad_name)
                .filter(WinningAdMonth.account_id == acc.id, WinningAdMonth.month == m)
                .all()
            }
            for d in decided:
                if d["ad_name"] in existing:
                    summary["already_frozen"] += 1
                    continue
                combo = combo_map.get(d["ad_name"])
                db.add(WinningAdMonth(
                    account_id=acc.id,
                    month=m,
                    ad_name=d["ad_name"],
                    verdict=d["verdict"],
                    combo_id=combo.combo_id if combo else None,
                    target_audience=combo.target_audience if combo else None,
                    country=combo.country if combo else None,
                    spend=d["spend"],
                    revenue=d["revenue"],
                    impressions=d["impressions"],
                    clicks=d["clicks"],
                    conversions=d["conversions"],
                    roas=d["roas"],
                    benchmark_roas=benchmark,
                    frozen_at=now,
                ))
                decided_ad_names.add(d["ad_name"])
                if d["verdict"] == "WIN":
                    summary["awarded"] += 1
                else:
                    summary["lost"] += 1

    db.commit()
    logger.info(
        "[winning-months] %d newly awarded, %d newly lost, %d already frozen across %d accounts",
        summary["awarded"], summary["lost"], summary["already_frozen"], summary["accounts"],
    )
    return summary


def diagnose_winning_by_month(db: Session) -> dict:
    """Explain an empty Winning-by-Month tab: is ad_daily_metrics unpopulated,
    or is it populated but every synced ad is KOL-tagged (the one excluded
    category)?

    freeze_winning_months() silently skips an account with zero ad_daily_metrics
    rows (bounds[0] is None) and silently skips a month with zero eligible
    (non-KOL) rows (compute_month_verdicts returns no decided ads) — neither is
    an error, so there's nothing in the logs to point at. This makes both
    conditions visible at once, plus a naming sample for the all-KOL case so
    it's obvious rather than guessed at. Read-only.

    EXCLUDED_BRANCHES accounts are left out — they're absent from the tab by
    design, not by a fixable data problem, so listing them here would be a
    false lead.
    """
    accounts = eligible_accounts(db)

    per_account = []
    for acc in accounts:
        bounds = (
            db.query(sf.min(AdDailyMetric.date), sf.max(AdDailyMetric.date), sf.count())
            .filter(AdDailyMetric.account_id == acc.id)
            .first()
        )
        row_count = bounds[2] or 0
        eligible_count = (
            db.query(sf.count(sf.distinct(AdDailyMetric.ad_name)))
            .filter(AdDailyMetric.account_id == acc.id, ~AdDailyMetric.ad_name.ilike(_KOL_LIKE))
            .scalar()
        ) or 0

        entry = {
            "account_name": acc.account_name,
            "ad_daily_metrics_rows": row_count,
            "date_range": (
                f"{bounds[0].isoformat()} to {bounds[1].isoformat()}" if bounds[0] else None
            ),
            "distinct_eligible_ad_names": eligible_count,
        }
        if row_count and not eligible_count:
            # Populated but every ad is KOL-tagged — show a sample instead of
            # leaving Mason to guess.
            sample = (
                db.query(AdDailyMetric.ad_name)
                .filter(AdDailyMetric.account_id == acc.id, AdDailyMetric.ad_name.isnot(None))
                .distinct()
                .limit(10)
                .all()
            )
            entry["sample_ad_names"] = [s[0] for s in sample]
        per_account.append(entry)

    never_synced = [e["account_name"] for e in per_account if e["ad_daily_metrics_rows"] == 0]
    synced_all_kol = [
        e["account_name"] for e in per_account
        if e["ad_daily_metrics_rows"] > 0 and e["distinct_eligible_ad_names"] == 0
    ]

    frozen_awards = (
        db.query(sf.count()).select_from(WinningAdMonth)
        .filter(WinningAdMonth.verdict == "WIN").scalar()
    ) or 0

    return {
        "frozen_awards_so_far": frozen_awards,
        "accounts_never_synced_daily_metrics": never_synced,
        "accounts_synced_but_all_kol": synced_all_kol,
        "diagnosis": (
            "ad_daily_metrics is never populated by cron — only by the manual "
            "'Sync from Meta' button on the ad-performance page "
            "(POST /api/ad-performance/sync-daily). If accounts_never_synced_daily_metrics "
            "is non-empty, that's why: freeze_winning_months silently skips an "
            "account with zero rows. If accounts_synced_but_all_kol is "
            "non-empty instead, daily metrics ARE flowing but every ad name in "
            "that account contains \"KOL\" — check sample_ad_names below."
        ),
        "accounts": per_account,
    }


def list_kol_ads(db: Session, account_name_filter: str | None = None, limit: int = 200) -> dict:
    """Ads currently spending that ARE KOL-tagged — the one category excluded
    from Winning by Month, by name alone. Read-only.

    Aggregates ad_daily_metrics per (account, ad_name) across all synced
    history (no month boundary — this isn't a verdict decision, just "what's
    out there"), ranked by spend so the highest-impact exclusions surface
    first.

    `account_name_filter` is an ILIKE substring match (e.g. "Oani" or "1948"),
    same convention as diagnose_orphan_combos. EXCLUDED_BRANCHES accounts are
    left out — their ads are out of scope regardless of the KOL naming.
    """
    accounts = eligible_accounts(db)
    if account_name_filter:
        needle = account_name_filter.lower()
        accounts = [a for a in accounts if needle in (a.account_name or "").lower()]

    out_ads = []
    for acc in accounts:
        rows = (
            db.query(
                AdDailyMetric.ad_name.label("ad_name"),
                sf.sum(AdDailyMetric.spend).label("spend"),
                sf.sum(AdDailyMetric.revenue).label("revenue"),
                sf.sum(AdDailyMetric.conversions).label("conversions"),
                sf.max(AdDailyMetric.date).label("last_seen"),
            )
            .filter(
                AdDailyMetric.account_id == acc.id,
                AdDailyMetric.ad_name.isnot(None),
                AdDailyMetric.ad_name.ilike(_KOL_LIKE),
            )
            .group_by(AdDailyMetric.ad_name)
            .all()
        )
        for r in rows:
            spend = float(r.spend or 0)
            revenue = float(r.revenue or 0)
            out_ads.append({
                "account_name": acc.account_name,
                "ad_name": r.ad_name,
                "spend": spend,
                "revenue": revenue,
                "roas": (revenue / spend) if spend > 0 else None,
                "conversions": int(r.conversions or 0),
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            })

    out_ads.sort(key=lambda a: -a["spend"])
    return {
        "count": len(out_ads),
        "ads": out_ads[:limit],
        "note": (
            'Every ad here is excluded from Winning by Month because its name '
            'contains "KOL" (case-insensitive, any position) — paid '
            "amplification of KOL-sourced content, not the design team's own "
            "creative. Everything else counts, CRTV-tagged or not."
        ),
    }


def list_winning_months(
    db: Session,
    account_ids: list[str] | None = None,
    branch_id: str | None = None,
    month: str | None = None,
    year: int | None = None,
) -> dict:
    """Frozen verdicts grouped by month, newest month first.

    `account_ids=None` means "no scoping" (admin). `month` (YYYY-MM) narrows
    the ad list to one month; the per-month counts always cover every month
    within scope so the trend never collapses to a single bar. `year`
    restricts that scope to one calendar year — the router defaults this to
    the current year so the page reads as a YTD report ("% win rate" resets
    every January) — pass `year=None` explicitly for the untruncated,
    all-time view.

    Every row (WIN or LOSE) counts toward `tested` and `win_rate`; only WIN
    rows populate `count`, the `ads` detail list, and the win-only totals —
    those keep meaning "winning ads," same as before this table also started
    recording LOSEs. `win_rate` = WIN / (WIN + LOSE) among ads that crossed
    the test threshold that month, per Mason's spec — an ad still in TEST
    (insufficient clicks/bookings) never has a row here at all, so it's
    already excluded from both sides of the ratio.

    `in_progress` flags a calendar month bucket that still contains at least
    one account for which this is the most-recently-synced month —
    freeze_winning_months only freezes LOSE once a month is CLOSED for that
    account (see its docstring), so such a bucket's win_rate is provisional
    (usually inflated, since its stragglers haven't taken their final LOSE
    yet). This mirrors the freeze algorithm exactly rather than guessing
    from wall-clock "today," which would be wrong for a branch whose sync
    has silently stalled (its "open" month never closes until fresh data
    arrives, no matter how much wall-clock time passes).
    """
    q = db.query(WinningAdMonth)
    if branch_id:
        q = q.filter(WinningAdMonth.account_id == branch_id)
    elif account_ids is not None:
        q = q.filter(WinningAdMonth.account_id.in_(account_ids or ["__no_match__"]))
    # Rows are append-only, so awards frozen for a branch BEFORE it was
    # excluded still exist — hide them here rather than leaving them to skew
    # the totals.
    excluded = excluded_account_ids(db)
    if excluded:
        q = q.filter(WinningAdMonth.account_id.notin_(excluded))
    if year is not None:
        q = q.filter(
            WinningAdMonth.month >= date(year, 1, 1),
            WinningAdMonth.month <= date(year, 12, 31),
        )
    rows = q.order_by(WinningAdMonth.month.desc(), WinningAdMonth.roas.desc().nullslast()).all()

    acc_names = {
        a.id: a.account_name
        for a in db.query(AdAccount.id, AdAccount.account_name).all()
    }

    account_open_month: dict[str, date] = {}
    if rows:
        involved = {r.account_id for r in rows}
        account_open_month = {
            r[0]: month_start(r[1])
            for r in db.query(AdDailyMetric.account_id, sf.max(AdDailyMetric.date))
            .filter(AdDailyMetric.account_id.in_(involved))
            .group_by(AdDailyMetric.account_id)
            .all()
            if r[1] is not None
        }

    buckets: dict[str, dict] = {}
    in_progress_keys: set[str] = set()
    for r in rows:
        key = r.month.isoformat()[:7]
        b = buckets.setdefault(key, {
            "month": key, "count": 0, "lose_count": 0, "spend": 0.0, "revenue": 0.0,
            "conversions": 0, "by_branch": {}, "ads": [],
        })
        if account_open_month.get(r.account_id) == r.month:
            in_progress_keys.add(key)
        is_win = r.verdict == "WIN"
        if is_win:
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
        else:
            b["lose_count"] += 1

    months = []
    for key in sorted(buckets, reverse=True):
        b = buckets[key]
        b["roas"] = b["revenue"] / b["spend"] if b["spend"] > 0 else None
        b["tested"] = b["count"] + b["lose_count"]
        b["win_rate"] = (b["count"] / b["tested"]) if b["tested"] > 0 else None
        b["in_progress"] = key in in_progress_keys
        b["by_branch"] = [
            {"branch_name": n, "count": c}
            for n, c in sorted(b["by_branch"].items(), key=lambda kv: -kv[1])
        ]
        if month and key != month:
            b["ads"] = []
        months.append(b)

    win_rows = [r for r in rows if r.verdict == "WIN"]
    lose_count = len(rows) - len(win_rows)
    tested_count = len(rows)

    return {
        "months": months,
        "total_wins": len(win_rows),
        "total_lost": lose_count,
        "total_tested": tested_count,
        "overall_win_rate": (len(win_rows) / tested_count) if tested_count > 0 else None,
        # Distinct creatives — one ad can only win once now (see module docstring).
        "distinct_ads": len({(r.account_id, r.ad_name) for r in win_rows}),
        "year": year,
        "scope_note": (
            f'All ads count except ones whose name contains "{KOL_TOKEN}". '
            f"Branches not covered: {', '.join(sorted(EXCLUDED_BRANCHES))}. "
            "win_rate = WIN / (WIN + LOSE) among ads that crossed the test "
            "threshold that month, within the selected year; an ad already "
            "decided in an earlier month is never re-tested."
        ),
    }
