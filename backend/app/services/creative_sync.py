"""Sync creative library (materials, copies, combos) from Meta ads.

Idempotent: only inserts rows that don't already exist, keyed by:
  - AdMaterial: (branch_id, description=ad_name)
  - AdCopy:     (branch_id, headline)
  - AdCombo:    (branch_id, ad_name)

Called from sync_engine.sync_meta_account after the Ad table has been upserted.

ad_name is the identity key for the whole creative subsystem — combo_metrics_sync
and material_url_sync both look combos up by name, deliberately, because one Meta
ad_name is reused across many ad_ids (campaigns/adsets) and their metrics are
SUMMED into a single combo. That makes a rename on Meta's side destructive:
without apply_ad_renames() below, the old combo silently stops receiving metrics
(its name no longer matches any insights row) and a brand-new combo is created,
orphaning the verdict, angle, keypoints and hypothesis links.
"""
import logging
from collections import defaultdict

from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount
from facebook_business.api import FacebookAdsApi
from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.ad import Ad
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.winning_ad_month import WinningAdMonth
from app.services.changelog import log_change
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


def apply_ad_renames(
    db: Session,
    account: AdAccount,
    rename_pairs: set[tuple[str, str]],
    names_seen: set[str],
) -> dict:
    """Carry Meta ad renames over to the creative library, in place.

    Must run BEFORE sync_creative_library_for_account in the same transaction as
    the `ads` table upsert — that upsert overwrites Ad.name, which is the only
    record of the old name. Miss the window and the rename is undetectable
    forever.

    `rename_pairs` is {(old_name, new_name)} collected during the ad upsert;
    `names_seen` is every ad name Meta returned this run, used to tell a full
    rename from a partial one.

    Only unambiguous, complete renames are applied:
      - one old name -> exactly one new name (a split is left alone),
      - one new name <- exactly one old name (a merge is left alone),
      - no ad in this fetch still carries the old name (a partial rename means
        two genuinely distinct creative groups now exist — the new name gets its
        own combo from the normal sync path),
      - no combo already occupies the new name.

    Anything ambiguous is skipped rather than guessed at: creating a duplicate
    combo is recoverable, merging two real creatives' history is not.
    """
    summary = {"combos_renamed": 0, "renames_skipped": 0}
    if not rename_pairs:
        return summary

    by_old: dict[str, set[str]] = defaultdict(set)
    by_new: dict[str, set[str]] = defaultdict(set)
    for old_name, new_name in rename_pairs:
        if not old_name or not new_name or old_name == new_name:
            continue
        by_old[old_name].add(new_name)
        by_new[new_name].add(old_name)

    for old_name, new_names in by_old.items():
        if len(new_names) != 1:
            summary["renames_skipped"] += 1  # split: one name became several
            continue
        new_name = next(iter(new_names))
        if len(by_new[new_name]) != 1:
            summary["renames_skipped"] += 1  # merge: several names became one
            continue
        if old_name in names_seen:
            summary["renames_skipped"] += 1  # partial: old name still in use
            continue

        combo = (
            db.query(AdCombo)
            .filter(AdCombo.branch_id == account.id, AdCombo.ad_name == old_name)
            .first()
        )
        if combo is None:
            continue  # nothing in the library under the old name yet

        clash = (
            db.query(AdCombo)
            .filter(AdCombo.branch_id == account.id, AdCombo.ad_name == new_name)
            .first()
        )
        if clash is not None:
            summary["renames_skipped"] += 1
            continue

        combo.ad_name = new_name

        # The material is keyed by description=ad_name; move it too, but only
        # when it still matches — a hand-edited description is the user's.
        material = (
            db.query(AdMaterial)
            .filter(AdMaterial.material_id == combo.material_id)
            .first()
        )
        if material is not None and material.description == old_name:
            material.description = new_name

        # Winning-by-Month rows are keyed by (account, month, ad_name); keep the
        # monthly tab reading the same name as the library. Skip any month that
        # already has a row under the new name (unique constraint).
        taken_months = {
            m
            for (m,) in db.query(WinningAdMonth.month)
            .filter(
                WinningAdMonth.account_id == account.id,
                WinningAdMonth.ad_name == new_name,
            )
            .all()
        }
        won_rows = (
            db.query(WinningAdMonth)
            .filter(
                WinningAdMonth.account_id == account.id,
                WinningAdMonth.ad_name == old_name,
            )
            .all()
        )
        for row in won_rows:
            if row.month not in taken_months:
                row.ad_name = new_name

        log_change(
            db,
            category="ad_mutation",
            title=f"Ad renamed on Meta: {new_name}"[:200],
            source="auto",
            triggered_by="system",
            description=(
                f"Creative library combo {combo.combo_id} followed a Meta ad "
                f"rename, keeping its verdict and metric history."
            ),
            platform="meta",
            account_id=account.id,
            before_value={"ad_name": old_name},
            after_value={"ad_name": new_name, "combo_id": combo.combo_id},
        )

        summary["combos_renamed"] += 1
        logger.info(
            "[creative-rename] %s: combo %s %r -> %r",
            account.account_name, combo.combo_id, old_name, new_name,
        )

    db.flush()
    return summary


