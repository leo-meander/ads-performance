"""Landing Page service: CRUD, version management, approval lifecycle, metrics rollup.

Design notes (see CLAUDE.md):
- Versions are INSERT-only. Publishing a version updates landing_pages.current_version_id.
- All-approve rule: ALL reviewers must approve for status=APPROVED. ANY reject = REJECTED.
- Creator-only publish: only the submitter can flip APPROVED → PUBLISHED.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.ad import Ad
from app.models.account import AdAccount
from app.models.campaign import Campaign
from app.models.currency_rate import CurrencyRate
from app.models.landing_page import (
    LandingPage,
    SOURCE_EXTERNAL,
    SOURCE_MANAGED,
    STATUS_APPROVED,
    STATUS_ARCHIVED,
    STATUS_DISCOVERED,
    STATUS_DRAFT,
    STATUS_PENDING_APPROVAL,
    STATUS_PUBLISHED,
    STATUS_REJECTED,
)
from app.models.landing_page_ad_link import LandingPageAdLink
from app.models.landing_page_approval import (
    APPROVAL_APPROVED,
    APPROVAL_CANCELLED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    LandingPageApproval,
    LandingPageApprovalReviewer,
    REVIEWER_APPROVED,
    REVIEWER_PENDING,
    REVIEWER_REJECTED,
)
from app.models.landing_page_clarity import LandingPageClaritySnapshot
from app.models.landing_page_ga4 import LandingPageGA4Snapshot
from app.models.landing_page_version import LandingPageVersion
from app.models.metrics import MetricsCache
from app.services.landing_page_url_normalizer import (
    UTM_KEYS,
    infer_branch_from_host,
    normalize_url,
)


# ---------------------------------------------------------------------------
# Page lookup + upsert (used by importer + manual create)
# ---------------------------------------------------------------------------


def get_or_create_external_page(
    db: Session,
    *,
    raw_url: str,
    title_fallback: str | None = None,
    branch_id: str | None = None,
) -> LandingPage | None:
    """Upsert landing_pages row for an external (ad-discovered) URL.

    Match by (domain, slug). Creates a DISCOVERED/external row on first sight.
    """
    n = normalize_url(raw_url)
    if n is None:
        return None

    page = (
        db.query(LandingPage)
        .filter(LandingPage.domain == n.host, LandingPage.slug == n.slug)
        .one_or_none()
    )
    if page is not None:
        return page

    # Best-effort branch inference via subdomain
    if branch_id is None:
        branch_name = infer_branch_from_host(n.host)
        if branch_name:
            acct = (
                db.query(AdAccount)
                .filter(AdAccount.is_active.is_(True))
                .filter(
                    or_(
                        AdAccount.account_name.ilike(f"%{branch_name}%"),
                        AdAccount.account_name.ilike(f"%Meander {branch_name}%"),
                    )
                )
                .first()
            )
            if acct:
                branch_id = acct.id

    page = LandingPage(
        source=SOURCE_EXTERNAL,
        branch_id=branch_id,
        title=title_fallback or f"{n.host}/{n.slug}" or n.host,
        domain=n.host,
        slug=n.slug,
        status=STATUS_DISCOVERED,
        is_active=True,
    )
    db.add(page)
    db.flush()
    return page


# ---------------------------------------------------------------------------
# Versions (managed pages only)
# ---------------------------------------------------------------------------


def create_version(
    db: Session,
    *,
    landing_page_id: str,
    content: dict[str, Any],
    created_by: str | None = None,
    change_note: str | None = None,
) -> LandingPageVersion:
    """Append a new version. Page moves back to DRAFT if it was REJECTED."""
    page = db.query(LandingPage).filter(LandingPage.id == landing_page_id).one()
    if page.source != SOURCE_MANAGED:
        raise ValueError("Cannot create content version on an external landing page")

    # version_num: next integer after the current max for this page
    current_max = (
        db.query(func.max(LandingPageVersion.version_num))
        .filter(LandingPageVersion.landing_page_id == landing_page_id)
        .scalar()
        or 0
    )
    v = LandingPageVersion(
        landing_page_id=landing_page_id,
        version_num=current_max + 1,
        content=content,
        created_by=created_by,
        change_note=change_note,
    )
    db.add(v)

    # If the page was REJECTED, a new version resets it to DRAFT
    if page.status == STATUS_REJECTED:
        page.status = STATUS_DRAFT
    db.flush()
    return v


def publish_version(
    db: Session,
    *,
    version_id: str,
    actor_user_id: str | None = None,
) -> LandingPage:
    """Move a version to PUBLISHED state (requires APPROVED first).

    Creator-only: the submitter of the approval record is the only one who
    may publish (mirrors the combo-launch rule in CLAUDE.md).
    """
    v = db.query(LandingPageVersion).filter(LandingPageVersion.id == version_id).one()
    page = db.query(LandingPage).filter(LandingPage.id == v.landing_page_id).one()

    if page.status not in (STATUS_APPROVED, STATUS_PUBLISHED):
        raise ValueError(
            f"Cannot publish: page status is {page.status}, must be APPROVED"
        )

    # Verify creator-only: the latest approval record must have this user as submitter
    if actor_user_id is not None:
        latest_appr = (
            db.query(LandingPageApproval)
            .filter(
                LandingPageApproval.landing_page_id == page.id,
                LandingPageApproval.version_id == version_id,
            )
            .order_by(LandingPageApproval.submitted_at.desc())
            .first()
        )
        if latest_appr and latest_appr.submitted_by and latest_appr.submitted_by != actor_user_id:
            raise PermissionError("Only the submitter may publish this version")

    now = datetime.now(timezone.utc)
    v.published_at = now
    page.current_version_id = v.id
    page.status = STATUS_PUBLISHED
    page.published_at = now
    db.flush()
    return page


# ---------------------------------------------------------------------------
# Approvals (mirror combo_approvals logic)
# ---------------------------------------------------------------------------


def submit_for_approval(
    db: Session,
    *,
    landing_page_id: str,
    version_id: str,
    submitted_by: str,
    reviewer_ids: list[str],
    deadline_hours: int | None = 48,
) -> LandingPageApproval:
    page = db.query(LandingPage).filter(LandingPage.id == landing_page_id).one()
    if page.source != SOURCE_MANAGED:
        raise ValueError("Only managed pages can be submitted for approval")
    if page.status not in (STATUS_DRAFT, STATUS_REJECTED):
        raise ValueError(f"Cannot submit: status is {page.status}")
    if not reviewer_ids:
        raise ValueError("At least one reviewer required")

    # Cancel any in-flight approvals for this page
    inflight = (
        db.query(LandingPageApproval)
        .filter(
            LandingPageApproval.landing_page_id == landing_page_id,
            LandingPageApproval.status == APPROVAL_PENDING,
        )
        .all()
    )
    now = datetime.now(timezone.utc)
    for appr in inflight:
        appr.status = APPROVAL_CANCELLED
        appr.resolved_at = now

    deadline = now + timedelta(hours=deadline_hours) if deadline_hours else None
    appr = LandingPageApproval(
        landing_page_id=landing_page_id,
        version_id=version_id,
        status=APPROVAL_PENDING,
        submitted_by=submitted_by,
        submitted_at=now,
        deadline=deadline,
    )
    db.add(appr)
    db.flush()

    for rid in set(reviewer_ids):
        rev = LandingPageApprovalReviewer(
            approval_id=appr.id,
            reviewer_id=rid,
            status=REVIEWER_PENDING,
        )
        db.add(rev)

    page.status = STATUS_PENDING_APPROVAL
    db.flush()
    return appr


def record_reviewer_decision(
    db: Session,
    *,
    approval_id: str,
    reviewer_id: str,
    decision: str,  # APPROVED | REJECTED
    comment: str | None = None,
) -> LandingPageApproval:
    if decision not in (REVIEWER_APPROVED, REVIEWER_REJECTED):
        raise ValueError(f"Invalid decision: {decision}")

    row = (
        db.query(LandingPageApprovalReviewer)
        .filter(
            LandingPageApprovalReviewer.approval_id == approval_id,
            LandingPageApprovalReviewer.reviewer_id == reviewer_id,
        )
        .one_or_none()
    )
    if row is None:
        raise PermissionError("Reviewer not assigned to this approval")
    if row.status != REVIEWER_PENDING:
        raise ValueError(f"Already decided: {row.status}")

    now = datetime.now(timezone.utc)
    row.status = decision
    row.comment = comment
    row.decided_at = now
    db.flush()

    # Recompute approval status
    appr = db.query(LandingPageApproval).filter(LandingPageApproval.id == approval_id).one()
    page = db.query(LandingPage).filter(LandingPage.id == appr.landing_page_id).one()

    all_reviewers = (
        db.query(LandingPageApprovalReviewer)
        .filter(LandingPageApprovalReviewer.approval_id == approval_id)
        .all()
    )
    statuses = {r.status for r in all_reviewers}

    if REVIEWER_REJECTED in statuses:
        # ANY reject → REJECTED
        appr.status = APPROVAL_REJECTED
        appr.resolved_at = now
        if not appr.reject_reason and comment:
            appr.reject_reason = comment
        page.status = STATUS_REJECTED
    elif statuses == {REVIEWER_APPROVED}:
        # ALL approve → APPROVED
        appr.status = APPROVAL_APPROVED
        appr.resolved_at = now
        page.status = STATUS_APPROVED
    # else: still has PENDING reviewers → stay PENDING_APPROVAL

    db.flush()
    return appr


# ---------------------------------------------------------------------------
# Metrics rollup (ads + Clarity)
# ---------------------------------------------------------------------------


def rollup_metrics(
    db: Session,
    *,
    landing_page_id: str,
    date_from: date,
    date_to: date,
) -> dict[str, Any]:
    """Aggregate ad metrics + Clarity metrics for a landing page over a date range.

    Ad metrics (spend/clicks/conversions/revenue) are pulled from MetricsCache
    joined via landing_page_ad_links → campaigns (and optionally ads for
    ad-level detail).

    Clarity metrics (sessions/scroll/rage/etc.) come from
    landing_page_clarity_snapshots — aggregate row (NULL UTMs) is summed.
    """
    # --- Ad side: sum over unique campaign_ids linked to this page ---
    campaign_ids = [
        row[0]
        for row in db.query(LandingPageAdLink.campaign_id)
        .filter(
            LandingPageAdLink.landing_page_id == landing_page_id,
            LandingPageAdLink.campaign_id.isnot(None),
        )
        .distinct()
        .all()
    ]

    ad_totals = {
        "spend": 0.0,
        "impressions": 0,
        "clicks": 0,
        "link_clicks": 0,  # Meta's inline_link_clicks (or mirror of clicks on Google)
        "conversions": 0,
        "revenue": 0.0,
        "landing_page_views": 0,
        "ctr": None,
        "cpc": None,
        "cpa": None,
        "roas": None,
    }
    by_platform: dict[str, dict[str, float]] = {}

    # Display currency: if all linked campaigns share one ad-account currency
    # we display in that native currency. Otherwise we normalise to VND
    # (memory: VND is the base currency, currency_rates.rate_to_vnd).
    display_currency = "VND"
    convert_to_vnd = False

    if campaign_ids:
        currency_rows = (
            db.query(AdAccount.currency)
            .join(Campaign, Campaign.account_id == AdAccount.id)
            .filter(Campaign.id.in_(campaign_ids))
            .distinct()
            .all()
        )
        currencies = {(c[0] or "VND") for c in currency_rows}
        if len(currencies) == 1:
            display_currency = currencies.pop()
            convert_to_vnd = False
        else:
            display_currency = "VND"
            convert_to_vnd = True

        fx_rates: dict[str, float] = {"VND": 1.0}
        if convert_to_vnd:
            rate_rows = (
                db.query(CurrencyRate.currency, CurrencyRate.rate_to_vnd)
                .filter(CurrencyRate.currency.in_(currencies))
                .all()
            )
            fx_rates.update({r[0]: float(r[1]) for r in rate_rows})

        q = (
            db.query(
                MetricsCache.platform,
                AdAccount.currency.label("currency"),
                func.coalesce(func.sum(MetricsCache.spend), 0).label("spend"),
                func.coalesce(func.sum(MetricsCache.impressions), 0).label("impressions"),
                func.coalesce(func.sum(MetricsCache.clicks), 0).label("clicks"),
                func.coalesce(func.sum(MetricsCache.link_clicks), 0).label("link_clicks"),
                func.coalesce(func.sum(MetricsCache.conversions), 0).label("conversions"),
                func.coalesce(func.sum(MetricsCache.revenue), 0).label("revenue"),
                func.coalesce(func.sum(MetricsCache.landing_page_views), 0).label("lpv"),
            )
            .join(Campaign, Campaign.id == MetricsCache.campaign_id)
            .join(AdAccount, AdAccount.id == Campaign.account_id)
            .filter(
                MetricsCache.campaign_id.in_(campaign_ids),
                MetricsCache.date >= date_from,
                MetricsCache.date <= date_to,
            )
            .group_by(MetricsCache.platform, AdAccount.currency)
        )
        for row in q.all():
            row_currency = row.currency or "VND"
            fx = fx_rates.get(row_currency, 1.0) if convert_to_vnd else 1.0
            spend = float(row.spend or 0) * fx
            revenue = float(row.revenue or 0) * fx
            impr = int(row.impressions or 0)
            clicks = int(row.clicks or 0)
            link_clicks = int(row.link_clicks or 0)
            convs = int(row.conversions or 0)
            lpv = int(row.lpv or 0)

            # Merge into platform bucket (multiple currency rows under same
            # platform get summed in display currency).
            plat = by_platform.setdefault(row.platform, {
                "spend": 0.0, "impressions": 0, "clicks": 0,
                "link_clicks": 0, "conversions": 0, "revenue": 0.0,
                "landing_page_views": 0,
                "ctr": None, "cpc": None, "cpa": None, "roas": None,
            })
            plat["spend"] += spend
            plat["impressions"] += impr
            plat["clicks"] += clicks
            plat["link_clicks"] += link_clicks
            plat["conversions"] += convs
            plat["revenue"] += revenue
            plat["landing_page_views"] += lpv

            ad_totals["spend"] += spend
            ad_totals["impressions"] += impr
            ad_totals["clicks"] += clicks
            ad_totals["link_clicks"] += link_clicks
            ad_totals["conversions"] += convs
            ad_totals["revenue"] += revenue
            ad_totals["landing_page_views"] += lpv

        for plat in by_platform.values():
            if plat["impressions"]:
                plat["ctr"] = plat["clicks"] / plat["impressions"]
            if plat["clicks"]:
                plat["cpc"] = plat["spend"] / plat["clicks"]
            if plat["conversions"]:
                plat["cpa"] = plat["spend"] / plat["conversions"]
            if plat["spend"]:
                plat["roas"] = plat["revenue"] / plat["spend"]

        if ad_totals["impressions"]:
            ad_totals["ctr"] = ad_totals["clicks"] / ad_totals["impressions"]
        if ad_totals["clicks"]:
            ad_totals["cpc"] = ad_totals["spend"] / ad_totals["clicks"]
        if ad_totals["conversions"]:
            ad_totals["cpa"] = ad_totals["spend"] / ad_totals["conversions"]
        if ad_totals["spend"]:
            ad_totals["roas"] = ad_totals["revenue"] / ad_totals["spend"]

    # --- Clarity side: aggregate rows (utm_* are NULL) ---
    clarity = (
        db.query(
            func.coalesce(func.sum(LandingPageClaritySnapshot.sessions), 0).label("sessions"),
            func.coalesce(func.sum(LandingPageClaritySnapshot.distinct_users), 0).label("users"),
            func.avg(LandingPageClaritySnapshot.avg_scroll_depth).label("scroll"),
            func.coalesce(func.sum(LandingPageClaritySnapshot.total_time_sec), 0).label("total_time"),
            func.coalesce(func.sum(LandingPageClaritySnapshot.active_time_sec), 0).label("active_time"),
            func.coalesce(func.sum(LandingPageClaritySnapshot.dead_clicks), 0).label("dead"),
            func.coalesce(func.sum(LandingPageClaritySnapshot.rage_clicks), 0).label("rage"),
            func.coalesce(func.sum(LandingPageClaritySnapshot.error_clicks), 0).label("err"),
            func.coalesce(func.sum(LandingPageClaritySnapshot.quickback_clicks), 0).label("qback"),
            func.coalesce(func.sum(LandingPageClaritySnapshot.excessive_scrolls), 0).label("xscroll"),
            func.coalesce(func.sum(LandingPageClaritySnapshot.script_errors), 0).label("script_err"),
        )
        .filter(
            LandingPageClaritySnapshot.landing_page_id == landing_page_id,
            LandingPageClaritySnapshot.date >= date_from,
            LandingPageClaritySnapshot.date <= date_to,
            LandingPageClaritySnapshot.utm_source.is_(None),
            LandingPageClaritySnapshot.utm_campaign.is_(None),
            LandingPageClaritySnapshot.utm_content.is_(None),
        )
        .one()
    )

    sessions = int(clarity.sessions or 0)
    clarity_data = {
        "sessions": sessions,
        "distinct_users": int(clarity.users or 0),
        "avg_scroll_depth": float(clarity.scroll) if clarity.scroll is not None else None,
        "total_time_sec": int(clarity.total_time or 0),
        "active_time_sec": int(clarity.active_time or 0),
        "dead_clicks": int(clarity.dead or 0),
        "rage_clicks": int(clarity.rage or 0),
        "error_clicks": int(clarity.err or 0),
        "quickback_clicks": int(clarity.qback or 0),
        "excessive_scrolls": int(clarity.xscroll or 0),
        "script_errors": int(clarity.script_err or 0),
        # Useful derived rates:
        "rage_rate": (int(clarity.rage or 0) / sessions) if sessions else None,
        "dead_rate": (int(clarity.dead or 0) / sessions) if sessions else None,
        "quickback_rate": (int(clarity.qback or 0) / sessions) if sessions else None,
    }

    # --- Cross-signal: link_clicks & LPV from ads → sessions from Clarity ---
    # We use `link_clicks` (Meta's inline_link_clicks) as the pre-page count —
    # that's the click that specifically goes to the landing page, whereas
    # `clicks` inflates with video plays, profile taps, likes, etc.
    # Google Ads mirrors clicks→link_clicks so the comparison is uniform.
    link_click_to_session = None
    lpv_to_session = None
    if ad_totals["link_clicks"] and sessions:
        link_click_to_session = sessions / ad_totals["link_clicks"]
    if ad_totals["landing_page_views"] and sessions:
        lpv_to_session = sessions / ad_totals["landing_page_views"]

    # Direct Booking Conversion Rate (the one metric that matters, §1.2)
    dbcr = None
    if sessions:
        dbcr = ad_totals["conversions"] / sessions if ad_totals["conversions"] else 0.0

    # --- Clarity data coverage: how many days in [date_from..date_to] do we
    # actually have snapshots for? UI uses this to warn when the selected
    # window is too wide for the data we've synced so far.
    requested_days = (date_to - date_from).days + 1
    distinct_dates = (
        db.query(func.count(func.distinct(LandingPageClaritySnapshot.date)))
        .filter(
            LandingPageClaritySnapshot.landing_page_id == landing_page_id,
            LandingPageClaritySnapshot.date >= date_from,
            LandingPageClaritySnapshot.date <= date_to,
        )
        .scalar()
        or 0
    )
    latest_date_row = (
        db.query(func.max(LandingPageClaritySnapshot.date))
        .filter(LandingPageClaritySnapshot.landing_page_id == landing_page_id)
        .scalar()
    )

    # --- GA4 aggregate (utm-less row) + coverage ---
    ga4_agg = (
        db.query(
            func.coalesce(func.sum(LandingPageGA4Snapshot.sessions), 0).label("sessions"),
            func.coalesce(func.sum(LandingPageGA4Snapshot.engaged_sessions), 0).label("engaged"),
            func.coalesce(func.sum(LandingPageGA4Snapshot.active_users), 0).label("users"),
            func.coalesce(func.sum(LandingPageGA4Snapshot.new_users), 0).label("new_users"),
            func.coalesce(func.sum(LandingPageGA4Snapshot.screen_page_views), 0).label("pv"),
            func.avg(LandingPageGA4Snapshot.engagement_rate).label("eng_rate"),
            func.avg(LandingPageGA4Snapshot.avg_session_duration_sec).label("dur"),
            func.avg(LandingPageGA4Snapshot.bounce_rate).label("bounce"),
            # Web Vitals — take max (p75) across the window
            func.max(LandingPageGA4Snapshot.lcp_p75_ms).label("lcp"),
            func.max(LandingPageGA4Snapshot.inp_p75_ms).label("inp"),
            func.max(LandingPageGA4Snapshot.cls_p75).label("cls"),
            func.max(LandingPageGA4Snapshot.fcp_p75_ms).label("fcp"),
        )
        .filter(
            LandingPageGA4Snapshot.landing_page_id == landing_page_id,
            LandingPageGA4Snapshot.date >= date_from,
            LandingPageGA4Snapshot.date <= date_to,
            LandingPageGA4Snapshot.source.is_(None),
            LandingPageGA4Snapshot.medium.is_(None),
            LandingPageGA4Snapshot.campaign.is_(None),
        )
        .one()
    )
    ga4_sessions = int(ga4_agg.sessions or 0)
    ga4_data = {
        "sessions": ga4_sessions,
        "engaged_sessions": int(ga4_agg.engaged or 0),
        "active_users": int(ga4_agg.users or 0),
        "new_users": int(ga4_agg.new_users or 0),
        "page_views": int(ga4_agg.pv or 0),
        "engagement_rate": float(ga4_agg.eng_rate) if ga4_agg.eng_rate is not None else None,
        "avg_session_duration_sec": float(ga4_agg.dur) if ga4_agg.dur is not None else None,
        "bounce_rate": float(ga4_agg.bounce) if ga4_agg.bounce is not None else None,
        "web_vitals": {
            "lcp_p75_ms": int(ga4_agg.lcp) if ga4_agg.lcp is not None else None,
            "inp_p75_ms": int(ga4_agg.inp) if ga4_agg.inp is not None else None,
            "cls_p75": float(ga4_agg.cls) if ga4_agg.cls is not None else None,
            "fcp_p75_ms": int(ga4_agg.fcp) if ga4_agg.fcp is not None else None,
            # Playbook §5.3 pass/fail
            "lcp_pass": (ga4_agg.lcp is not None and int(ga4_agg.lcp) < 2500),
            "inp_pass": (ga4_agg.inp is not None and int(ga4_agg.inp) < 200),
            "cls_pass": (ga4_agg.cls is not None and float(ga4_agg.cls) < 0.1),
        },
    }
    ga4_distinct_dates = (
        db.query(func.count(func.distinct(LandingPageGA4Snapshot.date)))
        .filter(
            LandingPageGA4Snapshot.landing_page_id == landing_page_id,
            LandingPageGA4Snapshot.date >= date_from,
            LandingPageGA4Snapshot.date <= date_to,
        )
        .scalar()
        or 0
    )
    ga4_latest = (
        db.query(func.max(LandingPageGA4Snapshot.date))
        .filter(LandingPageGA4Snapshot.landing_page_id == landing_page_id)
        .scalar()
    )

    # --- Cross-source reconciliation (the key insight for this dashboard) ---
    # GA4 is the independent 3rd party. Comparing what each source reports
    # tells us where tracking / attribution is broken.
    # We compare against `link_clicks` (not raw `clicks`) because clicks
    # inflates with non-destination interactions; link_clicks is the direct
    # comparison against landing page traffic.
    reconciliation: dict[str, Any] = {}
    if ga4_sessions and ad_totals["landing_page_views"]:
        reconciliation["ga4_vs_meta_lpv"] = ga4_sessions / ad_totals["landing_page_views"]
    if ga4_sessions and sessions:
        reconciliation["clarity_vs_ga4"] = sessions / ga4_sessions
    if ga4_sessions and ad_totals["link_clicks"]:
        reconciliation["ga4_vs_link_clicks"] = ga4_sessions / ad_totals["link_clicks"]
    # Legacy key kept for dashboards that still read it
    if ga4_sessions and ad_totals["clicks"]:
        reconciliation["ga4_vs_clicks"] = ga4_sessions / ad_totals["clicks"]

    # DBCR using GA4's independent session count as denominator (most honest)
    dbcr_ga4 = None
    if ga4_sessions:
        dbcr_ga4 = ad_totals["conversions"] / ga4_sessions if ad_totals["conversions"] else 0.0

    return {
        "landing_page_id": landing_page_id,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "ads": {
            "totals": ad_totals,
            "by_platform": by_platform,
            "campaign_count": len(campaign_ids),
            "currency": display_currency,
            "currency_normalized": convert_to_vnd,
        },
        "clarity": clarity_data,
        "clarity_coverage": {
            "requested_days": requested_days,
            "days_with_data": int(distinct_dates),
            "latest_synced_date": latest_date_row.isoformat() if latest_date_row else None,
            "is_complete": int(distinct_dates) >= requested_days,
        },
        "ga4": ga4_data,
        "ga4_coverage": {
            "requested_days": requested_days,
            "days_with_data": int(ga4_distinct_dates),
            "latest_synced_date": ga4_latest.isoformat() if ga4_latest else None,
            "is_complete": int(ga4_distinct_dates) >= requested_days,
        },
        "derived": {
            "click_to_session_ratio": link_click_to_session,  # now uses link_clicks
            "link_click_to_session_ratio": link_click_to_session,
            "lpv_to_session_ratio": lpv_to_session,
            "dbcr": dbcr,
            "dbcr_ga4": dbcr_ga4,
            "reconciliation": reconciliation,
        },
    }
