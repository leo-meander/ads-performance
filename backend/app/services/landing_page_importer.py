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

from sqlalchemy.orm import Session

from app.models.ad import Ad
from app.models.campaign import Campaign
from app.models.google_asset_group import GoogleAssetGroup
from app.models.landing_page_ad_link import LandingPageAdLink
from app.services.landing_page_service import get_or_create_external_page
from app.services.landing_page_url_normalizer import normalize_url

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
    row = q.one_or_none()

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
    summary = {
        "utm_combos_scanned": 0,
        "campaigns_matched": 0,
        "ad_links_created": 0,
        "ad_links_updated": 0,
        "no_match": 0,
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

        # Destination URL reconstructed from the landing page + UTMs
        page = db.query(LandingPage).filter(LandingPage.id == lp_id).one_or_none() if False else None
        # We only need destination_url as an identifier for the ad-link — use
        # canonical + UTM reconstruction.
        from app.models.landing_page import LandingPage as LP
        lp = db.query(LP).filter(LP.id == lp_id).one()
        from app.services.landing_page_url_normalizer import build_url_with_utms
        base = f"https://{lp.domain}/{lp.slug}" if lp.slug else f"https://{lp.domain}"
        destination_url = build_url_with_utms(
            base,
            {
                "utm_source": utm_s or "",
                "utm_campaign": utm_c or "",
                "utm_content": utm_ct or "",
            },
        )

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
        if created:
            summary["ad_links_created"] += 1
        else:
            summary["ad_links_updated"] += 1

    db.commit()
    logger.info("[lp-importer:clarity-utm] done: %s", summary)
    return summary


# --- Top-level importer ----------------------------------------------------


def import_from_ads(db: Session) -> dict[str, Any]:
    """Scan all stored ads + google asset groups → upsert landing pages + ad-links.

    Idempotent: re-running updates last_seen_at and picks up new URLs.
    """
    now = datetime.now(timezone.utc)
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

    # After ads-table scan, also pull in the Clarity-observed UTM→campaign mapping.
    # This is where the real coverage comes from for accounts whose stored
    # raw_data lacks creative expansion (the default for our Meta sync).
    try:
        utm_summary = import_from_clarity_utms(db)
        summary["clarity_utm"] = utm_summary
    except Exception:
        logger.exception("[lp-importer] clarity-utm sub-pass failed")
        summary["clarity_utm"] = {"error": "see logs"}

    db.commit()
    logger.info("[lp-importer] done: %s", summary)
    return summary
