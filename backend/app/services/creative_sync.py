"""Sync creative library (materials, copies, combos) from Meta ads.

Idempotent: only inserts rows that don't already exist, keyed by:
  - AdMaterial: (branch_id, description=ad_name)
  - AdCopy:     (branch_id, headline)
  - AdCombo:    (branch_id, ad_name)

Called from sync_engine.sync_meta_account after the Ad table has been upserted.
"""
import logging

from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount
from facebook_business.api import FacebookAdsApi
from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.services.creative_service import (
    next_combo_id, next_copy_id, next_material_id,
)
from app.services.parse_utils import parse_campaign_metadata

logger = logging.getLogger(__name__)


def _detect_ta(name: str) -> str:
    """Extract TA using the canonical whitelist (parse_utils.TA_WHITELIST).

    Returns 'Unknown' when no whitelist token is present, matching the
    platform-wide parsing contract (see .claude/rules/parsing-rules.md).
    """
    return parse_campaign_metadata(name)["ta"]


def dominant_country_map(db: Session, account_id=None) -> dict[tuple, str]:
    """Map (account_id, ad_name) -> the DOMINANT country (highest ad-level spend).

    A single Meta ad_name is reused across many adsets in different countries;
    each ad_id belongs to exactly one adset (one country). We sum ad-level spend
    per (ad_name, country) and pick the highest-spend country, so a combo
    reflects where the creative actually ran — not an arbitrary first row. The
    old logic took whatever country the join returned first, which is why a
    TW-heavy ad could end up tagged KR.

    Country lives on AdSet (parsed from the adset-name prefix at sync time).
    'Unknown'/blank countries are ignored. For ad_names that have no spend rows
    yet (freshly synced, metrics not pulled), we fall back to the first-seen
    real country so they still get a value instead of NULL.

    Pass `account_id` to restrict to one branch.
    """
    from sqlalchemy import func

    from app.models.ad import Ad
    from app.models.ad_set import AdSet
    from app.models.metrics import MetricsCache

    base_filters = [AdSet.country.isnot(None), AdSet.country != "Unknown"]
    if account_id is not None:
        base_filters.append(Ad.account_id == account_id)

    out: dict[tuple, str] = {}
    best: dict[tuple, float] = {}

    # 1) Dominant country by total ad-level spend.
    spend_rows = (
        db.query(
            Ad.account_id,
            Ad.name,
            AdSet.country,
            func.coalesce(func.sum(MetricsCache.spend), 0).label("spend"),
        )
        .join(AdSet, AdSet.id == Ad.ad_set_id)
        .join(MetricsCache, MetricsCache.ad_id == Ad.id)
        .filter(*base_filters)
        .group_by(Ad.account_id, Ad.name, AdSet.country)
        .all()
    )
    for acc, name, country, spend in spend_rows:
        if not name or not country:
            continue
        key = (acc, name)
        spend = float(spend or 0)
        if key not in best or spend > best[key]:
            best[key] = spend
            out[key] = country

    # 2) Fallback for ad_names with no spend rows at all (first-seen real country).
    fallback_rows = (
        db.query(Ad.account_id, Ad.name, AdSet.country)
        .join(AdSet, AdSet.id == Ad.ad_set_id)
        .filter(*base_filters)
        .all()
    )
    for acc, name, country in fallback_rows:
        key = (acc, name)
        if name and country and key not in out:
            out[key] = country
    return out


def _country_by_ad_name(db: Session, account_id) -> dict[str, str]:
    """ad_name -> dominant country for ONE account (thin wrapper over
    dominant_country_map, keyed by ad_name only)."""
    return {
        name: country
        for (_acc, name), country in dominant_country_map(db, account_id=account_id).items()
    }


def _detect_material_type(ad_name: str) -> str:
    n = (ad_name or "").lower()
    if "[video]" in n:
        return "video"
    if "[carousel]" in n:
        return "carousel"
    return "image"


def _detect_language(text: str) -> str:
    sample = (text or "")[:50]
    if any(0x3040 <= ord(c) <= 0x30FF for c in sample):
        return "ja"
    if any(ord(c) > 0x4E00 for c in sample):
        return "zh"
    return "en"


