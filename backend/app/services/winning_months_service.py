"""Monthly winning-creative awards — computed from ad_daily_metrics, then FROZEN.

Why this exists
---------------
The Creative Library verdict is dynamic: each combo's LIFETIME ROAS is compared
against the account's CURRENT blended ROAS. Move the benchmark and yesterday's
WIN becomes today's LOSE, so "how many winners did we ship in May?" has no
stable answer.

This module answers it. For every (account, calendar month) it looks at every
ad_name still running THAT month, but judges it on its CUMULATIVE history —
every day of spend since the ad's first appearance, through the end of that
month — against the account's LIFETIME (all-time-to-date) blended non-KOL
roas, same "current benchmark" the Library compares combos against, per
Mason: "hiện tại" means lifetime, not an isolated cohort. Splitting an ad's
clicks into calendar-month buckets meant most ads never individually
accumulated enough evidence to leave TEST, even after months of real spend —
1,500 clicks in June and 1,500 more in July never crossed MIN_TEST_CLICKS
under pure per-month accounting, despite the ad plainly having earned 3,000
clicks of evidence (comfortably over the 2,500 bar — see
creative_service.classify_verdict) by the end of July. So the ELIGIBILITY
check (clicks/bookings) and the ROAS judged against the benchmark are both
cumulative-to-date as of the month an ad first clears the bar — see
compute_month_verdicts for the exact mechanics. Per Mason (2026-08-10): "để
chỉ số phải tính cả nhiều tháng lại với nhau chứ, thì mới đúng được."

The decided ads get INSERTed into winning_ad_months. Rows are append-only:
re-running can award NEW verdicts to a past month, but never rewrites or
removes one that was already frozen — the roas / benchmark / bookings stored
on the row are the numbers as of the award, so a month's win_rate never
drifts later just because the lifetime benchmark (or a later month's data)
kept moving.

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

Caveat: LOSE only FREEZES for a CLOSED month (see freeze_winning_months) —
the account's current/most-recent synced month is still accumulating data,
and permanently locking in a LOSE it might climb out of before the month
ends would be wrong. But per Mason (2026-08-11): an ad that already crossed
the test threshold this month IS tested, frozen or not — so
list_winning_months blends a LIVE (unfrozen) LOSE count into the open
month's tested/win_rate for reporting, without writing anything to
WinningAdMonth. That number can move day to day as live LOSEs flip to WIN
and freeze there instead — see list_winning_months for the mechanics.

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
    """Decide every candidate STILL RUNNING this month, using its CUMULATIVE
    history through this month's end.

    `benchmark` is the bar every candidate is measured against — the
    account's CURRENT (lifetime-to-date) blended non-KOL ROAS, from
    compute_lifetime_benchmark.

    Two different things are cumulative here and it's worth being precise
    about which:

    1. Candidacy — WHICH ad_names are considered this month — is still
       month-scoped: an ad must have at least one row in [month_start,
       month_end] to be a candidate at all. An ad that stopped running two
       months ago isn't re-surfaced just because its old numbers would now
       clear the bar.
    2. The NUMBERS used to judge a candidate — clicks, bookings, spend,
       revenue, and therefore roas — are cumulative from the ad's own first
       day of history through the end of THIS month, not this month's
       isolated total. Per Mason (2026-08-10): splitting an ad's clicks into
       calendar-month buckets meant most ads never individually cleared
       MIN_TEST_CLICKS (2,500 — see creative_service.classify_verdict) even
       after months of real spend — 1,500 clicks in June and 1,500 more in
       July never left TEST under the old per-month accounting, even though
       the ad plainly earned 3,000 clicks of evidence by the end of July. So:
       an ad with 1,500 clicks in June (candidate, still TEST) and 1,500 more
       in July (candidate again, now cumulative 3,000 clicks) gets DECIDED in
       July, using July's cumulative roas (both months' revenue ÷ both
       months' spend) — not July's own isolated roas. This mirrors how
       `benchmark` already works: never an isolated cohort.

    `already_decided` is the set of ad_names that already have a frozen
    verdict from an earlier month for this account — they're skipped as
    candidates entirely (not counted as WIN, LOSE, or TEST) so an ad already
    judged doesn't get re-judged, and its cumulative total isn't diluted by
    months that happened after it already won or lost.

    Returns one dict per ad that crossed the test threshold this month
    (verdict WIN or LOSE — ads still in TEST are omitted).
    """
    already_decided = already_decided or set()
    start = month_start(month)
    end = month_end(start)

    # Candidacy: must actually be running THIS month.
    active_this_month = {
        r[0] for r in db.query(AdDailyMetric.ad_name)
        .filter(
            AdDailyMetric.account_id == account_id,
            AdDailyMetric.date >= start,
            AdDailyMetric.date <= end,
            AdDailyMetric.ad_name.isnot(None),
            ~AdDailyMetric.ad_name.ilike(_KOL_LIKE),
        )
        .distinct()
        .all()
    }
    active_this_month -= already_decided
    if not active_this_month:
        return []

    # Numbers: cumulative from the beginning of this ad_name's history
    # through the end of THIS month — no lower date bound.
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
            AdDailyMetric.date <= end,
            AdDailyMetric.ad_name.in_(active_this_month),
        )
        .group_by(AdDailyMetric.ad_name)
        .all()
    )
    if not rows:
        return []

    decided: list[dict] = []
    for r in rows:
        # r.ad_name is guaranteed in active_this_month (already_decided
        # already subtracted before the query ran).
        spend = float(r.spend or 0)
        revenue = float(r.revenue or 0)
        clicks = int(r.clicks or 0)
        conversions = int(r.conversions or 0)
        roas = revenue / spend if spend > 0 else 0.0
        verdict = classify_verdict(clicks, conversions, roas, benchmark)
        if verdict not in ("WIN", "LOSE"):
            continue  # still TEST — cumulative total carries into next month
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


def live_open_month_loses(
    db: Session,
    accounts: list[AdAccount],
    account_open_month: dict[str, date],
) -> dict[str, tuple[date, int]]:
    """``{account_id: (open_month, live_lose_count)}`` — the unfrozen LOSEs
    sitting in each account's still-open month, accounts with none omitted.

    freeze_winning_months deliberately never freezes a LOSE for the open month
    (an ad still spending could climb out of it before month end), so a read
    path that only counts frozen rows sees WINs and nothing else and reports
    100% for the current month no matter how many tested ads are actually
    losing. Every read path that publishes a win_rate has to fold this number
    in — list_winning_months for the "Winning by Month" tab, and
    routers/export.py's /export/winning-ads-monthly for HiD's "% Ads Win"
    KPI. It lives here, in one place, because the two disagreeing about the
    open month is exactly the bug this fixes.

    Nothing is persisted, and the number is intentionally volatile: a live
    LOSE today can flip to WIN and freeze there tomorrow. Callers apply their
    own month/year window and attribute the count to a branch themselves.
    """
    out: dict[str, tuple[date, int]] = {}
    for acc in accounts:
        open_m = account_open_month.get(acc.id)
        if open_m is None:
            continue
        already_decided = {
            r[0] for r in db.query(WinningAdMonth.ad_name)
            .filter(WinningAdMonth.account_id == acc.id).distinct().all()
        }
        benchmark = compute_lifetime_benchmark(db, acc.id)
        live_lose = sum(
            1 for d in compute_month_verdicts(db, acc.id, open_m, benchmark, already_decided)
            if d["verdict"] == "LOSE"
        )
        if live_lose:
            out[acc.id] = (open_m, live_lose)
    return out


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


class ManualVerdictError(ValueError):
    """Raised by award_manual_verdict for any rejection — bad verdict value,
    out-of-scope account/ad, already decided, or no data at all. The router
    catches this specifically so callers get a clear 4xx message instead of a
    generic 500."""


def award_manual_verdict(
    db: Session,
    account_id: str,
    ad_name: str,
    verdict: str,
    notes: str | None = None,
    month: date | None = None,
) -> WinningAdMonth:
    """Human override for an ad stuck in TEST that will never accumulate
    enough clicks/bookings on its own to get an automatic verdict.

    Per Mason (2026-08-11): "những cái ad cũ và chưa được vendict, tao muốn
    được tự đánh giá nó win hay lose được không" — old, low-volume ads sitting
    in TEST forever were the concrete reason the win-rate KPI's `tested` count
    stayed small even after MIN_TEST_CLICKS came down to 2,500 (see
    compute_month_verdicts). This is the escape hatch: skip the click/booking
    gate entirely and let a person decide.

    Still bound by every other rule this table enforces, because a manual row
    is a WinningAdMonth row like any other and freeze_winning_months can't
    tell the difference when it builds `decided_ad_names`:

    - `verdict` must be WIN or LOSE — never TEST, which just means "no row".
    - The account must not be in EXCLUDED_BRANCHES and `ad_name` must not be
      KOL-tagged — same scope as every automatic award, so a manual override
      can't smuggle an out-of-scope ad into the KPI.
    - The ad_name must not already have a row for this account (checked
      against ALL verdict_source values) — "decided once, ever" holds
      regardless of who or what decided it.
    - The ad must have at least one real ad_daily_metrics row — otherwise
      there's nothing to award and it's almost certainly a typo'd ad_name.

    `month` defaults to the account's most-recently-synced month (mirrors
    `last` in freeze_winning_months — deterministic from synced data, not
    wall-clock "today"). spend/revenue/clicks/conversions/roas are still
    computed CUMULATIVELY through that month's end, same convention as an
    automatic award, so the row stays meaningful/auditable even though the
    threshold check was skipped. `benchmark_roas` is recorded for context —
    it did NOT decide this verdict, a human did.

    Raises ManualVerdictError (a ValueError) on any rejection. Does not
    commit — caller owns the transaction, same convention as
    compute_month_verdicts/freeze_winning_months.
    """
    verdict = verdict.upper()
    if verdict not in ("WIN", "LOSE"):
        raise ManualVerdictError(f"verdict must be WIN or LOSE, got {verdict!r}")

    account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
    if not account:
        raise ManualVerdictError(f"no such account: {account_id}")
    if is_excluded_branch(account.account_name):
        raise ManualVerdictError(
            f"{account.account_name} is not covered by this KPI (EXCLUDED_BRANCHES)"
        )
    if is_kol(ad_name):
        raise ManualVerdictError(f'"{ad_name}" contains "KOL" — out of scope for this KPI')

    already = (
        db.query(WinningAdMonth)
        .filter(WinningAdMonth.account_id == account_id, WinningAdMonth.ad_name == ad_name)
        .first()
    )
    if already:
        raise ManualVerdictError(
            f'"{ad_name}" already has a {already.verdict} verdict for {already.month.isoformat()[:7]} '
            f"({already.verdict_source}) — an ad is judged once, ever"
        )

    if month is None:
        last_synced = (
            db.query(sf.max(AdDailyMetric.date))
            .filter(AdDailyMetric.account_id == account_id)
            .scalar()
        )
        if not last_synced:
            raise ManualVerdictError(
                f"{account.account_name} has no ad_daily_metrics at all — pass `month` explicitly"
            )
        month = month_start(last_synced)
    else:
        month = month_start(month)

    totals = (
        db.query(
            sf.sum(AdDailyMetric.spend), sf.sum(AdDailyMetric.revenue),
            sf.sum(AdDailyMetric.impressions), sf.sum(AdDailyMetric.clicks),
            sf.sum(AdDailyMetric.conversions),
        )
        .filter(
            AdDailyMetric.account_id == account_id,
            AdDailyMetric.ad_name == ad_name,
            AdDailyMetric.date <= month_end(month),
        )
        .first()
    )
    spend = float(totals[0] or 0)
    if spend == 0 and not (totals[1] or totals[3] or totals[4]):
        raise ManualVerdictError(
            f'"{ad_name}" has no ad_daily_metrics rows for {account.account_name} through '
            f"{month.isoformat()[:7]} — nothing to award"
        )
    revenue = float(totals[1] or 0)
    roas = revenue / spend if spend > 0 else 0.0
    benchmark = compute_lifetime_benchmark(db, account_id)

    combo = (
        db.query(AdCombo)
        .filter(AdCombo.branch_id == account_id, AdCombo.ad_name == ad_name)
        .first()
    )
    row = WinningAdMonth(
        account_id=account_id,
        month=month,
        ad_name=ad_name,
        verdict=verdict,
        combo_id=combo.combo_id if combo else None,
        target_audience=combo.target_audience if combo else None,
        country=combo.country if combo else None,
        spend=spend,
        revenue=revenue,
        impressions=int(totals[2] or 0),
        clicks=int(totals[3] or 0),
        conversions=int(totals[4] or 0),
        roas=roas,
        benchmark_roas=benchmark,
        verdict_source="manual",
        verdict_notes=notes,
        frozen_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    logger.warning(
        "[winning-months] MANUAL %s awarded to %s / %s (%s), roas=%.2f vs benchmark=%.2f — %s",
        verdict, account.account_name, ad_name, month.isoformat()[:7], roas, benchmark, notes or "no notes",
    )
    return row


def describe_data_window(db: Session, accounts: list[AdAccount] | None = None) -> list[dict]:
    """Per account, the ad_daily_metrics window currently on disk.

    The pre-flight check for a rebuild. /ad-performance/sync runs in a daemon
    thread and returns immediately, so there is no signal for when a backfill
    has finished; rebuilding early silently re-creates the skew the rebuild
    exists to fix (see rebuild_winning_months). This makes "how far back does
    the data actually go" answerable in one cheap call, per account so one
    lagging branch can't hide behind the others.
    """
    accounts = accounts if accounts is not None else eligible_accounts(db)
    out = []
    for acc in accounts:
        # Distinct months counted in Python, not via date_trunc — that's
        # Postgres-only and the test suite runs on SQLite.
        dates = [
            d for (d,) in db.query(AdDailyMetric.date)
            .filter(AdDailyMetric.account_id == acc.id)
            .distinct().all()
            if d
        ]
        out.append({
            "account_name": acc.account_name,
            "from": min(dates).isoformat() if dates else None,
            "to": max(dates).isoformat() if dates else None,
            "months": len({(d.year, d.month) for d in dates}),
        })
    return sorted(out, key=lambda e: (e["from"] or "9999", e["account_name"] or ""))


def rebuild_winning_months(db: Session, account_ids: list[str] | None = None) -> dict:
    """DESTRUCTIVE repair: wipe every frozen verdict and re-freeze from scratch.

    WHY THIS EXISTS. The "an ad is decided once, ever" rule keys off whether a
    row already exists, NOT off calendar order — see freeze_winning_months,
    which loads `decided_ad_names` for the whole account before walking the
    months. That is correct while history only ever grows forward, but it
    breaks when a backfill adds EARLIER months than the ones already frozen:
    an ad that ran Jan→Aug and was first decided in May stays decided in May,
    and never gets the January row where it actually first crossed the test
    threshold. The backfilled months would then contain only the ads that
    stopped running before the previously-earliest month — a small, biased
    subset that reads as a real win rate but isn't one.

    So after widening the ad_daily_metrics window (DEFAULT_SINCE moved from
    2026-05-01 to 2026-01-01 on 2026-08-08), the table has to be rebuilt for
    the new months to mean anything.

    THE TRADE-OFF, EXPLICITLY. Rebuilding re-stamps every row with TODAY's
    lifetime benchmark, so verdicts frozen earlier can come out different —
    which is exactly what freezing normally prevents. That is acceptable only
    as a deliberate, one-off repair after the underlying data changed, never
    on a schedule. It also makes every month comparable for once, since all of
    them end up judged against the same bar. This is why it is a separate
    function behind an explicit confirm rather than a flag on the daily pass.

    Scope note: EXCLUDED_BRANCHES accounts are not re-created, and their
    pre-existing rows are deleted, so a rebuild also cleans them out for good.
    """
    accounts = [
        a for a in eligible_accounts(db)
        if account_ids is None or a.id in set(account_ids or [])
    ]
    keep_ids = {a.id for a in accounts}

    q = db.query(WinningAdMonth)
    if account_ids is not None:
        # Also drop excluded-branch rows that the caller asked about, so a
        # scoped rebuild still clears them rather than stranding them.
        q = q.filter(WinningAdMonth.account_id.in_(set(account_ids or ["__no_match__"])))
    deleted = q.delete(synchronize_session=False)
    db.flush()

    summary = freeze_winning_months(db, account_ids=sorted(keep_ids) if keep_ids else [])
    summary["deleted"] = deleted
    # The window the rebuild actually SAW. A rebuild run while a backfill is
    # still writing silently produces the very skew it exists to fix — the
    # missing months just aren't candidates yet, and the once-ever rule then
    # locks their ads into whatever later month did have data. Reporting the
    # range makes that visible in the response instead of weeks later on the
    # chart. Per account, so one lagging branch can't hide behind the others.
    summary["data_seen"] = describe_data_window(db, accounts)
    logger.warning(
        "[winning-months] REBUILD deleted %d frozen rows, re-froze %d wins / %d losses; data_seen=%s",
        deleted, summary["awarded"], summary["lost"], summary["data_seen"],
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

    LIVE LOSE PREVIEW. freeze_winning_months never freezes a LOSE for the
    open month (an ad still spending could climb out of it before month
    end), so without help every open-month bucket would show 100% win_rate
    no matter how many ads had already crossed the test threshold and were
    actually sitting at LOSE right now. Per Mason (2026-08-11): once an ad
    clears MIN_TEST_CLICKS/bookings and scores below benchmark it IS tested
    — that should count for tracking purposes even though nothing gets
    written to WinningAdMonth yet. So for every account whose most-recently-
    synced month is the bucket being built, this re-runs
    compute_month_verdicts live (not persisted) and folds any LOSEs it finds
    straight into that bucket's `lose_count`/`tested`/`win_rate` — this can
    create a bucket that has zero frozen rows at all (open month, no WIN yet,
    but some ads already at live LOSE). This number is intentionally
    volatile: a live LOSE today can flip to WIN and freeze there tomorrow,
    which is the whole reason it isn't frozen now.

    `in_progress` flags a calendar month bucket that still contains at least
    one account for which this is the most-recently-synced month — i.e. a
    bucket that may still be carrying a live LOSE preview per above, or gain
    new WIN/LOSE rows as more ads clear the test threshold before the month
    closes. This mirrors the freeze algorithm exactly rather than guessing
    from wall-clock "today," which would be wrong for a branch whose sync
    has silently stalled (its "open" month never closes until fresh data
    arrives, no matter how much wall-clock time passes).

    `new_ads` is a reference-only count of distinct ad_names that FIRST
    appeared in ad_daily_metrics that month, same scope as the KPI (non-KOL,
    EXCLUDED_BRANCHES out). It never feeds win_rate or any other number here
    — just display context for whether a month was quiet or busy on output.
    A month only gets a bucket at all if it has at least one WIN/LOSE row (or
    a live LOSE preview, see above) — a month with new_ads > 0 but nothing
    tested/live-tested yet won't appear in `months`.
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

    # Reference-only stat: how many NEW ad_names first appeared each month,
    # scoped the same way as the KPI (non-KOL, EXCLUDED_BRANCHES out) so the
    # number sits in the same universe as win/tested. Purely informational —
    # doesn't feed win_rate or any other calculation, just display context for
    # "was this a quiet month for output or a busy one."
    new_ads_q = db.query(
        AdDailyMetric.account_id,
        AdDailyMetric.ad_name,
        sf.min(AdDailyMetric.date).label("first_date"),
    ).filter(
        AdDailyMetric.ad_name.isnot(None),
        ~AdDailyMetric.ad_name.ilike(_KOL_LIKE),
    )
    if branch_id:
        new_ads_q = new_ads_q.filter(AdDailyMetric.account_id == branch_id)
    elif account_ids is not None:
        new_ads_q = new_ads_q.filter(AdDailyMetric.account_id.in_(account_ids or ["__no_match__"]))
    if excluded:
        new_ads_q = new_ads_q.filter(AdDailyMetric.account_id.notin_(excluded))
    new_ads_by_month: dict[str, int] = {}
    for _acc_id, _ad_name, first_date in new_ads_q.group_by(
        AdDailyMetric.account_id, AdDailyMetric.ad_name
    ).all():
        key = first_date.isoformat()[:7]
        new_ads_by_month[key] = new_ads_by_month.get(key, 0) + 1

    acc_names = {
        a.id: a.account_name
        for a in db.query(AdAccount.id, AdAccount.account_name).all()
    }

    # Every account within scope (not just ones with a frozen row already) —
    # needed below both for `in_progress` and for the live LOSE preview,
    # which can create a bucket with no frozen rows at all.
    accounts_in_scope = eligible_accounts(db)
    if branch_id:
        accounts_in_scope = [a for a in accounts_in_scope if a.id == branch_id]
    elif account_ids is not None:
        wanted = set(account_ids or [])
        accounts_in_scope = [a for a in accounts_in_scope if a.id in wanted]

    account_open_month: dict[str, date] = {
        r[0]: month_start(r[1])
        for r in db.query(AdDailyMetric.account_id, sf.max(AdDailyMetric.date))
        .filter(AdDailyMetric.account_id.in_([a.id for a in accounts_in_scope] or ["__no_match__"]))
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
                "verdict_source": r.verdict_source,
                "verdict_notes": r.verdict_notes,
            })
        else:
            b["lose_count"] += 1

    # Live (unfrozen) LOSE preview — see the "LIVE LOSE PREVIEW" note in this
    # function's docstring. For every account whose most-recently-synced
    # month is still open, re-run compute_month_verdicts (not persisted) and
    # fold any LOSEs straight into that bucket so tested/win_rate reflect
    # today's real state instead of only counting the WINs that already
    # froze. Can create a bucket that has no frozen rows at all.
    live_lose_total = 0
    for _acc_id, (open_m, live_lose) in live_open_month_loses(
        db, accounts_in_scope, account_open_month
    ).items():
        if year is not None and open_m.year != year:
            continue
        key = open_m.isoformat()[:7]
        b = buckets.setdefault(key, {
            "month": key, "count": 0, "lose_count": 0, "spend": 0.0, "revenue": 0.0,
            "conversions": 0, "by_branch": {}, "ads": [],
        })
        b["lose_count"] += live_lose
        in_progress_keys.add(key)
        live_lose_total += live_lose

    months = []
    for key in sorted(buckets, reverse=True):
        b = buckets[key]
        b["roas"] = b["revenue"] / b["spend"] if b["spend"] > 0 else None
        b["tested"] = b["count"] + b["lose_count"]
        b["win_rate"] = (b["count"] / b["tested"]) if b["tested"] > 0 else None
        b["in_progress"] = key in in_progress_keys
        b["new_ads"] = new_ads_by_month.get(key, 0)
        b["by_branch"] = [
            {"branch_name": n, "count": c}
            for n, c in sorted(b["by_branch"].items(), key=lambda kv: -kv[1])
        ]
        if month and key != month:
            b["ads"] = []
        months.append(b)

    win_rows = [r for r in rows if r.verdict == "WIN"]
    # live_lose_total folds the open month's unfrozen LOSEs into the org-wide
    # totals too, same reasoning as the per-month buckets above.
    lose_count = len(rows) - len(win_rows) + live_lose_total
    tested_count = len(rows) + live_lose_total

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
            "decided in an earlier month is never re-tested. The open "
            "month's LOSE count is a live (unfrozen) preview — see in_progress."
        ),
    }
