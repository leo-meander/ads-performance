"""Competitor ad monitor: crawl tracked pages, keep the longevity ledger.

Runs on demand -- the "Crawl now" button on /ad-research, or a manual
dispatch of /api/internal/tasks/spy-ads-crawl. Each run:

1. asks the Ad Library provider for each tracked page's live ads,
2. upserts them into `spy_competitor_ads`, extending first/last-seen,
3. retires ads that were there last time and are gone now,
4. re-derives creative groups so duplicated concepts read as one.

The expensive part is step 1 - Apify bills per ad returned - so the crawl is
bounded per page and deliberately has no schedule. Run length is measured
from Meta's own start date, so crawling more often does not make the ranking
better; it only sharpens our own first/last-seen evidence.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models.spy_competitor_ad import SpyCompetitorAd, SpyCreativeGroup
from app.models.spy_tracked_page import SpyTrackedPage
from app.services.ad_library import AdLibraryError, active_provider_name, fetch_page_ads
from app.services.ad_library.base import NormalizedAd
from app.services.spy_fingerprint import fingerprint, group_ads

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """Postgres hands back tz-aware datetimes; SQLite (tests) does not."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _days_running(ad: SpyCompetitorAd, now: datetime) -> int:
    """How long the ad has been in market.

    The window ends at whichever bound we can actually stand behind:

    1. Meta's own stop date, when it gave one;
    2. otherwise, for an ad we have stopped seeing, the last crawl that still
       found it -- we know it ran that long and cannot claim more;
    3. otherwise now, for an ad still running.

    Case 2 is what keeps the headline number honest when crawling is ad hoc.
    Counting up to the crawl that *noticed* the ad missing would silently
    credit it with however long the gap between crawls happened to be, so an
    ad that died in February would read as still-running in April.
    """
    stop = _aware(ad.ad_delivery_stop_time)
    last_seen = _aware(ad.last_seen_at)
    if stop:
        end = stop
    elif not ad.is_currently_active and last_seen:
        end = last_seen
    else:
        end = now

    start = _aware(ad.ad_delivery_start_time)
    if start:
        return max(0, (end.date() - start.date()).days)
    # No provider start date: fall back to our own observation window so the
    # ranking still has something honest to sort on.
    first = _aware(ad.first_seen_at) or now
    return max(0, (end.date() - first.date()).days)


def _days_observed(ad: SpyCompetitorAd) -> int:
    first = _aware(ad.first_seen_at)
    last = _aware(ad.last_seen_at)
    if not first or not last:
        return 0
    return max(0, (last.date() - first.date()).days)


def _apply_creative(row: SpyCompetitorAd, ad: NormalizedAd) -> None:
    """Refresh the mutable creative snapshot from the latest crawl."""
    row.page_id = ad.page_id or row.page_id
    row.page_name = ad.page_name or row.page_name
    row.country = ad.country or row.country
    row.ad_creative_bodies = ad.ad_creative_bodies
    row.ad_creative_link_titles = ad.ad_creative_link_titles
    row.ad_creative_link_captions = ad.ad_creative_link_captions
    row.cta_text = (ad.cta_text or "")[:200] or None
    row.link_url = ad.link_url or None
    row.media_type = ad.media_type
    row.image_urls = ad.image_urls
    row.video_urls = ad.video_urls
    row.preview_image_url = ad.preview_image_url or None
    row.ad_snapshot_url = ad.ad_snapshot_url or None
    row.publisher_platforms = ad.publisher_platforms
    row.source = ad.source
    row.raw_data = ad.raw_data
    # Meta's start date is the one number we cannot reconstruct if a later
    # crawl returns it blank, so never overwrite a known value with nothing.
    if ad.ad_delivery_start_time:
        row.ad_delivery_start_time = ad.ad_delivery_start_time
    row.ad_delivery_stop_time = ad.ad_delivery_stop_time
    row.fingerprint = fingerprint(
        ad.ad_creative_bodies, ad.ad_creative_link_titles, ad.image_urls, ad.video_urls
    )


def upsert_ads(
    db: Session,
    ads: list[NormalizedAd],
    tracked_page: SpyTrackedPage | None = None,
    now: datetime | None = None,
) -> dict:
    """Fold one crawl's ads into the ledger. Returns {new, seen_again}."""
    now = now or _now()
    new_count = 0
    seen_again = 0

    for ad in ads:
        if not ad.ad_archive_id:
            continue
        row = (
            db.query(SpyCompetitorAd)
            .filter(SpyCompetitorAd.ad_archive_id == ad.ad_archive_id)
            .first()
        )
        if row is None:
            row = SpyCompetitorAd(
                ad_archive_id=ad.ad_archive_id,
                first_seen_at=now,
                last_seen_at=now,
                seen_count=1,
                is_active=True,
            )
            db.add(row)
            new_count += 1
        else:
            row.last_seen_at = now
            row.seen_count = (row.seen_count or 0) + 1
            row.is_active = True
            seen_again += 1

        if tracked_page is not None:
            row.tracked_page_id = tracked_page.id
        row.is_currently_active = ad.is_active
        if ad.is_active:
            # A relaunched ad reappearing must not keep its old tombstone.
            row.disappeared_at = None
        elif row.disappeared_at is None:
            row.disappeared_at = now

        _apply_creative(row, ad)
        row.days_running = _days_running(row, now)
        row.days_observed = _days_observed(row)

    db.flush()
    return {"new": new_count, "seen_again": seen_again}