def _fetch_meta_ad_names(account: AdAccount) -> set[str] | None:
    """Every ad name currently on Meta for this account, or None on failure.

    No status filter: an archived ad still owns its name, and treating it as
    gone would misreport a live name as a rename.
    """
    acc_id = (
        account.account_id
        if account.account_id.startswith("act_")
        else f"act_{account.account_id}"
    )
    try:
        FacebookAdsApi.init(app_id="", app_secret="", access_token=account.access_token_enc)
        fb = FBAdAccount(acc_id)
        ads = fb.get_ads(fields=["name"], params={"limit": 500})
        return {(a.get("name") or "").strip() for a in ads if (a.get("name") or "").strip()}
    except Exception:
        logger.exception("diagnose_orphan_combos: failed to fetch ads from Meta for %s", account.account_id)
        return None


def diagnose_orphan_combos(db: Session, account_name_filter: str | None = None) -> dict:
    """Find combos whose ad_name matches no row in `ads`, and tell a real rename
    apart from a harmless gap in the `ads` table. Read-only.

    The naive test — "no `ads` row carries this combo's name" — over-selects,
    because `ads` is not a complete mirror of Meta: sync_engine skips any ad
    whose adset/campaign hasn't synced yet, so the ad never gets an `ads` row
    while creative_sync (reading Meta directly) still creates its combo; and
    combos can be created by hand with names that never existed on Meta.

    So this asks Meta directly. For every active Meta account it pulls current
    ad names and classifies each orphan:
      RENAMED_OR_DELETED  name is gone from Meta      -> real merge candidate
      MISSING_FROM_ADS    name is still live on Meta  -> `ads` gap, not a rename
      NO_SPEND            never received metrics      -> probably never delivered

    For RENAMED_OR_DELETED combos, also lists "twins" — other combos in the
    same branch sharing the material's file_url, i.e. the likely other half of
    a fork (same creative re-imported under the new name).
    """
    accounts = (
        db.query(AdAccount)
        .filter(AdAccount.platform == "meta", AdAccount.is_active.is_(True))
        .all()
    )
    if account_name_filter:
        needle = account_name_filter.lower()
        accounts = [a for a in accounts if needle in (a.account_name or "").lower()]

    by_account = []
    totals = {"RENAMED_OR_DELETED": 0, "MISSING_FROM_ADS": 0, "NO_SPEND": 0}

    for account in accounts:
        entry: dict = {"account_name": account.account_name, "account_id": account.account_id}

        if not account.access_token_enc:
            entry["status"] = "skipped: no access token"
            by_account.append(entry)
            continue

        db_ad_names = {
            n for (n,) in db.query(Ad.name).filter(Ad.account_id == account.id).all() if n
        }
        combos = (
            db.query(AdCombo)
            .filter(AdCombo.branch_id == account.id, AdCombo.ad_name.isnot(None))
            .all()
        )
        orphans = [c for c in combos if c.ad_name not in db_ad_names]
        if not orphans:
            entry["status"] = "no orphaned combos"
            by_account.append(entry)
            continue

        meta_names = _fetch_meta_ad_names(account)
        if meta_names is None:
            entry["status"] = f"{len(orphans)} orphan(s), but Meta is unreachable — cannot classify"
            by_account.append(entry)
            continue

        classified = []
        for combo in sorted(orphans, key=lambda c: -(float(c.spend or 0))):
            if combo.ad_name in meta_names:
                verdict = "MISSING_FROM_ADS"
            elif not combo.spend:
                verdict = "NO_SPEND"
            else:
                verdict = "RENAMED_OR_DELETED"
            totals[verdict] += 1

            material = (
                db.query(AdMaterial)
                .filter(AdMaterial.material_id == combo.material_id)
                .first()
            )
            twins: list[str] = []
            if verdict == "RENAMED_OR_DELETED" and material and material.file_url:
                twins = [
                    c2.combo_id
                    for c2 in combos
                    if c2.combo_id != combo.combo_id
                    and (
                        db.query(AdMaterial)
                        .filter(
                            AdMaterial.material_id == c2.material_id,
                            AdMaterial.file_url == material.file_url,
                        )
                        .first()
                        is not None
                    )
                ]

            classified.append({
                "verdict": verdict,
                "combo_id": combo.combo_id,
                "ad_name": combo.ad_name,
                "combo_verdict": combo.verdict,
                "spend": float(combo.spend) if combo.spend else 0,
                "roas": float(combo.roas) if combo.roas else 0,
                "updated_at": combo.updated_at.isoformat() if combo.updated_at else None,
                "twins": twins,
            })

        entry["status"] = f"{len(orphans)} orphan(s) classified"
        entry["combos"] = classified
        by_account.append(entry)

    return {
        "totals": totals,
        "accounts": by_account,
    }


