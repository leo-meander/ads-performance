"""Importer: scan existing ads → discover landing pages → write ad-link rows.

Discovery sources:

    Meta ads       ads.raw_data.creative.object_story_spec.link_data.link
                   ads.raw_data.creative.object_story_spec.video_data.call_to_action.value.link
                   ads.raw_data.creative.asset_feed_spec.link_urls[].website_url
                   ads.raw_data.creative.effective_object_story_id (resolves to a post URL — skip)

    Google PMax    google_asset_groups.final_urls  (JSON array of URLs)

    Google Search  ads.raw_data.final_urls  (RSA destination URLs, populated
                    by google_client.fetch_ads)

For each URL found:
  1. normalize_url → (host, slug, utm)
  2. get_or_create_external_page(host, slug) — upserts landing_pages row
  3. Upsert landing_page_ad_links row keyed by (landing_page_id, campaign_id, ad_id)

This runs once as a bootstrap via the router endpoint, and also lives as a
cron in internal_tasks (so newly-created ads flow into landing_pages
automatically).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.ad import Ad
from app.models.campaign import Campaign
from app.models.google_asset_group import GoogleAssetGroup
from app.models.landing_page import LandingPage
from app.models.landing_page_ad_link import LandingPageAdLink
from app.services.landing_page_service import get_or_create_external_page
from app.services.landing_page_url_normalizer import build_url_with_utms, normalize_url

logger = logging.getLogger(__name__)


# --- Meta URL extraction ---------------------------------------------------


def _meta_extract_urls(raw_data: dict | None) -> list[str]:
    """Drill into a Meta ad raw_data payload and yield every destination URL found."""
    if not raw_data:
        return []
    out: list[str] = []
    creative = raw_data.get("creative") or {}
    if not isinstance(creative, dict):
        return []

    oss = creative.get("object_story_spec") or {}
    if isinstance(oss, dict):
        link_data = oss.get("link_data") or {}
        if isinstance(link_data, dict):
            if link_data.get("link"):
                out.append(link_data["link"])
            for child in (link_data.get("child_attachments") or []):
                if isinstance(child, dict) and child.get("link"):
                    out.append(child["link"])

        video_data = oss.get("video_data") or {}
        if isinstance(video_data, dict):
            cta = video_data.get("call_to_action") or {}
            value = (cta or {}).get("value") or {}
            if isinstance(value, dict) and value.get("link"):
                out.append(value["link"])

    afs = creative.get("asset_feed_spec") or {}
    if isinstance(afs, dict):
        for lu in (afs.get("link_urls") or []):
            if isinstance(lu, dict) and lu.get("website_url"):
                out.append(lu["website_url"])

    # Dedupe preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for u in out:
        if u and u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def _google_extract_urls(final_urls: Any) -> list[str]:
    """Google asset_groups.final_urls is a JSON array of URL strings."""
    if not final_urls:
        return []
    if isinstance(final_urls, str):
        return [final_urls]
    if isinstance(final_urls, (list, tuple)):
        return [u for u in final_urls if isinstance(u, str) and u]
    return []


# --- Upsert ad_link --------------------------------------------------------


def _upsert_ad_link(
    db: Session,
    *,
    landing_page_id: str,
    platform: str,
    campaign_id: str | None,
    ad_id: str | None,
    ad_set_id: str | None,
    asset_group_id: str | None,
    destination_url: str,
    utm: dict[str, str],
    now: datetime,
) -> tuple[LandingPageAdLink, bool]:
    """Upsert keyed by (landing_page_id, platform, campaign_id, ad_set_id, ad_id, destination_url).

    Returns (row, created).
    """
    q = db.query(LandingPageAdLink).filter(
        LandingPageAdLink.landing_page_id == landing_page_id,
        LandingPageAdLink.platform == platform,
        LandingPageAdLink.destination_url == destination_url,
    )
    if campaign_id is not None:
        q = q.filter(LandingPageAdLink.campaign_id == campaign_id)
    else:
        q = q.filter(LandingPageAdLink.campaign_id.is_(None))
    if ad_set_id is not None:
        q = q.filter(LandingPageAdLink.ad_set_id == ad_set_id)
    else:
        q = q.filter(LandingPageAdLink.ad_set_id.is_(None))
    if ad_id is not None:
        q = q.filter(LandingPageAdLink.ad_id == ad_id)
    else:
        q = q.filter(LandingPageAdLink.ad_id.is_(None))
    # .first(), not .one_or_none(): nothing enforces uniqueness on this key, and a
    # MultipleResultsFound here used to abort whichever import pass was running.
    # Any duplicate is an equivalent row, so touching the first one is correct.
    row = q.first()

    created = False
    if row is None:
        row = LandingPageAdLink(
            landing_page_id=landing_page_id,
            platform=platform,
            campaign_id=campaign_id,
            ad_id=ad_id,
            ad_set_id=ad_set_id,
            asset_group_id=asset_group_id,
            destination_url=destination_url,
            utm_source=utm.get("utm_source"),
            utm_medium=utm.get("utm_medium"),
            utm_campaign=utm.get("utm_campaign"),
            utm_content=utm.get("utm_content"),
            utm_term=utm.get("utm_term"),
            discovered_at=now,
            last_seen_at=now,
        )
        db.add(row)
        created = True
    else:
        row.last_seen_at = now
        # Update UTMs in case they changed on the latest destination URL
        row.utm_source = utm.get("utm_source") or row.utm_source
        row.utm_medium = utm.get("utm_medium") or row.utm_medium
        row.utm_campaign = utm.get("utm_campaign") or row.utm_campaign
        row.utm_content = utm.get("utm_content") or row.utm_content
        row.utm_term = utm.get("utm_term") or row.utm_term

    return row, created


# --- Clarity-driven importer (UTM campaign match) --------------------------


def import_from_clarity_utms(db: Session) -> dict[str, Any]:
    """Build landing_page_ad_links by matching Clarity UTM_campaign → Campaign.name.

    Why this exists: most Meta ads in our DB have raw_data.creative = {id}
    (Meta doesn't expand the creative object in the Ads list endpoint), so
    there is no destination URL to scan. But Clarity observed the UTM tags
    from actual user visits — and the utm_campaign value matches our
    Campaign.name verbatim.

    This scans landing_page_clarity_snapshots, finds rows with a non-NULL
    utm_campaign, looks up the Campaign by exact name match (falling back to
    prefix-trimmed match for " - Copy" / " - copy" / " - Copy 2" suffixes),
    and upserts a landing_page_ad_links row.
    """
    from app.models.landing_page_clarity import LandingPageClaritySnapshot

    now = datetime.now(timezone.utc)
    summary: dict[str, Any] = {
        "utm_combos_scanned": 0,
        "campaigns_matched": 0,
        "ad_links_created": 0,
        "ad_links_updated": 0,
        "no_match": 0,
        "page_missing": 0,
        "errors": 0,
        "error_samples": [],
    }

    # distinct (landing_page_id, utm_source, utm_campaign, utm_content)
    rows = (
        db.query(
            LandingPageClaritySnapshot.landing_page_id,
            LandingPageClaritySnapshot.utm_source,
            LandingPageClaritySnapshot.utm_campaign,
            LandingPageClaritySnapshot.utm_content,
        )
        .filter(LandingPageClaritySnapshot.utm_campaign.isnot(None))
        .distinct()
        .all()
    )

    # Cache: campaign_name → (Campaign.id, platform)
    campaign_cache: dict[str, tuple[str, str]] = {}
    for c in db.query(Campaign).all():
        campaign_cache.setdefault(c.name, (c.id, c.platform))

    def _lookup_campaign(name: str) -> tuple[str, str] | None:
        if name in campaign_cache:
            return campaign_cache[name]
        # Fuzzy: strip common suffixes Meta adds when duplicating campaigns
        for suffix in (" - Copy", " - copy", " - Copy 2", " - Copy 3"):
            if name.endswith(suffix):
                base = name[: -len(suffix)]
                if base in campaign_cache:
                    return campaign_cache[base]
        return None

    # Preload every landing page. This used to be a .one() per row, which both
    # N+1'd the query count and raised NoResultFound the moment a snapshot
    # outlived its page — and since the loop had no exception handling, that
    # single row aborted the whole pass and every page after it silently kept
    # its missing ad-link.
    pages_by_id: dict[str, LandingPage] = {p.id: p for p in db.query(LandingPage).all()}

    _COMMIT_EVERY = 25
    pending = 0

    for lp_id, utm_s, utm_c, utm_ct in rows:
        summary["utm_combos_scanned"] += 1
        if not utm_c or utm_c.startswith("{{"):  # Meta template placeholder
            summary["no_match"] += 1
            continue
        match = _lookup_campaign(utm_c)
        if match is None:
            summary["no_match"] += 1
            continue
        campaign_id, platform = match
        summary["campaigns_matched"] += 1

        lp = pages_by_id.get(lp_id)
        if lp is None:
            summary["page_missing"] += 1
            continue

        # We only need destination_url as an identifier for the ad-link — use
        # canonical + UTM reconstruction.
        base = f"https://{lp.domain}/{lp.slug}" if lp.slug else f"https://{lp.domain}"
        destination_url = build_url_with_utms(
            base,
            {
                "utm_source": utm_s or "",
                "utm_campaign": utm_c or "",
                "utm_content": utm_ct or "",
            },
        )

        # Per-row isolation: one bad combo must not cost every combo behind it.
        try:
            _, created = _upsert_ad_link(
                db,
                landing_page_id=lp_id,
                platform=platform,
                campaign_id=campaign_id,
                ad_id=None,
                ad_set_id=None,
                asset_group_id=None,
                destination_url=destination_url,
                utm={"utm_source": utm_s, "utm_campaign": utm_c, "utm_content": utm_ct},
                now=now,
            )
            pending += 1
            if pending >= _COMMIT_EVERY:
                db.commit()
                pending = 0
        except Exception as e:
            logger.exception("[lp-importer:clarity-utm] failed page=%s campaign=%s", lp_id, utm_c)
            db.rollback()
            pending = 0
            summary["errors"] += 1
            if len(summary["error_samples"]) < 5:
                summary["error_samples"].append(f"{type(e).__name__}: {e}")
            continue

        if created:
            summary["ad_links_created"] += 1
        else:
            summary["ad_links_updated"] += 1

    db.commit()
    logger.info("[lp-importer:clarity-utm] done: %s", summary)
    return summary


# --- Top-level importer ----------------------------------------------------


def _commit_phase(db: Session, summary: dict[str, Any], label: str) -> None:
    """Commit one scan phase. A failed commit must not discard the phases that
    already succeeded, nor stop the phases still to come."""
    try:
        db.commit()
    except Exception as e:
        logger.exception("[lp-importer] commit failed after %s", label)
        db.rollback()
        summary["errors"] += 1
        summary.setdefault("commit_failures", []).append(f"{label}: {type(e).__name__}: {e}")


def import_from_ads(db: Session) -> dict[str, Any]:
    """Scan all stored ads + google asset groups → upsert landing pages + ad-links.

    Idempotent: re-running updates last_seen_at and picks up new URLs.

    Runs the Clarity-UTM pass FIRST. That pass is where the real coverage comes
    from (most Meta ads store raw_data.creative = {id}, so the scans below find
    no destination URL), and it used to run last — behind three full-table scans
    sharing one uncommitted transaction with no statement_timeout raise. Any
    stall in the scans starved the one pass that matters, and pages kept their
    missing ad-links, which reads on the dashboard as spend and conversions
    frozen at 0. Each phase now commits on its own so none can starve another.
    """
    now = datetime.now(timezone.utc)

    # Same reasoning as ga4_sync: Supabase's default statement_timeout kills a
    # long flush mid-transaction and rolls the whole thing back silently.
    try:
        db.execute(text("SET statement_timeout = '180000'"))  # ms
    except Exception:
        logger.warning("[lp-importer] could not raise statement_timeout", exc_info=True)
    summary = {
        "meta_ads_scanned": 0,
        "meta_urls_found": 0,
        "google_asset_groups_scanned": 0,
        "google_ads_scanned": 0,
        "google_urls_found": 0,
        "pages_created": 0,
        "ad_links_created": 0,
        "ad_links_updated": 0,
        "errors": 0,
    }

    # Clarity-observed UTM → campaign mapping. First, and on its own commit, so
    # the scans below cannot starve it.
    try:
        summary["clarity_utm"] = import_from_clarity_utms(db)
    except Exception as e:
        logger.exception("[lp-importer] clarity-utm pass failed")
        db.rollback()
        summary["clarity_utm"] = {"error": f"{type(e).__name__}: {e}"}

    # Meta ads
    meta_ads = db.query(Ad).filter(Ad.platform == "meta").all()
    summary["meta_ads_scanned"] = len(meta_ads)
    for ad in meta_ads:
        try:
            urls = _meta_extract_urls(ad.raw_data if isinstance(ad.raw_data, dict) else None)
            for url in urls:
                summary["meta_urls_found"] += 1
                n = normalize_url(url)
                if n is None:
                    continue
                page = get_or_create_external_page(
                    db,
                    raw_url=url,
                    title_fallback=f"{n.host}/{n.slug}".rstrip("/"),
                    branch_id=None,
                )
                if page is None:
                    continue
                if page.created_at == page.updated_at:
                    summary["pages_created"] += 1
                _, created = _upsert_ad_link(
                    db,
                    landing_page_id=page.id,
                    platform="meta",
                    campaign_id=ad.campaign_id,
                    ad_id=ad.id,
                    ad_set_id=None,
                    asset_group_id=None,
                    destination_url=url,
                    utm=n.utm,
                    now=now,
                )
                if created:
                    summary["ad_links_created"] += 1
                else:
                    summary["ad_links_updated"] += 1
        except Exception:
            logger.exception("[lp-importer] failed on meta ad id=%s", ad.id)
            summary["errors"] += 1
    _commit_phase(db, summary, "meta-ads")

    # Google asset groups (PMax)
    asset_groups = db.query(GoogleAssetGroup).all()
    summary["google_asset_groups_scanned"] = len(asset_groups)
    for ag in asset_groups:
        try:
            urls = _google_extract_urls(ag.final_urls)
            for url in urls:
                summary["google_urls_found"] += 1
                n = normalize_url(url)
                if n is None:
                    continue
                page = get_or_create_external_page(
                    db,
                    raw_url=url,
                    title_fallback=f"{n.host}/{n.slug}".rstrip("/"),
                    branch_id=None,
                )
                if page is None:
                    continue
                if page.created_at == page.updated_at:
                    summary["pages_created"] += 1
                _, created = _upsert_ad_link(
                    db,
                    landing_page_id=page.id,
                    platform="google",
                    campaign_id=ag.campaign_id,
                    ad_id=None,
                    ad_set_id=None,
                    asset_group_id=ag.id,
                    destination_url=url,
                    utm=n.utm,
                    now=now,
                )
                if created:
                    summary["ad_links_created"] += 1
                else:
                    summary["ad_links_updated"] += 1
        except Exception:
            logger.exception("[lp-importer] failed on google asset group id=%s", ag.id)
            summary["errors"] += 1
    _commit_phase(db, summary, "google-asset-groups")

    # Google Search ads (RSA) — final URLs live on the ad itself (not on an
    # asset group), stored by google_client.fetch_ads into raw_data.final_urls.
    google_ads = db.query(Ad).filter(Ad.platform == "google").all()
    summary["google_ads_scanned"] = len(google_ads)
    for ad in google_ads:
        try:
            raw = ad.raw_data if isinstance(ad.raw_data, dict) else {}
            urls = _google_extract_urls(raw.get("final_urls"))
            for url in urls:
                summary["google_urls_found"] += 1
                n = normalize_url(url)
                if n is None:
                    continue
                page = get_or_create_external_page(
                    db,
                    raw_url=url,
                    title_fallback=f"{n.host}/{n.slug}".rstrip("/"),
                    branch_id=None,
                )
                if page is None:
                    continue
                if page.created_at == page.updated_at:
                    summary["pages_created"] += 1
                _, created = _upsert_ad_link(
                    db,
                    landing_page_id=page.id,
                    platform="google",
                    campaign_id=ad.campaign_id,
                    ad_id=None,           # Google has no ad-level metrics_cache rows
                    ad_set_id=ad.ad_set_id,  # use ad_set level for precise attribution
                    asset_group_id=None,
                    destination_url=url,
                    utm=n.utm,
                    now=now,
                )
                if created:
                    summary["ad_links_created"] += 1
                else:
                    summary["ad_links_updated"] += 1
        except Exception:
            logger.exception("[lp-importer] failed on google ad id=%s", ad.id)
            summary["errors"] += 1
    _commit_phase(db, summary, "google-ads")

    logger.info("[lp-importer] done: %s", summary)
    return summary