def _retire_missing(
    db: Session,
    tracked_page: SpyTrackedPage,
    seen_ids: set[str],
    crawl_was_complete: bool,
    now: datetime,
) -> int:
    """Mark ads that this page used to run and no longer does.

    Only safe when the crawl returned fewer ads than we asked for: a run that
    hit its results limit was truncated, and every ad past the cut would look
    identical to one that stopped. Retiring on a truncated crawl would erase
    exactly the long-running ads the page exists to surface.
    """
    if not crawl_was_complete:
        return 0

    stale = (
        db.query(SpyCompetitorAd)
        .filter(
            SpyCompetitorAd.tracked_page_id == tracked_page.id,
            SpyCompetitorAd.is_currently_active.is_(True),
            SpyCompetitorAd.is_active.is_(True),
        )
        .all()
    )
    retired = 0
    for row in stale:
        if row.ad_archive_id in seen_ids:
            continue
        row.is_currently_active = False
        if row.disappeared_at is None:
            row.disappeared_at = now
        # Freeze the run length at the last day we could still see it.
        row.days_running = _days_running(row, now)
        retired += 1
    db.flush()
    return retired


def crawl_tracked_page(
    db: Session,
    tracked_page: SpyTrackedPage,
    limit: int | None = None,
    now: datetime | None = None,
) -> dict:
    """Crawl one competitor page. Never raises - failures land on the row."""
    now = now or _now()
    limit = limit or settings.SPY_CRAWL_ADS_PER_PAGE
    result = {
        "page_id": tracked_page.page_id,
        "page_name": tracked_page.page_name,
        "fetched": 0,
        "new": 0,
        "seen_again": 0,
        "retired": 0,
        "error": None,
    }

    try:
        page = fetch_page_ads(
            page_id=tracked_page.page_id,
            country=tracked_page.country or "ALL",
            active_status="ACTIVE",
            limit=limit,
        )
        ads = page.ads
        result["fetched"] = len(ads)

        counts = upsert_ads(db, ads, tracked_page=tracked_page, now=now)
        result.update(counts)
        result["retired"] = _retire_missing(
            db,
            tracked_page,
            {a.ad_archive_id for a in ads},
            crawl_was_complete=len(ads) < limit,
            now=now,
        )

        tracked_page.last_checked_at = now
        tracked_page.last_crawl_ad_count = len(ads)
        tracked_page.last_crawl_error = None
        if not ads and page.coverage_note:
            tracked_page.last_crawl_error = page.coverage_note
            result["error"] = page.coverage_note
        db.commit()
    except AdLibraryError as e:
        db.rollback()
        tracked_page.last_checked_at = now
        tracked_page.last_crawl_ad_count = 0
        tracked_page.last_crawl_error = str(e)[:2000]
        db.commit()
        result["error"] = str(e)
        logger.warning("[spy-crawl] %s failed: %s", tracked_page.page_name, e)
    except Exception as e:  # noqa: BLE001 - one bad page must not stop the crawl
        db.rollback()
        logger.exception("[spy-crawl] %s crashed", tracked_page.page_name)
        tracked_page.last_checked_at = now
        tracked_page.last_crawl_error = f"Unexpected error: {e}"[:2000]
        db.commit()
        result["error"] = str(e)

    return result


# -- Creative grouping --------------------------------------------------