def merge_orphan_combo(db: Session, orphan_combo_id: str, dry_run: bool = True) -> dict:
    """Consolidate an orphaned combo (see diagnose_orphan_combos) into its live
    twin — another combo in the same branch whose material shares the same
    file_url, i.e. the same creative asset re-imported under Meta's new name.

    If more than one twin exists (the ad was split into several Meta ads, not
    simply renamed), the twin with the higher current spend is treated as the
    dominant successor — the same spend-weighted tie-break already used for
    country assignment (see dominant_country_map). The runner-up(s) are left
    completely untouched; only the chosen twin receives the merge.

    Every table that references ad_combos.combo_id is re-pointed from the
    orphan to the target before the orphan is deleted:
      - hypothesis_combo_links: ON DELETE CASCADE — moved first, or the link
        (which hypothesis this combo tested) would be silently destroyed.
        Skipped (not duplicated) if the target already has a link to that
        same hypothesis, since (hypothesis_id, combo_id) is unique.
      - creative_hypotheses.combo_id, winning_ad_months.combo_id,
        figma_jobs.source_combo_id: ON DELETE SET NULL — moved so those rows
        keep resolving to something that still exists, instead of quietly
        going NULL.

    ad_combos has no archived/is_active column to soft-delete into, so the
    orphan row is hard-deleted — but only after its full state is captured in
    a changelog before_value snapshot, so the merge is auditable even after
    the row is gone.

    dry_run=True (default) computes and returns the plan — including which
    twin was picked and why, and exact counts of what would move — without
    writing anything. Call again with dry_run=False to commit.
    """
    from app.models.creative_hypothesis import CreativeHypothesis
    from app.models.figma import FigmaJob
    from app.models.hypothesis_combo_link import HypothesisComboLink

    orphan = db.query(AdCombo).filter(AdCombo.combo_id == orphan_combo_id).first()
    if orphan is None:
        return {"error": f"combo {orphan_combo_id} not found"}

    material = (
        db.query(AdMaterial).filter(AdMaterial.material_id == orphan.material_id).first()
    )
    if material is None or not material.file_url:
        return {"error": f"combo {orphan_combo_id} has no material/file_url to match twins on"}

    twins = (
        db.query(AdCombo)
        .join(AdMaterial, AdMaterial.material_id == AdCombo.material_id)
        .filter(
            AdCombo.branch_id == orphan.branch_id,
            AdCombo.combo_id != orphan.combo_id,
            AdMaterial.file_url == material.file_url,
        )
        .all()
    )
    if not twins:
        return {"error": f"no live twin found for {orphan_combo_id} — nothing to merge into"}

    target = max(twins, key=lambda c: float(c.spend or 0))
    declined = [c.combo_id for c in twins if c.combo_id != target.combo_id]

    plan = {
        "orphan_combo_id": orphan.combo_id,
        "orphan_ad_name": orphan.ad_name,
        "orphan_verdict": orphan.verdict,
        "orphan_spend": float(orphan.spend or 0),
        "target_combo_id": target.combo_id,
        "target_ad_name": target.ad_name,
        "target_spend": float(target.spend or 0),
        "declined_twins": declined,
        "dry_run": dry_run,
    }

    if dry_run:
        plan["would_move"] = {
            "hypothesis_links": db.query(HypothesisComboLink)
            .filter(HypothesisComboLink.combo_id == orphan.combo_id).count(),
            "direct_hypotheses": db.query(CreativeHypothesis)
            .filter(CreativeHypothesis.combo_id == orphan.combo_id).count(),
            "winning_months": db.query(WinningAdMonth)
            .filter(WinningAdMonth.combo_id == orphan.combo_id).count(),
            "figma_jobs": db.query(FigmaJob)
            .filter(FigmaJob.source_combo_id == orphan.combo_id).count(),
        }
        return plan

    moved = {
        "hypothesis_links_moved": 0, "hypothesis_links_dropped_duplicate": 0,
        "direct_hypotheses_repointed": 0, "winning_months_repointed": 0,
        "figma_jobs_repointed": 0,
    }

    for link in (
        db.query(HypothesisComboLink)
        .filter(HypothesisComboLink.combo_id == orphan.combo_id)
        .all()
    ):
        clash = (
            db.query(HypothesisComboLink)
            .filter(
                HypothesisComboLink.hypothesis_id == link.hypothesis_id,
                HypothesisComboLink.combo_id == target.combo_id,
            )
            .first()
        )
        if clash:
            db.delete(link)
            moved["hypothesis_links_dropped_duplicate"] += 1
        else:
            link.combo_id = target.combo_id
            moved["hypothesis_links_moved"] += 1

    for h in (
        db.query(CreativeHypothesis)
        .filter(CreativeHypothesis.combo_id == orphan.combo_id)
        .all()
    ):
        h.combo_id = target.combo_id
        moved["direct_hypotheses_repointed"] += 1

    for w in (
        db.query(WinningAdMonth)
        .filter(WinningAdMonth.combo_id == orphan.combo_id)
        .all()
    ):
        w.combo_id = target.combo_id
        moved["winning_months_repointed"] += 1

    for j in (
        db.query(FigmaJob)
        .filter(FigmaJob.source_combo_id == orphan.combo_id)
        .all()
    ):
        j.source_combo_id = target.combo_id
        moved["figma_jobs_repointed"] += 1

    log_change(
        db,
        category="ad_mutation",
        title=f"Combo merged: {orphan.combo_id} -> {target.combo_id}"[:200],
        source="manual",
        triggered_by="user",
        description=(
            f"Orphaned combo {orphan.combo_id} ({orphan.ad_name!r}) matched no "
            f"live Meta ad; its creative asset now lives under {target.combo_id} "
            f"({target.ad_name!r}). Full pre-delete state kept in before_value."
            + (f" Declined twin(s), left untouched: {declined}." if declined else "")
        ),
        platform="meta",
        account_id=orphan.branch_id,
        before_value={
            "combo_id": orphan.combo_id,
            "ad_name": orphan.ad_name,
            "verdict": orphan.verdict,
            "verdict_source": orphan.verdict_source,
            "verdict_notes": orphan.verdict_notes,
            "spend": float(orphan.spend) if orphan.spend else 0,
            "roas": float(orphan.roas) if orphan.roas else 0,
            "conversions": orphan.conversions,
            "angle_id": orphan.angle_id,
            "keypoint_ids": orphan.keypoint_ids,
            "target_audience": orphan.target_audience,
            "country": orphan.country,
        },
        after_value={"merged_into": target.combo_id, "declined_twins": declined},
    )

    db.delete(orphan)
    db.commit()

    plan["applied"] = True
    plan["moved"] = moved
    return plan


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
