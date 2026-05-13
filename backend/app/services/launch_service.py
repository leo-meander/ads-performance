import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.ad_combo import AdCombo
from app.models.ad_set import AdSet
from app.models.approval import ComboApproval
from app.models.campaign import Campaign
from app.models.campaign_auto_config import CampaignAutoConfig
from app.models.user import User
from app.services.changelog import log_change
from app.services.meta_creative_builder import build_or_get_meta_creative
from app.services.notification_service import create_notification

logger = logging.getLogger(__name__)


def launch_to_existing_campaign(
    db: Session,
    approval_id: str,
    campaign_id: str,
    user_id: str,
    adset_id: str | None = None,
) -> ComboApproval:
    """Launch an approved combo into an existing campaign via Meta Ads API.

    Meta requires an ad set ID (not campaign ID) when creating an ad. If
    `adset_id` is supplied, it is used after verifying it belongs to the
    chosen campaign. Otherwise the most recent ACTIVE ad set under the
    campaign is auto-selected.
    """
    approval = _validate_launch(db, approval_id, user_id)
    combo = db.query(AdCombo).filter(AdCombo.id == approval.combo_id).first()
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()

    if not campaign:
        raise ValueError("Campaign not found")

    adset = _resolve_adset(db, campaign, adset_id, combo)

    now = datetime.now(timezone.utc)

    try:
        account = _get_account_for_campaign(db, campaign)
        meta_ad_id = _create_meta_ad_from_ids(account, adset.platform_adset_id, combo, db=db)

        approval.launch_campaign_id = campaign_id
        approval.launch_meta_ad_id = meta_ad_id
        approval.launch_status = "LAUNCHED"
        approval.launched_at = now

        # Notify creator
        _notify_launch_success(db, approval, combo)

        # Emit change log entry for the new ad creation (never raises).
        combo_name = combo.ad_name if combo else "Unknown"
        log_change(
            db,
            category="ad_creation",
            title=f"Ad launched: {combo_name}"[:200],
            source="auto",
            triggered_by="manual",
            occurred_at=now,
            description=(
                f"Launched combo '{combo_name}' into existing campaign '{campaign.name}'."
            ),
            campaign_id=campaign_id,
            account_id=campaign.account_id if campaign else None,
            author_user_id=user_id,
            after_value={
                "meta_ad_id": meta_ad_id,
                "combo_id": str(combo.id) if combo else None,
                "approval_id": str(approval.id),
            },
        )

        db.commit()
        return approval

    except Exception as e:
        logger.exception("Launch to existing campaign failed: %s", e)
        approval.launch_status = "LAUNCH_FAILED"
        approval.launch_error = str(e)
        db.commit()

        _notify_launch_failure(db, approval, combo, str(e))
        raise


def launch_with_new_campaign(
    db: Session,
    approval_id: str,
    country: str,
    ta: str,
    language: str,
    user_id: str,
) -> ComboApproval:
    """Auto-create a new campaign + ad set + ad via Meta Ads API."""
    approval = _validate_launch(db, approval_id, user_id)
    combo = db.query(AdCombo).filter(AdCombo.id == approval.combo_id).first()

    # Look up auto-config
    config = get_auto_config(db, combo.branch_id, country, ta, language)
    if not config:
        raise ValueError(f"No auto-config found for country={country}, ta={ta}, language={language}")

    now = datetime.now(timezone.utc)

    try:
        account = _get_account_by_id(db, config.account_id)

        # Step 1: Create campaign
        campaign_name = _generate_campaign_name(config, country, ta)
        meta_campaign_id = _create_meta_campaign(account, campaign_name, config)

        # Step 2: Create ad set
        meta_adset_id = _create_meta_adset(account, meta_campaign_id, combo, config, country)

        # Step 3: Create ad
        meta_ad_id = _create_meta_ad_from_ids(account, meta_adset_id, combo, db=db)

        approval.launch_meta_ad_id = meta_ad_id
        approval.launch_status = "LAUNCHED"
        approval.launched_at = now

        _notify_launch_success(db, approval, combo)

        # Emit change log entry for the new campaign+adset+ad creation.
        combo_name = combo.ad_name if combo else "Unknown"
        log_change(
            db,
            category="ad_creation",
            title=f"Campaign launched: {campaign_name}"[:200],
            source="auto",
            triggered_by="manual",
            occurred_at=now,
            description=(
                f"Auto-created campaign + ad set + ad for '{combo_name}' "
                f"(country={country.upper()}, TA={ta})."
            ),
            country=country.upper() if country else None,
            account_id=account.id if account else None,
            author_user_id=user_id,
            after_value={
                "meta_campaign_id": meta_campaign_id,
                "meta_adset_id": meta_adset_id,
                "meta_ad_id": meta_ad_id,
                "combo_id": str(combo.id) if combo else None,
                "approval_id": str(approval.id),
                "ta": ta,
                "language": language,
            },
        )

        db.commit()
        return approval

    except Exception as e:
        logger.exception("Launch with new campaign failed: %s", e)
        approval.launch_status = "LAUNCH_FAILED"
        approval.launch_error = str(e)
        db.commit()

        _notify_launch_failure(db, approval, combo, str(e))
        raise


