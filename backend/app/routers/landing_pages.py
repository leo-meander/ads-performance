"""Landing Pages router — CRUD, versions, approvals, metrics, ad-links, import."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
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
