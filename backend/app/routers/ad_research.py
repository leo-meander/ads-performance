"""Spy Ads: search, track, save, and analyze competitor Meta Ads."""

import logging
import uuid
from datetime import datetime, timezone

from anthropic import Anthropic
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies.auth import require_page
from app.models.account import AdAccount
from app.models.spy_analysis_report import SpyAnalysisReport
from app.models.spy_competitor_ad import SpyCompetitorAd, SpyCreativeGroup
from app.models.spy_saved_ad import SpySavedAd
from app.models.spy_tracked_page import SpyTrackedPage
from app.models.user import User
from app.services.ad_library import (
    AdLibraryError,
    active_provider_name,
    fetch_page_ads,
    looks_like_page_id,
    provider_status,
    resolve_page,
    search_ads,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _resolve_meta_token(db: Session) -> str | None:
    """Token for the Ad Library API comes from any active Meta account in the
    DB (same source as the sync engine). Returns None to let the client fall
    back to the env var."""
    account = (
        db.query(AdAccount)
        .filter(
            AdAccount.platform == "meta",
            AdAccount.is_active.is_(True),
            AdAccount.access_token_enc.isnot(None),
        )
        .first()
    )
    return account.access_token_enc if account else None


# ── Search ─────────────────────────────────────────────────


@router.get("/spy-ads/provider")
def get_provider_info(
    current_user: User = Depends(require_page("ad_research")),
):
    """What source is answering, and whether it can see commercial ads.

    The page shows this up front because the two sources differ in coverage,
    not just speed: an empty grid means something completely different on
    meta_official than on apify.
    """
    try:
        return _api_response(provider_status())
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/spy-ads/search")
def search_ad_library(
    q: str = "",
    country: str = "ALL",
    active_status: str = "ACTIVE",
    platform: str = "ALL",
    media_type: str = "ALL",
    page_id: str = "",
    limit: int = Query(default=25, le=100),
    after: str | None = None,
    provider: str | None = None,
    current_user: User = Depends(require_page("ad_research")),
    db: Session = Depends(get_db),
):
    name = active_provider_name(provider)
    try:
        page = search_ads(
            provider=name,
            query=q,
            country=country,
            active_status=active_status,
            publisher_platform=platform,
            media_type=media_type,
            page_id=page_id,
            limit=limit,
            after=after,
            access_token=_resolve_meta_token(db) if name == "meta_official" else None,
        )
        return _api_response({
            "ads": [a.to_dict() for a in page.ads],
            "paging": {"after": page.after},
            "provider": page.source or name,
            "coverage_note": page.coverage_note,
        })
    except AdLibraryError as e:
        logger.warning("Ad Library search failed [%s]: %s", name, e)
        return _api_response(error=str(e))
    except Exception as e:
        logger.exception("Ad Library search crashed [%s]", name)
        return _api_response(error=str(e))


# ── Tracked Pages (Competitors) ────────────────────────────


class TrackedPageCreate(BaseModel):
    # Either is enough: `page_url` is whatever the user pasted (facebook.com
    # page, instagram.com profile, or a bare id) and `page_id` is the numeric
    # id the Search tab already knows. Anything non-numeric arriving in
    # `page_id` is resolved rather than stored, because the Ad Library
    # answers a slug with silence, not an error.
    page_id: str = ""
    page_url: str = ""
    page_name: str = ""
    category: str | None = None
    country: str | None = None
    notes: str | None = None


class PageResolveRequest(BaseModel):
    page_url: str
    country: str | None = None


class TrackedPageUpdate(BaseModel):
    page_name: str | None = None
    category: str | None = None
    country: str | None = None
    notes: str | None = None


@router.get("/spy-ads/tracked-pages")
def list_tracked_pages(
    category: str | None = None,
    current_user: User = Depends(require_page("ad_research")),
    db: Session = Depends(get_db),
):
    try:
        q = db.query(SpyTrackedPage).filter(SpyTrackedPage.is_active.is_(True))
        if category:
            q = q.filter(SpyTrackedPage.category == category)
        rows = q.order_by(SpyTrackedPage.category, SpyTrackedPage.page_name).all()
        result = [
            {
                "id": r.id, "page_id": r.page_id, "page_name": r.page_name,
                "category": r.category, "country": r.country, "notes": r.notes,
                "last_checked_at": r.last_checked_at.isoformat() if r.last_checked_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
        return _api_response(result)
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/spy-ads/resolve-page")
def resolve_competitor_page(
    body: PageResolveRequest,
    current_user: User = Depends(require_page("ad_research", "edit")),
):
    """Look up the numeric Page ID behind a pasted URL, before anything is saved.

    Separate from the create call so the dialog can show WHICH page it found
    (and, when the handle is ambiguous, the candidates) instead of committing
    a competitor the user never actually confirmed.
    """
    try:
        result = resolve_page(body.page_url, country=body.country or "ALL")
        return _api_response(result.to_dict())
    except AdLibraryError as e:
        return _api_response(error=str(e))
    except Exception as e:
        logger.exception("[spy-resolve] failed for %r", body.page_url)
        return _api_response(error=str(e))


@router.post("/spy-ads/tracked-pages")
def create_tracked_page(
    body: TrackedPageCreate,
    current_user: User = Depends(require_page("ad_research", "edit")),
    db: Session = Depends(get_db),
):
    try:
        # An id the caller already resolved wins over the pasted URL, so
        # confirming in the dialog does not buy a second lookup.
        raw = (body.page_id or "").strip()
        if not looks_like_page_id(raw):
            raw = (body.page_url or raw).strip()
        if not raw:
            return _api_response(
                error="Paste a Facebook page URL, an Instagram URL, or a Page ID."
            )

        page_id = raw
        page_name = (body.page_name or "").strip()
        resolution = None

        # A slug stored as-is crawls forever and returns nothing, so resolve
        # here too -- not only in the dialog -- and refuse if it stays unclear.
        if not looks_like_page_id(raw):
            resolution = resolve_page(raw, country=body.country or "ALL")
            if not resolution.resolved:
                return _api_response(
                    data={"candidates": [c.to_dict() for c in resolution.candidates]},
                    error=resolution.note or f"Could not find a Page ID for '{raw}'.",
                )
            page_id = resolution.page_id
            page_name = page_name or resolution.page_name

        existing = db.query(SpyTrackedPage).filter(
            SpyTrackedPage.page_id == page_id,
            SpyTrackedPage.is_active.is_(True),
        ).first()
        if existing:
            return _api_response(
                error=f"{existing.page_name} (ID {page_id}) is already tracked."
            )

        # A page tracked before, then removed: revive the row so its ad
        # history reattaches instead of colliding with the unique page_id.
        retired = db.query(SpyTrackedPage).filter(
            SpyTrackedPage.page_id == page_id
        ).first()
        row = retired or SpyTrackedPage(page_id=page_id)
        row.page_name = page_name or page_id
        row.category = body.category
        row.country = body.country
        row.notes = body.notes
        row.is_active = True
        if retired is None:
            db.add(row)
        db.commit()
        db.refresh(row)
        return _api_response({
            "id": row.id,
            "page_id": row.page_id,
            "page_name": row.page_name,
            "resolution": resolution.to_dict() if resolution else None,
        })
    except AdLibraryError as e:
        db.rollback()
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.patch("/spy-ads/tracked-pages/{page_db_id}")
def update_tracked_page(
    page_db_id: str,
    body: TrackedPageUpdate,
    current_user: User = Depends(require_page("ad_research", "edit")),
    db: Session = Depends(get_db),
):
    try:
        row = db.query(SpyTrackedPage).filter(SpyTrackedPage.id == page_db_id).first()
        if not row:
            return _api_response(error="Tracked page not found.")
        if body.page_name is not None:
            row.page_name = body.page_name
        if body.category is not None:
            row.category = body.category
        if body.country is not None:
            row.country = body.country
        if body.notes is not None:
            row.notes = body.notes
        db.commit()
        return _api_response({"id": row.id, "page_name": row.page_name})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.delete("/spy-ads/tracked-pages/{page_db_id}")
def delete_tracked_page(
    page_db_id: str,
    current_user: User = Depends(require_page("ad_research", "edit")),
    db: Session = Depends(get_db),
):
    try:
        row = db.query(SpyTrackedPage).filter(SpyTrackedPage.id == page_db_id).first()
        if not row:
            return _api_response(error="Tracked page not found.")
        row.is_active = False
        db.commit()
        return _api_response({"deleted": True})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/spy-ads/tracked-pages/{page_db_id}/ads")
def get_tracked_page_ads(
    page_db_id: str,
    limit: int = Query(default=25, le=50),
    active_status: str = "ACTIVE",
    after: str | None = None,
    current_user: User = Depends(require_page("ad_research")),
    db: Session = Depends(get_db),
):
    try:
        row = db.query(SpyTrackedPage).filter(SpyTrackedPage.id == page_db_id).first()
        if not row:
            return _api_response(error="Tracked page not found.")

        name = active_provider_name()
        page = fetch_page_ads(
            provider=name,
            page_id=row.page_id,
            country=row.country or "ALL",
            active_status=active_status,
            limit=limit,
            after=after,
            access_token=_resolve_meta_token(db) if name == "meta_official" else None,
        )

        # A live view is also an observation — fold it into the ledger so
        # browsing a competitor extends their ads' first/last-seen for free.
        from app.services.spy_monitor import upsert_ads
        upsert_ads(db, page.ads, tracked_page=row)

        row.last_checked_at = datetime.now(timezone.utc)
        row.last_crawl_ad_count = len(page.ads)
        row.last_crawl_error = page.coverage_note
        db.commit()

        return _api_response({
            "ads": [a.to_dict() for a in page.ads],
            "paging": {"after": page.after},
            "provider": page.source or name,
            "coverage_note": page.coverage_note,
        })
    except AdLibraryError as e:
        db.rollback()
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        logger.exception("Tracked-page ad fetch crashed")
        return _api_response(error=str(e))


# ── Saved Ads ──────────────────────────────────────────────


class SaveAdBody(BaseModel):
    ad_archive_id: str
    page_id: str | None = None
    page_name: str | None = None
    ad_creative_bodies: list | None = None
    ad_creative_link_titles: list | None = None
    ad_creative_link_captions: list | None = None
    ad_snapshot_url: str | None = None
    publisher_platforms: list | None = None
    ad_delivery_start_time: str | None = None
    ad_delivery_stop_time: str | None = None
    country: str | None = None
    media_type: str | None = None
    tags: list[str] | None = None
    notes: str | None = None
    collection: str | None = None
    raw_data: dict | None = None


class UpdateSavedAdBody(BaseModel):
    tags: list[str] | None = None
    notes: str | None = None
    collection: str | None = None


class BulkTagBody(BaseModel):
    ad_ids: list[str]
    tags: list[str]


@router.get("/spy-ads/saved-ads")
def list_saved_ads(
    collection: str | None = None,
    tags: str | None = None,
    page_id: str | None = None,
    country: str | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    current_user: User = Depends(require_page("ad_research")),
    db: Session = Depends(get_db),
):
    try:
        q = db.query(SpySavedAd).filter(SpySavedAd.is_active.is_(True))
        if collection:
            q = q.filter(SpySavedAd.collection == collection)
        if page_id:
            q = q.filter(SpySavedAd.page_id == page_id)
        if country:
            q = q.filter(SpySavedAd.country == country)

        total = q.count()

        # Sort
        sort_col = getattr(SpySavedAd, sort_by, SpySavedAd.created_at)
        q = q.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())
        rows = q.offset(offset).limit(limit).all()

        items = []
        for r in rows:
            days_active = 0
            if r.ad_delivery_start_time:
                end = r.ad_delivery_stop_time or datetime.now(timezone.utc)
                days_active = max(0, (end.date() - r.ad_delivery_start_time.date()).days)

            items.append({
                "id": r.id, "ad_archive_id": r.ad_archive_id,
                "page_id": r.page_id, "page_name": r.page_name,
                "ad_creative_bodies": r.ad_creative_bodies or [],
                "ad_creative_link_titles": r.ad_creative_link_titles or [],
                "ad_creative_link_captions": r.ad_creative_link_captions or [],
                "ad_snapshot_url": r.ad_snapshot_url,
                "publisher_platforms": r.publisher_platforms or [],
                "ad_delivery_start_time": r.ad_delivery_start_time.isoformat() if r.ad_delivery_start_time else None,
                "ad_delivery_stop_time": r.ad_delivery_stop_time.isoformat() if r.ad_delivery_stop_time else None,
                "days_active": days_active,
                "is_active_ad": r.ad_delivery_stop_time is None,
                "country": r.country, "media_type": r.media_type,
                "tags": r.tags or [], "notes": r.notes, "collection": r.collection,
                "created_at": r.created_at.isoformat(),
            })

        return _api_response({"items": items, "total": total})
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/spy-ads/saved-ads")
def save_ad(
    body: SaveAdBody,
    current_user: User = Depends(require_page("ad_research", "edit")),
    db: Session = Depends(get_db),
):
    try:
        existing = db.query(SpySavedAd).filter(
            SpySavedAd.ad_archive_id == body.ad_archive_id,
            SpySavedAd.is_active.is_(True),
        ).first()

        start_dt = None
        stop_dt = None
        if body.ad_delivery_start_time:
            try:
                start_dt = datetime.fromisoformat(body.ad_delivery_start_time.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass
        if body.ad_delivery_stop_time:
            try:
                stop_dt = datetime.fromisoformat(body.ad_delivery_stop_time.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        if existing:
            # Upsert: update delivery dates and metadata
            existing.ad_delivery_start_time = start_dt or existing.ad_delivery_start_time
            existing.ad_delivery_stop_time = stop_dt
            if body.tags is not None:
                existing.tags = body.tags
            if body.notes is not None:
                existing.notes = body.notes
            if body.collection is not None:
                existing.collection = body.collection
            if body.raw_data:
                existing.raw_data = body.raw_data
            db.commit()
            return _api_response({"id": existing.id, "ad_archive_id": existing.ad_archive_id, "updated": True})

        row = SpySavedAd(
            ad_archive_id=body.ad_archive_id,
            page_id=body.page_id,
            page_name=body.page_name,
            ad_creative_bodies=body.ad_creative_bodies,
            ad_creative_link_titles=body.ad_creative_link_titles,
            ad_creative_link_captions=body.ad_creative_link_captions,
            ad_snapshot_url=body.ad_snapshot_url,
            publisher_platforms=body.publisher_platforms,
            ad_delivery_start_time=start_dt,
            ad_delivery_stop_time=stop_dt,
            country=body.country,
            media_type=body.media_type,
            tags=body.tags or [],
            notes=body.notes,
            collection=body.collection,
            raw_data=body.raw_data,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _api_response({"id": row.id, "ad_archive_id": row.ad_archive_id, "updated": False})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.patch("/spy-ads/saved-ads/{ad_db_id}")
def update_saved_ad(
    ad_db_id: str,
    body: UpdateSavedAdBody,
    current_user: User = Depends(require_page("ad_research", "edit")),
    db: Session = Depends(get_db),
):
    try:
        row = db.query(SpySavedAd).filter(SpySavedAd.id == ad_db_id).first()
        if not row:
            return _api_response(error="Saved ad not found.")
        if body.tags is not None:
            row.tags = body.tags
        if body.notes is not None:
            row.notes = body.notes
        if body.collection is not None:
            row.collection = body.collection
        db.commit()
        return _api_response({"id": row.id})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.delete("/spy-ads/saved-ads/{ad_db_id}")
def delete_saved_ad(
    ad_db_id: str,
    current_user: User = Depends(require_page("ad_research", "edit")),
    db: Session = Depends(get_db),
):
    try:
        row = db.query(SpySavedAd).filter(SpySavedAd.id == ad_db_id).first()
        if not row:
            return _api_response(error="Saved ad not found.")
        row.is_active = False
        db.commit()
        return _api_response({"deleted": True})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/spy-ads/saved-ads/collections")
def list_collections(
    current_user: User = Depends(require_page("ad_research")),
    db: Session = Depends(get_db),
):
    try:
        rows = (
            db.query(SpySavedAd.collection, func.count(SpySavedAd.id))
            .filter(SpySavedAd.is_active.is_(True), SpySavedAd.collection.isnot(None))
            .group_by(SpySavedAd.collection)
            .all()
        )
        result = [{"name": name, "count": count} for name, count in rows if name]
        return _api_response(result)
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/spy-ads/saved-ads/bulk-tag")
def bulk_tag(
    body: BulkTagBody,
    current_user: User = Depends(require_page("ad_research", "edit")),
    db: Session = Depends(get_db),
):
    try:
        rows = db.query(SpySavedAd).filter(SpySavedAd.id.in_(body.ad_ids)).all()
        for row in rows:
            existing_tags = row.tags or []
            merged = list(set(existing_tags + body.tags))
            row.tags = merged
        db.commit()
        return _api_response({"updated": len(rows)})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


# ── AI Analysis ────────────────────────────────────────────


ANALYSIS_SYSTEM_PROMPT = """You are an expert ad strategist analyzing competitor Meta Ads for MEANDER Group — a hospitality company with hotel branches in Saigon, Taipei, and Osaka.

Analyze the provided ads and deliver actionable insights. Focus on:
- **Ad copy patterns**: hooks, CTAs, emotional triggers, urgency language
- **Creative strategy**: what formats work (video/image/carousel), visual themes
- **Duration signal**: ads running 30+ days are likely profitable — highlight these
- **Targeting clues**: language, country targeting, audience signals
- **Opportunities**: gaps competitors miss that MEANDER could exploit

Be specific with examples from the ads. Write in Vietnamese if the ads are Vietnamese, otherwise English.
Provide structured analysis with clear headers and bullet points."""

ANALYSIS_TYPES = {
    "pattern_analysis": "Analyze common patterns across these ads: hooks, CTAs, copy structure, creative formats, and targeting strategies.",
    "competitor_deep_dive": "Deep-dive into this competitor's ad strategy: what angles they use, how they position their brand, pricing strategy, and what we can learn.",
    "creative_trends": "Identify creative trends: what formats, visual styles, and messaging approaches are being used. Highlight what's working (long-running ads) vs what's being tested.",
}


class AnalyzeBody(BaseModel):
    ad_ids: list[str]
    analysis_type: str = "pattern_analysis"
    custom_prompt: str | None = None


@router.post("/spy-ads/analyze")
def analyze_ads(
    body: AnalyzeBody,
    current_user: User = Depends(require_page("ad_research", "edit")),
    db: Session = Depends(get_db),
):
    try:
        ads = db.query(SpySavedAd).filter(SpySavedAd.id.in_(body.ad_ids), SpySavedAd.is_active.is_(True)).all()
        if not ads:
            return _api_response(error="No saved ads found with the provided IDs.")

        # Build context from saved ads
        ad_texts = []
        for i, ad in enumerate(ads, 1):
            days_active = 0
            if ad.ad_delivery_start_time:
                end = ad.ad_delivery_stop_time or datetime.now(timezone.utc)
                days_active = max(0, (end.date() - ad.ad_delivery_start_time.date()).days)

            bodies = ad.ad_creative_bodies or []
            titles = ad.ad_creative_link_titles or []
            platforms = ad.publisher_platforms or []

            ad_texts.append(
                f"### Ad #{i} — {ad.page_name or 'Unknown'}\n"
                f"- Archive ID: {ad.ad_archive_id}\n"
                f"- Platforms: {', '.join(platforms)}\n"
                f"- Country: {ad.country or 'Unknown'}\n"
                f"- Days Active: {days_active} {'(still running)' if not ad.ad_delivery_stop_time else '(stopped)'}\n"
                f"- Body text: {'; '.join(bodies[:3]) if bodies else 'N/A'}\n"
                f"- Link titles: {'; '.join(titles[:3]) if titles else 'N/A'}\n"
            )

        context = f"## Competitor Ads ({len(ads)} total)\n\n" + "\n".join(ad_texts)

        type_prompt = ANALYSIS_TYPES.get(body.analysis_type, ANALYSIS_TYPES["pattern_analysis"])
        user_prompt = body.custom_prompt or type_prompt

        # Generate title
        title = f"{body.analysis_type.replace('_', ' ').title()} — {len(ads)} ads"

        # Create report row (will update result after streaming)
        report = SpyAnalysisReport(
            title=title,
            analysis_type=body.analysis_type,
            input_ad_ids=body.ad_ids,
            input_params={"custom_prompt": body.custom_prompt},
            result_markdown="",
            model_used="claude-sonnet-5",
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        report_id = report.id

        def stream_and_save():
            client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            full_text = []
            try:
                with client.messages.stream(
                    model="claude-sonnet-5",
                    max_tokens=4096,
                    system=ANALYSIS_SYSTEM_PROMPT,
                    messages=[
                        {"role": "user", "content": f"{context}\n\n---\n\n{user_prompt}"},
                    ],
                ) as stream:
                    for text in stream.text_stream:
                        full_text.append(text)
                        yield text
            finally:
                # Save the complete result to db
                from app.database import SessionLocal
                save_db = SessionLocal()
                try:
                    r = save_db.query(SpyAnalysisReport).filter(SpyAnalysisReport.id == report_id).first()
                    if r:
                        r.result_markdown = "".join(full_text)
                        save_db.commit()
                finally:
                    save_db.close()

        return StreamingResponse(stream_and_save(), media_type="text/event-stream")
    except Exception as e:
        logger.error("Analysis failed: %s", e)
        return _api_response(error=str(e))


@router.get("/spy-ads/reports")
def list_reports(
    limit: int = Query(default=20, le=100),
    offset: int = 0,
    current_user: User = Depends(require_page("ad_research")),
    db: Session = Depends(get_db),
):
    try:
        q = db.query(SpyAnalysisReport).filter(SpyAnalysisReport.is_active.is_(True))
        total = q.count()
        rows = q.order_by(SpyAnalysisReport.created_at.desc()).offset(offset).limit(limit).all()
        items = [
            {
                "id": r.id, "title": r.title, "analysis_type": r.analysis_type,
                "input_ad_ids": r.input_ad_ids or [],
                "model_used": r.model_used,
                "created_at": r.created_at.isoformat(),
                "has_result": bool(r.result_markdown),
            }
            for r in rows
        ]
        return _api_response({"items": items, "total": total})
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/spy-ads/reports/{report_id}")
def get_report(
    report_id: str,
    current_user: User = Depends(require_page("ad_research")),
    db: Session = Depends(get_db),
):
    try:
        r = db.query(SpyAnalysisReport).filter(SpyAnalysisReport.id == report_id).first()
        if not r:
            return _api_response(error="Report not found.")
        return _api_response({
            "id": r.id, "title": r.title, "analysis_type": r.analysis_type,
            "input_ad_ids": r.input_ad_ids or [],
            "input_params": r.input_params,
            "result_markdown": r.result_markdown,
            "model_used": r.model_used,
            "created_at": r.created_at.isoformat(),
        })
    except Exception as e:
        return _api_response(error=str(e))


# ── Stats ──────────────────────────────────────────────────


@router.get("/spy-ads/stats")
def get_stats(
    current_user: User = Depends(require_page("ad_research")),
    db: Session = Depends(get_db),
):
    try:
        total_saved = db.query(SpySavedAd).filter(SpySavedAd.is_active.is_(True)).count()
        total_pages = db.query(SpyTrackedPage).filter(SpyTrackedPage.is_active.is_(True)).count()
        total_reports = db.query(SpyAnalysisReport).filter(SpyAnalysisReport.is_active.is_(True)).count()

        collections = (
            db.query(SpySavedAd.collection, func.count(SpySavedAd.id))
            .filter(SpySavedAd.is_active.is_(True), SpySavedAd.collection.isnot(None))
            .group_by(SpySavedAd.collection)
            .all()
        )

        return _api_response({
            "total_saved": total_saved,
            "total_tracked_pages": total_pages,
            "total_reports": total_reports,
            "collections": [{"name": n, "count": c} for n, c in collections if n],
        })
    except Exception as e:
        return _api_response(error=str(e))


# -- Competitor monitor (longevity ledger) ------------------------------
#
# Search answers "what is running right now". The monitor answers the harder
# question: what has KEPT running. That only comes from repeated observation,
# so these endpoints read `spy_competitor_ads` rather than hitting a provider.


def _competitor_ad_dict(r: SpyCompetitorAd) -> dict:
    return {
        "id": r.id,
        "ad_archive_id": r.ad_archive_id,
        "tracked_page_id": r.tracked_page_id,
        "page_id": r.page_id,
        "page_name": r.page_name,
        "country": r.country,
        "ad_creative_bodies": r.ad_creative_bodies or [],
        "ad_creative_link_titles": r.ad_creative_link_titles or [],
        "ad_creative_link_captions": r.ad_creative_link_captions or [],
        "cta_text": r.cta_text,
        "link_url": r.link_url,
        "media_type": r.media_type,
        "preview_image_url": r.preview_image_url,
        "ad_snapshot_url": r.ad_snapshot_url,
        "publisher_platforms": r.publisher_platforms or [],
        "ad_delivery_start_time": (
            r.ad_delivery_start_time.isoformat() if r.ad_delivery_start_time else None
        ),
        "ad_delivery_stop_time": (
            r.ad_delivery_stop_time.isoformat() if r.ad_delivery_stop_time else None
        ),
        "days_running": r.days_running or 0,
        "first_seen_at": r.first_seen_at.isoformat() if r.first_seen_at else None,
        "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
        "seen_count": r.seen_count or 0,
        "days_observed": r.days_observed or 0,
        "is_currently_active": bool(r.is_currently_active),
        "disappeared_at": r.disappeared_at.isoformat() if r.disappeared_at else None,
        "creative_group_key": r.creative_group_key,
        "ai_breakdown": r.ai_breakdown,
        "source": r.source,
    }


@router.get("/spy-ads/monitor/ads")
def list_monitored_ads(
    min_days: int | None = None,
    status: str = "active",  # active | stopped | all
    page_id: str | None = None,
    country: str | None = None,
    media_type: str | None = None,
    has_breakdown: bool | None = None,
    sort_by: str = "days_running",
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    current_user: User = Depends(require_page("ad_research")),
    db: Session = Depends(get_db),
):
    """The longevity ranking - longest-running competitor ads first."""
    try:
        q = db.query(SpyCompetitorAd).filter(SpyCompetitorAd.is_active.is_(True))
        if min_days is not None:
            q = q.filter(SpyCompetitorAd.days_running >= min_days)
        if status == "active":
            q = q.filter(SpyCompetitorAd.is_currently_active.is_(True))
        elif status == "stopped":
            q = q.filter(SpyCompetitorAd.is_currently_active.is_(False))
        if page_id:
            q = q.filter(SpyCompetitorAd.page_id == page_id)
        if country:
            q = q.filter(SpyCompetitorAd.country == country.upper())
        if media_type:
            q = q.filter(SpyCompetitorAd.media_type == media_type)
        if has_breakdown is True:
            q = q.filter(SpyCompetitorAd.ai_breakdown.isnot(None))
        elif has_breakdown is False:
            q = q.filter(SpyCompetitorAd.ai_breakdown.is_(None))

        total = q.count()
        sort_col = {
            "days_running": SpyCompetitorAd.days_running,
            "days_observed": SpyCompetitorAd.days_observed,
            "first_seen_at": SpyCompetitorAd.first_seen_at,
            "last_seen_at": SpyCompetitorAd.last_seen_at,
            "seen_count": SpyCompetitorAd.seen_count,
        }.get(sort_by, SpyCompetitorAd.days_running)
        rows = q.order_by(sort_col.desc()).offset(offset).limit(limit).all()

        return _api_response({
            "items": [_competitor_ad_dict(r) for r in rows],
            "total": total,
            "long_running_days": settings.SPY_LONG_RUNNING_DAYS,
        })
    except Exception as e:
        logger.exception("monitor/ads failed")
        return _api_response(error=str(e))


@router.get("/spy-ads/monitor/groups")
def list_creative_groups(
    min_ads: int = 2,
    only_active: bool = True,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    current_user: User = Depends(require_page("ad_research")),
    db: Session = Depends(get_db),
):
    """Creative concepts - the same idea duplicated across ad ids.

    Defaults to groups of 2+ because a group of one is just an ad, and the
    whole point of this view is repetition.
    """
    try:
        q = db.query(SpyCreativeGroup).filter(
            SpyCreativeGroup.is_active.is_(True),
            SpyCreativeGroup.ad_count >= min_ads,
        )
        if only_active:
            q = q.filter(SpyCreativeGroup.is_still_active.is_(True))
        total = q.count()
        rows = (
            q.order_by(
                SpyCreativeGroup.ad_count.desc(),
                SpyCreativeGroup.max_days_running.desc(),
            )
            .offset(offset)
            .limit(limit)
            .all()
        )
        items = [
            {
                "id": g.id,
                "group_key": g.group_key,
                "label": g.label,
                "ad_count": g.ad_count,
                "active_ad_count": g.active_ad_count,
                "page_ids": g.page_ids or [],
                "page_names": g.page_names or [],
                "representative_ad_id": g.representative_ad_id,
                "preview_image_url": g.preview_image_url,
                "media_type": g.media_type,
                "first_seen_at": g.first_seen_at.isoformat() if g.first_seen_at else None,
                "last_seen_at": g.last_seen_at.isoformat() if g.last_seen_at else None,
                "max_days_running": g.max_days_running,
                "is_still_active": bool(g.is_still_active),
            }
            for g in rows
        ]
        return _api_response({"items": items, "total": total})
    except Exception as e:
        logger.exception("monitor/groups failed")
        return _api_response(error=str(e))


@router.get("/spy-ads/monitor/groups/{group_key}")
def get_creative_group(
    group_key: str,
    current_user: User = Depends(require_page("ad_research")),
    db: Session = Depends(get_db),
):
    try:
        group = (
            db.query(SpyCreativeGroup)
            .filter(SpyCreativeGroup.group_key == group_key)
            .first()
        )
        if not group:
            return _api_response(error="Creative group not found.")
        members = (
            db.query(SpyCompetitorAd)
            .filter(
                SpyCompetitorAd.creative_group_key == group_key,
                SpyCompetitorAd.is_active.is_(True),
            )
            .order_by(SpyCompetitorAd.days_running.desc())
            .all()
        )
        return _api_response({
            "group_key": group.group_key,
            "label": group.label,
            "ad_count": group.ad_count,
            "active_ad_count": group.active_ad_count,
            "page_names": group.page_names or [],
            "max_days_running": group.max_days_running,
            "first_seen_at": group.first_seen_at.isoformat() if group.first_seen_at else None,
            "last_seen_at": group.last_seen_at.isoformat() if group.last_seen_at else None,
            "is_still_active": bool(group.is_still_active),
            "ads": [_competitor_ad_dict(m) for m in members],
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/spy-ads/monitor/status")
def get_monitor_status(
    current_user: User = Depends(require_page("ad_research")),
    db: Session = Depends(get_db),
):
    """Per-page crawl roll call.

    A cron that returns 202 proves nothing about whether a competitor actually
    yielded ads, and a page silently returning zero looks exactly like one
    that stopped advertising. Surfacing `last_crawl_error` and the per-page ad
    count is what makes a broken page visible instead of invisible.
    """
    try:
        pages = (
            db.query(SpyTrackedPage)
            .filter(SpyTrackedPage.is_active.is_(True))
            .order_by(SpyTrackedPage.page_name)
            .all()
        )
        long_days = settings.SPY_LONG_RUNNING_DAYS
        base = db.query(SpyCompetitorAd).filter(SpyCompetitorAd.is_active.is_(True))
        total_ads = base.count()
        active_ads = base.filter(SpyCompetitorAd.is_currently_active.is_(True)).count()
        long_running = base.filter(
            SpyCompetitorAd.is_currently_active.is_(True),
            SpyCompetitorAd.days_running >= long_days,
        ).count()
        awaiting = base.filter(
            SpyCompetitorAd.days_running >= long_days,
            SpyCompetitorAd.ai_breakdown.is_(None),
        ).count()
        groups = (
            db.query(SpyCreativeGroup)
            .filter(SpyCreativeGroup.is_active.is_(True), SpyCreativeGroup.ad_count >= 2)
            .count()
        )

        return _api_response({
            "provider": provider_status(),
            "long_running_days": long_days,
            "totals": {
                "tracked_pages": len(pages),
                "ads_tracked": total_ads,
                "ads_active": active_ads,
                "long_running_active": long_running,
                "awaiting_breakdown": awaiting,
                "creative_groups": groups,
            },
            "pages": [
                {
                    "id": p.id,
                    "page_id": p.page_id,
                    "page_name": p.page_name,
                    "category": p.category,
                    "country": p.country,
                    "monitor_enabled": bool(p.monitor_enabled),
                    "last_checked_at": (
                        p.last_checked_at.isoformat() if p.last_checked_at else None
                    ),
                    "last_crawl_ad_count": p.last_crawl_ad_count,
                    "last_crawl_error": p.last_crawl_error,
                }
                for p in pages
            ],
        })
    except Exception as e:
        logger.exception("monitor/status failed")
        return _api_response(error=str(e))


class CrawlBody(BaseModel):
    page_db_id: str | None = None
    limit: int | None = None


@router.post("/spy-ads/monitor/crawl")
def trigger_crawl(
    body: CrawlBody,
    current_user: User = Depends(require_page("ad_research", "edit")),
    db: Session = Depends(get_db),
):
    """Crawl now. Synchronous so the user sees the roll call they triggered.

    One page takes an Apify run (tens of seconds); a sweep of a handful of
    competitors stays inside the ingress timeout. The cron path runs the same
    function in a background thread.
    """
    try:
        from app.services.spy_monitor import run_crawl
        result = run_crawl(db, page_db_id=body.page_db_id, limit=body.limit)
        return _api_response(result, error=result.get("error"))
    except Exception as e:
        logger.exception("monitor/crawl failed")
        return _api_response(error=str(e))


class BreakdownBody(BaseModel):
    limit: int | None = None
    min_days_running: int | None = None
    force: bool = False


@router.post("/spy-ads/monitor/breakdown")
def trigger_breakdown(
    body: BreakdownBody,
    current_user: User = Depends(require_page("ad_research", "edit")),
    db: Session = Depends(get_db),
):
    """Fill hook/angle/offer/USP/CTA/target on long-running ads."""
    try:
        from app.services.spy_intelligence import breakdown_ads
        result = breakdown_ads(
            db,
            limit=body.limit or settings.SPY_BREAKDOWN_BATCH,
            min_days_running=body.min_days_running,
            force=body.force,
        )
        return _api_response(result)
    except Exception as e:
        logger.exception("monitor/breakdown failed")
        return _api_response(error=str(e))


@router.get("/spy-ads/patterns")
def get_patterns(
    min_days: int | None = None,
    current_user: User = Depends(require_page("ad_research")),
    db: Session = Depends(get_db),
):
    """The pattern tally - counted in SQL, no model call, no cost."""
    try:
        from app.services.spy_intelligence import compute_tally
        return _api_response(compute_tally(db, min_days_running=min_days))
    except Exception as e:
        logger.exception("patterns failed")
        return _api_response(error=str(e))


class DigestBody(BaseModel):
    min_days_running: int | None = None


@router.post("/spy-ads/patterns/digest")
def create_pattern_digest(
    body: DigestBody,
    current_user: User = Depends(require_page("ad_research", "edit")),
    db: Session = Depends(get_db),
):
    """Interpret the tally into a MEANDER-facing recommendation."""
    try:
        from app.services.spy_intelligence import build_pattern_digest
        return _api_response(
            build_pattern_digest(db, min_days_running=body.min_days_running)
        )
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        logger.exception("patterns/digest failed")
        return _api_response(error=str(e))