def get_auto_config(
    db: Session,
    account_id: str | None,
    country: str,
    ta: str,
    language: str,
) -> CampaignAutoConfig | None:
    """Look up campaign auto-config for a given combination."""
    q = db.query(CampaignAutoConfig).filter(
        CampaignAutoConfig.country == country.upper(),
        CampaignAutoConfig.ta == ta,
        CampaignAutoConfig.language == language.lower(),
        CampaignAutoConfig.is_active == True,
    )
    if account_id:
        q = q.filter(CampaignAutoConfig.account_id == account_id)
    return q.first()


def get_available_campaigns(db: Session, account_id: str | None = None) -> list[dict]:
    """List active campaigns available for launching ads into."""
    q = db.query(Campaign).filter(Campaign.status == "ACTIVE")
    if account_id:
        q = q.filter(Campaign.account_id == account_id)
    campaigns = q.order_by(Campaign.name).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "platform_campaign_id": c.platform_campaign_id,
            "objective": c.objective,
            "daily_budget": float(c.daily_budget) if c.daily_budget else None,
            "status": c.status,
        }
        for c in campaigns
    ]


def get_available_adsets(db: Session, campaign_id: str) -> list[dict]:
    """List active ad sets under a campaign for launch selection."""
    rows = (
        db.query(AdSet)
        .filter(AdSet.campaign_id == campaign_id, AdSet.status == "ACTIVE")
        .order_by(AdSet.name)
        .all()
    )
    return [
        {
            "id": a.id,
            "name": a.name,
            "platform_adset_id": a.platform_adset_id,
            "country": a.country,
            "daily_budget": float(a.daily_budget) if a.daily_budget else None,
            "status": a.status,
        }
        for a in rows
    ]


# ── Private helpers ──────────────────────────────────────────


def _resolve_adset(db: Session, campaign: Campaign, adset_id: str | None, combo: AdCombo | None) -> AdSet:
    """Resolve which ad set to launch into.

    If adset_id is provided, validate it belongs to the campaign. Otherwise,
    auto-pick an ACTIVE ad set under the campaign — preferring one whose
    country matches the combo's country if available.
    """
    if adset_id:
        adset = db.query(AdSet).filter(AdSet.id == adset_id).first()
        if not adset:
            raise ValueError("Ad set not found")
        if adset.campaign_id != campaign.id:
            raise ValueError("Ad set does not belong to the selected campaign")
        return adset

    candidates = (
        db.query(AdSet)
        .filter(AdSet.campaign_id == campaign.id, AdSet.status == "ACTIVE")
        .order_by(AdSet.created_at.desc())
        .all()
    )
    if not candidates:
        raise ValueError(
            "No active ad set under this campaign. Pick an ad set explicitly "
            "or create a new campaign instead."
        )

    if combo and combo.country:
        for a in candidates:
            if a.country and a.country.upper() == combo.country.upper():
                return a
    return candidates[0]


def _validate_launch(db: Session, approval_id: str, user_id: str) -> ComboApproval:
    """Validate that the approval exists, is approved, and the user is the creator."""
    approval = db.query(ComboApproval).filter(ComboApproval.id == approval_id).first()
    if not approval:
        raise ValueError("Approval not found")
    if approval.status != "APPROVED":
        raise ValueError(f"Approval is not approved (status: {approval.status})")
    if approval.submitted_by != user_id:
        # Admin can also launch — check role
        user = db.query(User).filter(User.id == user_id).first()
        if not user or "admin" not in (user.roles or []):
            raise ValueError("Only the creator or admin can launch this combo")
    if approval.launch_status == "LAUNCHED":
        raise ValueError("This combo has already been launched")
    return approval


def _get_account_for_campaign(db, campaign):
    """Get the ad account associated with a campaign."""
    from app.models.account import AdAccount

    return db.query(AdAccount).filter(AdAccount.id == campaign.account_id).first()


