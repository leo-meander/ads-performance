"""Landing Pages router — CRUD, versions, approvals, metrics, ad-links, import."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_section
from app.models.account import AdAccount
from app.models.landing_page import (
    LandingPage,
    SOURCE_EXTERNAL,
    SOURCE_MANAGED,
    STATUS_ARCHIVED,
    STATUS_DRAFT,
    STATUS_PUBLISHED,
)
from app.models.landing_page_ad_link import LandingPageAdLink
from app.models.landing_page_clarity import LandingPageClaritySnapshot
from app.models.landing_page_version import LandingPageVersion
from app.models.user import User
from app.services.landing_page_importer import import_from_ads
from app.services.landing_page_service import (
    create_version,
    publish_version,
    rollup_metrics,
)
from app.services.landing_page_url_normalizer import build_url_with_utms, normalize_url
from app.core.branches import resolve_branch_for_account_name

router = APIRouter()


def _api(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _serialize_page(p: LandingPage, *, include_version: bool = False, db: Session | None = None) -> dict:
    branch_name: str | None = None
    if p.branch_id and db:
        acct = db.query(AdAccount.account_name).filter(AdAccount.id == p.branch_id).scalar()
        branch_name = resolve_branch_for_account_name(acct) if acct else None

    out = {
        "id": p.id,
        "source": p.source,
        "branch_id": p.branch_id,
        "branch_name": branch_name,
        "title": p.title,
        "domain": p.domain,
        "slug": p.slug,
        "public_url": f"https://{p.domain}/{p.slug}" if p.slug else f"https://{p.domain}/",
        "language": p.language,
        "ta": p.ta,
        "status": p.status,
        "current_version_id": p.current_version_id,
        "published_at": p.published_at.isoformat() if p.published_at else None,
        "clarity_project_id": p.clarity_project_id,
        "created_by": p.created_by,
        "notes": p.notes,
        "is_active": p.is_active,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }
    if include_version and db is not None and p.current_version_id:
        v = db.query(LandingPageVersion).filter(LandingPageVersion.id == p.current_version_id).one_or_none()
        if v:
            out["current_version"] = {
                "id": v.id,
                "version_num": v.version_num,
                "content": v.content,
                "created_by": v.created_by,
                "change_note": v.change_note,
                "published_at": v.published_at.isoformat() if v.published_at else None,
            }
    return out


# ────────────────────────── schemas ─────────────────────────────────────────


class CreatePageReq(BaseModel):
    source: str = Field(default=SOURCE_MANAGED)  # managed | external
    branch_id: str | None = None
    title: str
    domain: str
    slug: str
    language: str | None = None
    ta: str | None = None
    clarity_project_id: str | None = None
    notes: str | None = None


class UpdatePageReq(BaseModel):
    title: str | None = None
    domain: str | None = None
    slug: str | None = None
    language: str | None = None
    ta: str | None = None
    branch_id: str | None = None
    clarity_project_id: str | None = None
    notes: str | None = None


class CreateVersionReq(BaseModel):
    content: dict[str, Any]
    change_note: str | None = None


class LinkAdReq(BaseModel):
    platform: str
    campaign_id: str | None = None
    ad_id: str | None = None
    asset_group_id: str | None = None
    destination_url: str


class GenerateUrlReq(BaseModel):
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None


# ────────────────────────── version overview ────────────────────────────────

# V2 slug patterns — pages launched June-July 2026.
# All others in these domains are considered V1.
_V2_PATTERNS: list[tuple[str, str]] = [
    ("osk.staymeander.com", "couple-explore-osaka%"),
    ("1948.staymeander.com", "taipei-heritage-hotel%"),
    ("tpe.staymeander.com", "ximen-social-hotel%"),
    ("oani-taipei.staymeander.com", "retreat-hotel%"),
    ("sgn.staymeander.com", "stay-work-wander%"),
]
_OVERVIEW_DOMAINS = (
    "osk.staymeander.com",
    "1948.staymeander.com",
    "tpe.staymeander.com",
    "oani-taipei.staymeander.com",
    "sgn.staymeander.com",
)
_BRANCH_LABELS: dict[str, str] = {
    "osk.staymeander.com": "Meander Osaka",
    "1948.staymeander.com": "Meander 1948",
    "tpe.staymeander.com": "Meander Taipei",
    "oani-taipei.staymeander.com": "Oani Taipei",
    "sgn.staymeander.com": "Meander Saigon",
}
_EXCLUDE_SLUGS = ("day-by-day-plan%", "thank-you%", "%travel-guide%")
# Date from which V2 metrics are counted (campaigns switched landing page URLs on this date)
_V2_METRICS_FROM = "2026-06-19"


@router.get("/landing-pages/version-overview")
def version_overview(
    current_user: User = Depends(require_section("landing_pages", "view")),
    db: Session = Depends(get_db),
):
    """Return per-version aggregate metrics for the 5 active landing page domains.

    Response: { branches: [{ domain, branch, versions: { "Version 1": VersionAgg, ... } }],
                version_labels: ["Version 1", "Version 2", ...] }
    VersionAgg includes ads + Clarity + GA4 metrics.
    """
    try:
        version_cases = "\n".join(
            f"WHEN lp.domain = '{d}' AND lp.slug LIKE '{s}' THEN 'Version 2'"
            for d, s in _V2_PATTERNS
        )
        # Reuse same WHEN conditions for metrics_from date filter
        metrics_from_cases = "\n".join(
            f"WHEN lp.domain = '{d}' AND lp.slug LIKE '{s}' THEN '{_V2_METRICS_FROM}'"
            for d, s in _V2_PATTERNS
        )
        exclude_where = " AND ".join(
            f"lp.slug NOT LIKE '{pat}'" for pat in _EXCLUDE_SLUGS
        )
        domain_list = ", ".join(f"'{d}'" for d in _OVERVIEW_DOMAINS)

        sql = text(f"""
            WITH page_tags AS (
                SELECT lp.id, lp.domain, lp.slug,
                    CASE
                        {version_cases}
                        ELSE 'Version 1'
                    END AS version,
                    CASE
                        {metrics_from_cases}
                        ELSE '2000-01-01'
                    END::date AS metrics_from
                FROM landing_pages lp
                WHERE lp.is_active = TRUE
                  AND lp.domain IN ({domain_list})
                  AND {exclude_where}
            ),
            ad_metrics AS (
                SELECT lpal.landing_page_id,
                    SUM(mc.spend)        AS spend,
                    SUM(mc.conversions)  AS conversions,
                    SUM(mc.revenue)      AS revenue,
                    SUM(mc.add_to_cart)  AS add_to_cart
                FROM landing_page_ad_links lpal
                JOIN page_tags pt ON pt.id = lpal.landing_page_id
                JOIN metrics_cache mc ON mc.campaign_id = lpal.campaign_id
                  AND mc.ad_id IS NULL
                  AND mc.date >= pt.metrics_from
                  AND (
                    (lpal.ad_set_id IS NOT NULL AND mc.ad_set_id = lpal.ad_set_id)
                    OR
                    (lpal.ad_set_id IS NULL AND mc.ad_set_id IS NULL)
                  )
                GROUP BY lpal.landing_page_id
            ),
            clarity_metrics AS (
                SELECT cs.landing_page_id,
                    SUM(cs.sessions)         AS sessions,
                    AVG(cs.avg_scroll_depth) AS avg_scroll_pct,
                    SUM(cs.rage_clicks)      AS rage_clicks,
                    SUM(cs.quickback_clicks) AS quickback_clicks
                FROM landing_page_clarity_snapshots cs
                JOIN page_tags pt ON pt.id = cs.landing_page_id
                WHERE cs.utm_source IS NULL AND cs.utm_campaign IS NULL AND cs.utm_content IS NULL
                  AND cs.date >= pt.metrics_from
                GROUP BY cs.landing_page_id
            ),
            ga4_metrics AS (
                SELECT g.landing_page_id,
                    SUM(g.engaged_sessions)         AS engaged_sessions,
                    AVG(g.engagement_rate)          AS engagement_rate,
                    AVG(g.bounce_rate)              AS bounce_rate,
                    SUM(g.begin_checkout)           AS begin_checkout,
                    AVG(g.avg_session_duration_sec) AS avg_session_duration_sec
                FROM landing_page_ga4_snapshots g
                JOIN page_tags pt ON pt.id = g.landing_page_id
                WHERE g.source IS NULL AND g.medium IS NULL AND g.campaign IS NULL
                  AND g.date >= pt.metrics_from
                GROUP BY g.landing_page_id
            )
            SELECT
                pt.domain,
                pt.version,
                pt.slug,
                ROUND(COALESCE(am.spend, 0)::numeric, 0)        AS spend,
                ROUND(COALESCE(am.revenue, 0)::numeric, 0)      AS revenue,
                COALESCE(am.conversions, 0)                      AS conversions,
                COALESCE(cm.sessions, 0)                         AS sessions,
                COALESCE(am.add_to_cart, 0)                      AS add_to_cart,
                CASE WHEN COALESCE(am.spend, 0) > 0
                    THEN ROUND((am.revenue / am.spend)::numeric, 2)
                END                                              AS roas,
                CASE WHEN COALESCE(cm.sessions, 0) > 0
                    THEN ROUND((am.conversions::numeric / cm.sessions * 100), 3)
                END                                              AS conv_rate_pct,
                CASE WHEN COALESCE(cm.sessions, 0) > 0
                    THEN ROUND((am.add_to_cart::numeric / cm.sessions * 100), 2)
                END                                              AS atc_rate_pct,
                ROUND(COALESCE(cm.avg_scroll_pct, 0)::numeric, 1) AS avg_scroll_pct,
                COALESCE(cm.rage_clicks, 0)                      AS rage_clicks,
                COALESCE(cm.quickback_clicks, 0)                 AS quickback_clicks,
                COALESCE(gm.engaged_sessions, 0)                 AS engaged_sessions,
                ROUND(COALESCE(gm.engagement_rate, 0)::numeric, 4) AS engagement_rate,
                ROUND(COALESCE(gm.bounce_rate, 0)::numeric, 4)  AS bounce_rate,
                COALESCE(gm.begin_checkout, 0)                   AS begin_checkout,
                ROUND(COALESCE(gm.avg_session_duration_sec, 0)::numeric, 1) AS avg_session_duration_sec
            FROM page_tags pt
            LEFT JOIN ad_metrics am ON am.landing_page_id = pt.id
            LEFT JOIN clarity_metrics cm ON cm.landing_page_id = pt.id
            LEFT JOIN ga4_metrics gm ON gm.landing_page_id = pt.id
            WHERE COALESCE(am.spend, 0) > 0 OR COALESCE(cm.sessions, 0) > 0
            ORDER BY pt.domain, pt.version DESC, COALESCE(am.spend, 0) DESC
        """)

        rows = db.execute(sql).mappings().all()

        by_domain: dict[str, dict] = {}
        for r in rows:
            domain = r["domain"]
            if domain not in by_domain:
                by_domain[domain] = {
                    "domain": domain,
                    "branch": _BRANCH_LABELS.get(domain, domain),
                    "versions": {},
                }
            page = {
                "slug": r["slug"],
                "spend": float(r["spend"] or 0),
                "revenue": float(r["revenue"] or 0),
                "conversions": float(r["conversions"] or 0),
                "sessions": int(r["sessions"] or 0),
                "add_to_cart": int(r["add_to_cart"] or 0),
                "roas": float(r["roas"]) if r["roas"] is not None else None,
                "conv_rate_pct": float(r["conv_rate_pct"]) if r["conv_rate_pct"] is not None else None,
                "atc_rate_pct": float(r["atc_rate_pct"]) if r["atc_rate_pct"] is not None else None,
                "avg_scroll_pct": float(r["avg_scroll_pct"] or 0),
                "rage_clicks": int(r["rage_clicks"] or 0),
                "quickback_clicks": int(r["quickback_clicks"] or 0),
                "engaged_sessions": int(r["engaged_sessions"] or 0),
                "engagement_rate": float(r["engagement_rate"] or 0),
                "bounce_rate": float(r["bounce_rate"] or 0),
                "begin_checkout": int(r["begin_checkout"] or 0),
                "avg_session_duration_sec": float(r["avg_session_duration_sec"] or 0),
                "low_confidence": int(r["sessions"] or 0) < 10,
            }
            version = r["version"]
            by_domain[domain]["versions"].setdefault(version, []).append(page)

        def _agg(pages: list[dict]) -> dict:
            total_sessions = sum(p["sessions"] for p in pages)
            total_conv = sum(p["conversions"] for p in pages)
            total_spend = sum(p["spend"] for p in pages)
            total_revenue = sum(p["revenue"] for p in pages)
            total_atc = sum(p["add_to_cart"] for p in pages)
            total_scroll = sum(p["avg_scroll_pct"] * p["sessions"] for p in pages)
            total_engaged = sum(p["engaged_sessions"] for p in pages)
            ga4_sessions = sum(p.get("engaged_sessions", 0) + 1 for p in pages)  # approx denom
            total_checkout = sum(p["begin_checkout"] for p in pages)
            # engagement_rate weighted by GA4 sessions
            eng_num = sum(p["engagement_rate"] * p["sessions"] for p in pages)
            bounce_num = sum(p["bounce_rate"] * p["sessions"] for p in pages)
            avg_dur_num = sum(p["avg_session_duration_sec"] * p["sessions"] for p in pages)
            return {
                "sessions": total_sessions,
                "conversions": round(total_conv, 1),
                "conv_rate_pct": round(total_conv / total_sessions * 100, 3) if total_sessions else None,
                "avg_roas": round(total_revenue / total_spend, 2) if total_spend else None,
                "avg_scroll_pct": round(total_scroll / total_sessions, 1) if total_sessions else None,
                "atc_rate_pct": round(total_atc / total_sessions * 100, 2) if total_sessions else None,
                "engagement_rate": round(eng_num / total_sessions, 4) if total_sessions else None,
                "bounce_rate": round(bounce_num / total_sessions, 4) if total_sessions else None,
                "begin_checkout_rate": round(total_checkout / total_sessions * 100, 2) if total_sessions else None,
                "avg_session_duration_sec": round(avg_dur_num / total_sessions, 1) if total_sessions else None,
                "page_count": len(pages),
                "pages": pages,
            }

        all_versions: list[str] = []
        seen: set[str] = set()
        for domain in _OVERVIEW_DOMAINS:
            if domain not in by_domain:
                continue
            for v in by_domain[domain]["versions"]:
                if v not in seen:
                    seen.add(v)
                    all_versions.append(v)
        all_versions.sort()

        result = []
        for domain in _OVERVIEW_DOMAINS:
            if domain not in by_domain:
                continue
            d = by_domain[domain]
            result.append({
                "domain": domain,
                "branch": d["branch"],
                "versions": {v: _agg(d["versions"].get(v, [])) for v in all_versions},
            })

        return _api({"branches": result, "version_labels": all_versions})
    except Exception as e:
        return _api(error=str(e))


# ────────────────────────── list + CRUD ─────────────────────────────────────


@router.get("/landing-pages")
def list_pages(
    status: str | None = Query(None),
    source: str | None = Query(None),
    branch_id: str | None = Query(None),
    q: str | None = Query(None, description="search title/domain/slug"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_inactive: bool = Query(False),
    current_user: User = Depends(require_section("landing_pages", "view")),
    db: Session = Depends(get_db),
):
    try:
        query = db.query(LandingPage)
        if not include_inactive:
            query = query.filter(LandingPage.is_active.is_(True))
        if status:
            query = query.filter(LandingPage.status == status)
        if source:
            query = query.filter(LandingPage.source == source)
        if branch_id:
            query = query.filter(LandingPage.branch_id == branch_id)
        if q:
            like = f"%{q}%"
            query = query.filter(
                (LandingPage.title.ilike(like))
                | (LandingPage.domain.ilike(like))
                | (LandingPage.slug.ilike(like))
            )
        total = query.count()
        rows = (
            query.order_by(LandingPage.updated_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return _api({
            "items": [_serialize_page(p) for p in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        })
    except Exception as e:
        return _api(error=str(e))


@router.post("/landing-pages")
def create_page(
    body: CreatePageReq,
    current_user: User = Depends(require_section("landing_pages", "edit")),
    db: Session = Depends(get_db),
):
    try:
        if body.source not in (SOURCE_MANAGED, SOURCE_EXTERNAL):
            raise ValueError(f"invalid source: {body.source}")

        # Validate branch exists if provided
        if body.branch_id:
            acct = db.query(AdAccount).filter(AdAccount.id == body.branch_id).one_or_none()
            if acct is None:
                raise ValueError(f"branch_id {body.branch_id} not found")

        # Enforce uniqueness
        existing = (
            db.query(LandingPage)
            .filter(LandingPage.domain == body.domain, LandingPage.slug == body.slug)
            .one_or_none()
        )
        if existing is not None:
            raise ValueError(f"landing page {body.domain}/{body.slug} already exists")

        page = LandingPage(
            source=body.source,
            branch_id=body.branch_id,
            title=body.title,
            domain=body.domain.lower(),
            slug=body.slug.strip("/"),
            language=body.language,
            ta=body.ta,
            clarity_project_id=body.clarity_project_id,
            notes=body.notes,
            status=STATUS_DRAFT if body.source == SOURCE_MANAGED else "DISCOVERED",
            created_by=current_user.id,
            is_active=True,
        )
        db.add(page)
        db.commit()
        db.refresh(page)
        return _api(_serialize_page(page))
    except ValueError as e:
        return _api(error=str(e))
    except Exception as e:
        db.rollback()
        return _api(error=str(e))


@router.get("/landing-pages/{page_id}")
def get_page(
    page_id: str,
    current_user: User = Depends(require_section("landing_pages", "view")),
    db: Session = Depends(get_db),
):
    page = db.query(LandingPage).filter(LandingPage.id == page_id).one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="not found")
    return _api(_serialize_page(page, include_version=True, db=db))


@router.patch("/landing-pages/{page_id}")
def update_page(
    page_id: str,
    body: UpdatePageReq,
    current_user: User = Depends(require_section("landing_pages", "edit")),
    db: Session = Depends(get_db),
):
    page = db.query(LandingPage).filter(LandingPage.id == page_id).one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        if body.title is not None:
            page.title = body.title
        if body.domain is not None:
            page.domain = body.domain.lower()
        if body.slug is not None:
            page.slug = body.slug.strip("/")
        if body.language is not None:
            page.language = body.language
        if body.ta is not None:
            page.ta = body.ta
        if body.branch_id is not None:
            page.branch_id = body.branch_id
        if body.clarity_project_id is not None:
            page.clarity_project_id = body.clarity_project_id
        if body.notes is not None:
            page.notes = body.notes
        db.commit()
        db.refresh(page)
        return _api(_serialize_page(page))
    except Exception as e:
        db.rollback()
        return _api(error=str(e))


@router.delete("/landing-pages/{page_id}")
def archive_page(
    page_id: str,
    current_user: User = Depends(require_section("landing_pages", "edit")),
    db: Session = Depends(get_db),
):
    """Soft delete: set is_active=False and status=ARCHIVED."""
    page = db.query(LandingPage).filter(LandingPage.id == page_id).one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="not found")
    page.is_active = False
    page.status = STATUS_ARCHIVED
    db.commit()
    return _api({"id": page.id, "status": page.status})


# ────────────────────────── versions (managed) ──────────────────────────────


@router.post("/landing-pages/{page_id}/versions")
def create_page_version(
    page_id: str,
    body: CreateVersionReq,
    current_user: User = Depends(require_section("landing_pages", "edit")),
    db: Session = Depends(get_db),
):
    page = db.query(LandingPage).filter(LandingPage.id == page_id).one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        v = create_version(
            db,
            landing_page_id=page_id,
            content=body.content,
            created_by=current_user.id,
            change_note=body.change_note,
        )
        db.commit()
        return _api({
            "id": v.id,
            "version_num": v.version_num,
            "created_at": v.created_at.isoformat(),
            "change_note": v.change_note,
        })
    except ValueError as e:
        return _api(error=str(e))
    except Exception as e:
        db.rollback()
        return _api(error=str(e))


@router.get("/landing-pages/{page_id}/versions")
def list_page_versions(
    page_id: str,
    current_user: User = Depends(require_section("landing_pages", "view")),
    db: Session = Depends(get_db),
):
    page = db.query(LandingPage).filter(LandingPage.id == page_id).one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="not found")
    rows = (
        db.query(LandingPageVersion)
        .filter(LandingPageVersion.landing_page_id == page_id)
        .order_by(LandingPageVersion.version_num.desc())
        .all()
    )
    current_id = page.current_version_id
    return _api([
        {
            "id": v.id,
            "version_num": v.version_num,
            "change_note": v.change_note,
            "created_by": v.created_by,
            "created_at": v.created_at.isoformat(),
            "published_at": v.published_at.isoformat() if v.published_at else None,
            "is_current": v.id == current_id,
        }
        for v in rows
    ])


@router.post("/landing-pages/{page_id}/publish")
def publish_page(
    page_id: str,
    version_id: str = Query(...),
    current_user: User = Depends(require_section("landing_pages", "edit")),
    db: Session = Depends(get_db),
):
    try:
        page = publish_version(db, version_id=version_id, actor_user_id=current_user.id)
        db.commit()
        return _api(_serialize_page(page))
    except (ValueError, PermissionError) as e:
        return _api(error=str(e))
    except Exception as e:
        db.rollback()
        return _api(error=str(e))


# ────────────────────────── ad-links ────────────────────────────────────────


@router.post("/landing-pages/{page_id}/ad-links")
def link_ad_to_page(
    page_id: str,
    body: LinkAdReq,
    current_user: User = Depends(require_section("landing_pages", "edit")),
    db: Session = Depends(get_db),
):
    page = db.query(LandingPage).filter(LandingPage.id == page_id).one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        n = normalize_url(body.destination_url)
        now = datetime.now(timezone.utc)
        link = LandingPageAdLink(
            landing_page_id=page_id,
            platform=body.platform,
            campaign_id=body.campaign_id,
            ad_id=body.ad_id,
            asset_group_id=body.asset_group_id,
            destination_url=body.destination_url,
            utm_source=(n.utm.get("utm_source") if n else None),
            utm_medium=(n.utm.get("utm_medium") if n else None),
            utm_campaign=(n.utm.get("utm_campaign") if n else None),
            utm_content=(n.utm.get("utm_content") if n else None),
            utm_term=(n.utm.get("utm_term") if n else None),
            discovered_at=now,
            last_seen_at=now,
        )
        db.add(link)
        db.commit()
        return _api({"id": link.id})
    except Exception as e:
        db.rollback()
        return _api(error=str(e))


@router.get("/landing-pages/{page_id}/ad-links")
def list_ad_links(
    page_id: str,
    current_user: User = Depends(require_section("landing_pages", "view")),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(LandingPageAdLink)
        .filter(LandingPageAdLink.landing_page_id == page_id)
        .order_by(LandingPageAdLink.last_seen_at.desc())
        .all()
    )
    return _api([
        {
            "id": r.id,
            "platform": r.platform,
            "campaign_id": r.campaign_id,
            "ad_id": r.ad_id,
            "asset_group_id": r.asset_group_id,
            "destination_url": r.destination_url,
            "utm_source": r.utm_source,
            "utm_medium": r.utm_medium,
            "utm_campaign": r.utm_campaign,
            "utm_content": r.utm_content,
            "utm_term": r.utm_term,
            "last_seen_at": r.last_seen_at.isoformat(),
        }
        for r in rows
    ])


@router.post("/landing-pages/{page_id}/generate-url")
def generate_ad_url(
    page_id: str,
    body: GenerateUrlReq,
    current_user: User = Depends(require_section("landing_pages", "view")),
    db: Session = Depends(get_db),
):
    """Return a tagged URL to paste into the ad creative's destination field."""
    page = db.query(LandingPage).filter(LandingPage.id == page_id).one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="not found")
    base = f"https://{page.domain}/{page.slug}" if page.slug else f"https://{page.domain}"
    utms = {
        "utm_source": body.utm_source or "",
        "utm_medium": body.utm_medium or "",
        "utm_campaign": body.utm_campaign or "",
        "utm_content": body.utm_content or "",
        "utm_term": body.utm_term or "",
    }
    url = build_url_with_utms(base, utms)
    return _api({"url": url})