def sync_creative_library_for_account(db: Session, account: AdAccount) -> dict:
    """Upsert AdMaterial / AdCopy / AdCombo rows from Meta ad creatives for one account."""
    summary = {
        "materials_created": 0, "copies_created": 0, "combos_created": 0,
        "combos_recountried": 0, "errors": [],
    }

    if not account.access_token_enc:
        return summary

    acc_id = account.account_id if account.account_id.startswith("act_") else f"act_{account.account_id}"

    try:
        FacebookAdsApi.init(app_id="", app_secret="", access_token=account.access_token_enc)
        fb = FBAdAccount(acc_id)
        ads = fb.get_ads(
            fields=["name", "status", "creative{title,body,call_to_action_type,thumbnail_url}", "campaign{name}"],
            params={
                "limit": 200,
                "filtering": [{"field": "ad.effective_status", "operator": "IN",
                               "value": ["ACTIVE", "PAUSED"]}],
            },
        )
    except Exception as e:
        logger.exception("Creative sync: failed to fetch ads for %s", account.account_id)
        summary["errors"].append(f"Failed to fetch Meta ads: {e}")
        return summary

    # Preload existing per-branch for O(1) lookups
    existing_materials = {
        m.description: m
        for m in db.query(AdMaterial).filter(AdMaterial.branch_id == account.id).all()
        if m.description
    }
    existing_copies = {
        c.headline: c
        for c in db.query(AdCopy).filter(AdCopy.branch_id == account.id).all()
    }
    existing_combos = {
        c.ad_name: c
        for c in db.query(AdCombo).filter(AdCombo.branch_id == account.id).all()
        if c.ad_name
    }
    # ad_name -> country, derived from the already-synced Ad -> AdSet link.
    country_by_ad = _country_by_ad_name(db, account.id)

    seen_ad_names: set[str] = set()

    for ad in ads:
        ad_name = (ad.get("name") or "").strip()
        if not ad_name or ad_name in seen_ad_names:
            continue
        seen_ad_names.add(ad_name)

        creative = ad.get("creative") or {}
        campaign = ad.get("campaign") or {}
        campaign_name = campaign.get("name", "")

        title = (creative.get("title") or "").strip()
        body = (creative.get("body") or "").strip()
        cta = creative.get("call_to_action_type") or None
        thumb = creative.get("thumbnail_url") or None

        ta = _detect_ta(f"{campaign_name} {ad_name}")
        mat_type = _detect_material_type(ad_name)

        # ── Material (keyed by description=ad_name) ──
        material = existing_materials.get(ad_name)
        if not material:
            if not thumb:
                # Material requires file_url (NOT NULL). Skip this ad — no combo either.
                continue
            try:
                mid = next_material_id(db)
                material = AdMaterial(
                    material_id=mid,
                    branch_id=account.id,
                    material_type=mat_type,
                    file_url=thumb,
                    description=ad_name,
                    target_audience=ta,
                    url_source="auto",
                )
                db.add(material)
                db.flush()
                existing_materials[ad_name] = material
                summary["materials_created"] += 1
            except Exception as e:
                db.rollback()
                logger.exception("Creative sync: failed to create material for %s", ad_name)
                summary["errors"].append(f"material {ad_name[:40]}: {e}")
                continue

        # ── Copy (keyed by headline) ──
        headline = (title or ad_name)[:500]
        copy = existing_copies.get(headline)
        if not copy:
            try:
                copy_body = body or f"[No body text — ad: {ad_name}]"
                cid = next_copy_id(db)
                copy = AdCopy(
                    copy_id=cid,
                    branch_id=account.id,
                    target_audience=ta,
                    headline=headline,
                    body_text=copy_body,
                    cta=cta[:200] if cta else None,
                    language=_detect_language(title + body),
                )
                db.add(copy)
                db.flush()
                existing_copies[headline] = copy
                summary["copies_created"] += 1
            except Exception as e:
                db.rollback()
                logger.exception("Creative sync: failed to create copy for %s", ad_name)
                summary["errors"].append(f"copy {ad_name[:40]}: {e}")
                continue

        # ── Combo (keyed by ad_name) ──
        dominant_country = country_by_ad.get(ad_name)
        existing_combo = existing_combos.get(ad_name)
        if existing_combo is None:
            try:
                cb_id = next_combo_id(db)
                combo = AdCombo(
                    combo_id=cb_id,
                    branch_id=account.id,
                    ad_name=ad_name,
                    copy_id=copy.copy_id,
                    material_id=material.material_id,
                    target_audience=ta,
                    country=dominant_country,
                    verdict="TEST",
                    verdict_source="auto",
                )
                db.add(combo)
                db.flush()
                existing_combos[ad_name] = combo
                summary["combos_created"] += 1
            except Exception as e:
                db.rollback()
                logger.exception("Creative sync: failed to create combo for %s", ad_name)
                summary["errors"].append(f"combo {ad_name[:40]}: {e}")
                continue
        elif dominant_country and existing_combo.country != dominant_country:
            # Correct combos whose country was set arbitrarily before this fix
            # (e.g. TW-heavy creative previously tagged KR). Only overwrite when
            # we have a real dominant value — never blank out an existing one.
            existing_combo.country = dominant_country
            summary["combos_recountried"] += 1

    db.commit()
    return summary