def _get_account_by_id(db, account_id):
    """Get ad account by ID."""
    from app.models.account import AdAccount

    account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
    if not account:
        raise ValueError(f"Ad account {account_id} not found")
    return account


def _generate_campaign_name(config: CampaignAutoConfig, country: str, ta: str) -> str:
    """Generate campaign name from template."""
    template = config.campaign_name_template
    return (
        template.replace("{COUNTRY}", country.upper())
        .replace("{TA}", ta)
        .replace("{FUNNEL}", f"[{config.default_funnel_stage}]")
    )


def _create_meta_campaign(account, campaign_name: str, config: CampaignAutoConfig) -> str:
    """Create a campaign on Meta Ads API. Returns platform campaign ID."""
    from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount
    from facebook_business.api import FacebookAdsApi

    FacebookAdsApi.init(access_token=account.access_token_enc)
    fb_account = FBAdAccount(f"act_{account.account_id}")

    params = {
        "name": campaign_name,
        "objective": config.default_objective,
        "status": "PAUSED",
        "special_ad_categories": [],
        "daily_budget": int(float(config.default_daily_budget) * 100),  # Convert to cents
    }
    result = fb_account.create_campaign(params=params)
    return result["id"]


def _create_meta_adset(account, campaign_id: str, combo, config, country: str) -> str:
    """Create an ad set on Meta Ads API. Returns platform adset ID."""
    from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount
    from facebook_business.api import FacebookAdsApi

    FacebookAdsApi.init(access_token=account.access_token_enc)
    fb_account = FBAdAccount(f"act_{account.account_id}")

    params = {
        "name": f"{country}_{combo.target_audience or 'ALL'}",
        "campaign_id": campaign_id,
        "billing_event": "IMPRESSIONS",
        "optimization_goal": "OFFSITE_CONVERSIONS",
        "daily_budget": int(float(config.default_daily_budget) * 100),
        "status": "PAUSED",
        "targeting": {"geo_locations": {"countries": [country.upper()]}},
    }
    result = fb_account.create_ad_set(params=params)
    return result["id"]


def _create_meta_ad_from_ids(account, adset_id: str, combo, *, db: Session) -> str:
    """Create an ad using platform adset ID.

    Builds a real Meta AdCreative from the combo's material+copy first
    (via meta_creative_builder) — passing combo.material_id straight in as
    a creative_id is wrong; that field is an internal "MAT-001" short id,
    not a Meta creative id.
    """
    from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount
    from facebook_business.api import FacebookAdsApi

    creative_id = build_or_get_meta_creative(db, account, combo)

    FacebookAdsApi.init(access_token=account.access_token_enc)
    fb_account = FBAdAccount(f"act_{account.account_id}")

    params = {
        "name": combo.ad_name or combo.combo_id,
        "adset_id": adset_id,
        "creative": {"creative_id": creative_id},
        "status": "PAUSED",
    }
    result = fb_account.create_ad(params=params)
    return result["id"]


def _notify_launch_success(db: Session, approval: ComboApproval, combo):
    """Notify creator of successful launch."""
    combo_name = combo.ad_name if combo else "Unknown"
    if approval.submitted_by:
        create_notification(
            db,
            user_id=approval.submitted_by,
            type="LAUNCH_SUCCESS",
            title=f"Launched: {combo_name}",
            body=f"{combo_name} has been successfully launched to Meta Ads.",
            reference_id=approval.id,
            reference_type="combo_approval",
        )


def _notify_launch_failure(db: Session, approval: ComboApproval, combo, error: str):
    """Notify creator + admins of launch failure."""
    combo_name = combo.ad_name if combo else "Unknown"

    if approval.submitted_by:
        create_notification(
            db,
            user_id=approval.submitted_by,
            type="LAUNCH_FAILED",
            title=f"Launch failed: {combo_name}",
            body=f"{combo_name} launch failed. Error: {error}",
            reference_id=approval.id,
            reference_type="combo_approval",
        )

    # Also notify all admins
    admins = db.query(User).filter(User.is_active == True).all()
    for admin in admins:
        if "admin" in (admin.roles or []) and admin.id != approval.submitted_by:
            create_notification(
                db,
                user_id=admin.id,
                type="LAUNCH_FAILED",
                title=f"Launch failed: {combo_name}",
                body=f"{combo_name} launch failed. Error: {error}",
                reference_id=approval.id,
                reference_type="combo_approval",
            )