# ────────────────────────── metrics ─────────────────────────────────────────


@router.get("/landing-pages/{page_id}/metrics")
def page_metrics(
    page_id: str,
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    current_user: User = Depends(require_section("landing_pages", "view")),
    db: Session = Depends(get_db),
):
    page = db.query(LandingPage).filter(LandingPage.id == page_id).one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        df = date.fromisoformat(date_from) if date_from else date.today() - timedelta(days=7)
        dt = date.fromisoformat(date_to) if date_to else date.today()
        return _api(rollup_metrics(db, landing_page_id=page_id, date_from=df, date_to=dt))
    except ValueError as e:
        return _api(error=str(e))
    except Exception as e:
        return _api(error=str(e))


@router.get("/landing-pages/{page_id}/metrics/by-utm")
def page_metrics_by_utm(
    page_id: str,
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    current_user: User = Depends(require_section("landing_pages", "view")),
    db: Session = Depends(get_db),
):
    """Break down Clarity metrics by UTM source/campaign/content."""
    try:
        df = date.fromisoformat(date_from) if date_from else date.today() - timedelta(days=7)
        dt = date.fromisoformat(date_to) if date_to else date.today()
        rows = (
            db.query(
                LandingPageClaritySnapshot.utm_source,
                LandingPageClaritySnapshot.utm_campaign,
                LandingPageClaritySnapshot.utm_content,
                func.sum(LandingPageClaritySnapshot.sessions).label("sessions"),
                func.sum(LandingPageClaritySnapshot.distinct_users).label("users"),
                func.avg(LandingPageClaritySnapshot.avg_scroll_depth).label("scroll"),
                func.sum(LandingPageClaritySnapshot.rage_clicks).label("rage"),
                func.sum(LandingPageClaritySnapshot.dead_clicks).label("dead"),
                func.sum(LandingPageClaritySnapshot.quickback_clicks).label("qback"),
                func.sum(LandingPageClaritySnapshot.total_time_sec).label("total_time"),
                func.sum(LandingPageClaritySnapshot.active_time_sec).label("active_time"),
            )
            .filter(
                LandingPageClaritySnapshot.landing_page_id == page_id,
                LandingPageClaritySnapshot.date >= df,
                LandingPageClaritySnapshot.date <= dt,
                # Exclude aggregate NULL rows — we want the per-UTM breakdown
                LandingPageClaritySnapshot.utm_source.isnot(None),
            )
            .group_by(
                LandingPageClaritySnapshot.utm_source,
                LandingPageClaritySnapshot.utm_campaign,
                LandingPageClaritySnapshot.utm_content,
            )
            .order_by(func.sum(LandingPageClaritySnapshot.sessions).desc())
            .all()
        )
        return _api([
            {
                "utm_source": r.utm_source,
                "utm_campaign": r.utm_campaign,
                "utm_content": r.utm_content,
                "sessions": int(r.sessions or 0),
                "distinct_users": int(r.users or 0),
                "avg_scroll_depth": float(r.scroll) if r.scroll is not None else None,
                "rage_clicks": int(r.rage or 0),
                "dead_clicks": int(r.dead or 0),
                "quickback_clicks": int(r.qback or 0),
                "total_time_sec": int(r.total_time or 0),
                "active_time_sec": int(r.active_time or 0),
            }
            for r in rows
        ])
    except ValueError as e:
        return _api(error=str(e))
    except Exception as e:
        return _api(error=str(e))


# ────────────────────────── import ──────────────────────────────────────────


@router.post("/landing-pages/import-from-ads")
def import_pages_from_ads(
    current_user: User = Depends(require_section("landing_pages", "edit")),
    db: Session = Depends(get_db),
):
    """One-click bootstrap: scan all existing ads for destination URLs and
    create `external` landing pages + ad-link rows."""
    try:
        summary = import_from_ads(db)
        return _api(summary)
    except Exception as e:
        db.rollback()
        return _api(error=str(e))
