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
from app.models.spy_analysis_report import SpyAnalysisReport
from app.models.spy_saved_ad import SpySavedAd
from app.models.spy_tracked_page import SpyTrackedPage
from app.services.ad_library_client import fetch_page_ads, search_ads

logger = logging.getLogger(__name__)

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Search ─────────────────────────────────────────────────


@router.get("/spy-ads/search")
def search_ad_library(
    q: str = "",
    country: str = "ALL",
    active_status: str = "ACTIVE",
    platform: str = "ALL",
    media_type: str = "ALL",
    page_id: str = "",
    limit: int = Query(default=25, le=50),
    after: str | None = None,
):
    try:
        result = search_ads(
            query=q,
            country=country,
            active_status=active_status,
            publisher_platform=platform,
            media_type=media_type,
            search_page_ids=page_id,
            limit=limit,
            after=after,
        )
        return _api_response(result)
    except Exception as e:
        logger.error("Search failed: %s", e)
        return _api_response(error=str(e))


# ── Tracked Pages (Competitors) ────────────────────────────


class TrackedPageCreate(BaseModel):
    page_id: str
    page_name: str
    category: str | None = None
    country: str | None = None
    notes: str | None = None


class TrackedPageUpdate(BaseModel):
    page_name: str | None = None
    category: str | None = None
    country: str | None = None
    notes: str | None = None


@router.get("/spy-ads/tracked-pages")
def list_tracked_pages(
    category: str | None = None,
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


@router.post("/spy-ads/tracked-pages")
def create_tracked_page(body: TrackedPageCreate, db: Session = Depends(get_db)):
    try:
        existing = db.query(SpyTrackedPage).filter(
            SpyTrackedPage.page_id == body.page_id,
            SpyTrackedPage.is_active.is_(True),
        ).first()
        if existing:
            return _api_response(error=f"Page {body.page_id} is already tracked.")

        row = SpyTrackedPage(
            page_id=body.page_id,
            page_name=body.page_name,
            category=body.category,
            country=body.country,
            notes=body.notes,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _api_response({"id": row.id, "page_id": row.page_id, "page_name": row.page_name})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.patch("/spy-ads/tracked-pages/{page_db_id}")
def update_tracked_page(page_db_id: str, body: TrackedPageUpdate, db: Session = Depends(get_db)):
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
def delete_tracked_page(page_db_id: str, db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db),
):
    try:
        row = db.query(SpyTrackedPage).filter(SpyTrackedPage.id == page_db_id).first()
        if not row:
            return _api_response(error="Tracked page not found.")

        result = fetch_page_ads(
            page_id=row.page_id,
            country=row.country or "ALL",
            active_status=active_status,
            limit=limit,
            after=after,
        )

        row.last_checked_at = datetime.now(timezone.utc)
        db.commit()

        return _api_response(result)
    except Exception as e:
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
def save_ad(body: SaveAdBody, db: Session = Depends(get_db)):
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
def update_saved_ad(ad_db_id: str, body: UpdateSavedAdBody, db: Session = Depends(get_db)):
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
def delete_saved_ad(ad_db_id: str, db: Session = Depends(get_db)):
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
def list_collections(db: Session = Depends(get_db)):
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
def bulk_tag(body: BulkTagBody, db: Session = Depends(get_db)):
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
def analyze_ads(body: AnalyzeBody, db: Session = Depends(get_db)):
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
            model_used="claude-sonnet-4-20250514",
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
                    model="claude-sonnet-4-20250514",
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
def get_report(report_id: str, db: Session = Depends(get_db)):
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
def get_stats(db: Session = Depends(get_db)):
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