def rebuild_creative_groups(db: Session, now: datetime | None = None) -> dict:
    """Re-partition every tracked ad into creative concepts.

    Grouping is global rather than per-competitor on purpose: an angle several
    hotels independently keep running is a far stronger signal than one hotel
    repeating itself, and only cross-page grouping shows it.
    """
    now = now or _now()
    rows = db.query(SpyCompetitorAd).filter(SpyCompetitorAd.is_active.is_(True)).all()
    if not rows:
        return {"ads": 0, "groups": 0}

    by_id = {r.id: r for r in rows}
    clusters = group_ads([
        {
            "id": r.id,
            "ad_creative_bodies": r.ad_creative_bodies,
            "ad_creative_link_titles": r.ad_creative_link_titles,
            "image_urls": r.image_urls,
            "video_urls": r.video_urls,
        }
        for r in rows
    ])

    live_keys = set()
    persisted = 0
    for group_key, member_ids in clusters.items():
        members = [by_id[m] for m in member_ids]
        # A cluster of one is just an ad. Persisting it would fill the table
        # with rows nothing queries and, worse, make every ad in the UI claim
        # it belongs to a duplicated concept.
        if len(members) < 2:
            for m in members:
                m.creative_group_key = None
            continue
        live_keys.add(group_key)
        persisted += 1
        for m in members:
            m.creative_group_key = group_key

        first_seens = [_aware(m.first_seen_at) for m in members if m.first_seen_at]
        last_seens = [_aware(m.last_seen_at) for m in members if m.last_seen_at]
        # Meta's start date reaches further back than our first crawl, so let
        # it win when present - otherwise every concept looks brand new on the
        # day the monitor was switched on.
        starts = [
            _aware(m.ad_delivery_start_time) for m in members if m.ad_delivery_start_time
        ]
        active_members = [m for m in members if m.is_currently_active]
        representative = max(members, key=lambda m: (m.days_running or 0))

        group = (
            db.query(SpyCreativeGroup)
            .filter(SpyCreativeGroup.group_key == group_key)
            .first()
        )
        if group is None:
            group = SpyCreativeGroup(group_key=group_key)
            db.add(group)

        group.ad_count = len(members)
        group.active_ad_count = len(active_members)
        group.page_ids = sorted({m.page_id for m in members if m.page_id})
        group.page_names = sorted({m.page_name for m in members if m.page_name})
        group.representative_ad_id = representative.ad_archive_id
        group.preview_image_url = next(
            (m.preview_image_url for m in members if m.preview_image_url), None
        )
        group.media_type = representative.media_type
        group.first_seen_at = min(starts + first_seens) if (starts or first_seens) else None
        group.last_seen_at = max(last_seens) if last_seens else None
        group.max_days_running = max((m.days_running or 0) for m in members)
        group.is_still_active = bool(active_members)
        group.is_active = True
        group.label = _group_label(representative)

    # Groups whose membership changed leave their old key behind; retire those
    # rather than deleting, so a report that cited one still resolves.
    stale = (
        db.query(SpyCreativeGroup)
        .filter(
            SpyCreativeGroup.is_active.is_(True),
            SpyCreativeGroup.group_key.notin_(live_keys) if live_keys else True,
        )
        .all()
    )
    for g in stale:
        g.is_active = False

    db.commit()
    return {"ads": len(rows), "groups": persisted}


def _group_label(rep: SpyCompetitorAd) -> str:
    """A short human handle for the concept: its longest-running ad's hook."""
    bodies = rep.ad_creative_bodies or []
    titles = rep.ad_creative_link_titles or []
    text = next((t for t in list(titles) + list(bodies) if t), "")
    text = " ".join(str(text).split())
    if len(text) > 120:
        text = text[:117] + "..."
    return text or f"{rep.page_name or 'Unknown'} — {rep.media_type or 'ad'}"


# -- Entry point --------------------------------------------------------


def run_crawl(db: Session, page_db_id: str | None = None, limit: int | None = None) -> dict:
    """Crawl every enabled tracked page (or just one), then regroup."""
    now = _now()
    q = db.query(SpyTrackedPage).filter(
        SpyTrackedPage.is_active.is_(True),
        SpyTrackedPage.monitor_enabled.is_(True),
    )
    if page_db_id:
        q = q.filter(SpyTrackedPage.id == page_db_id)
    pages = q.order_by(SpyTrackedPage.page_name).all()

    if not pages:
        return {
            "provider": active_provider_name(),
            "pages": [],
            "totals": {"fetched": 0, "new": 0, "seen_again": 0, "retired": 0, "failed": 0},
            "groups": 0,
            "error": "No tracked competitor pages are enabled for monitoring.",
        }

    results = [crawl_tracked_page(db, p, limit=limit, now=now) for p in pages]
    grouping = rebuild_creative_groups(db, now=now)

    totals = {
        "fetched": sum(r["fetched"] for r in results),
        "new": sum(r["new"] for r in results),
        "seen_again": sum(r["seen_again"] for r in results),
        "retired": sum(r["retired"] for r in results),
        "failed": sum(1 for r in results if r["error"]),
    }
    logger.info(
        "[spy-crawl] %d pages: fetched=%d new=%d retired=%d failed=%d groups=%d",
        len(results), totals["fetched"], totals["new"], totals["retired"],
        totals["failed"], grouping["groups"],
    )
    return {
        "provider": active_provider_name(),
        "pages": results,
        "totals": totals,
        "groups": grouping["groups"],
        "error": None,
    }
