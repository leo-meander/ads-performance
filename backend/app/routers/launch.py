from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_role, require_section
from app.models.approval import ComboApproval
from app.models.user import User
from app.services.launch_service import (
    create_auto_config,
    get_auto_config,
    get_available_adsets,
    get_available_campaigns,
    get_launch_preflight,
    launch_to_existing_campaign,
    launch_with_new_campaign,
)

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Schemas ──────────────────────────────────────────────────


class LaunchExistingRequest(BaseModel):
    approval_id: str
    campaign_id: str
    adset_id: str | None = None


class LaunchNewCampaignRequest(BaseModel):
    approval_id: str
    country: str
    ta: str
    language: str


class AutoConfigCreateRequest(BaseModel):
    account_id: str
    country: str
    ta: str
    language: str
    campaign_name_template: str
    default_objective: str = "CONVERSIONS"
    default_daily_budget: float
    default_funnel_stage: str = "TOF"


# ── Endpoints ────────────────────────────────────────────────


@router.get("/launch/campaigns")
def list_launch_campaigns(
    account_id: str | None = None,
    current_user: User = Depends(require_role(["creator", "admin"])),
    _section: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """List campaigns available to launch ads into."""
    try:
        campaigns = get_available_campaigns(db, account_id)
        return _api_response(data={"items": campaigns})
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/launch/adsets")
def list_launch_adsets(
    campaign_id: str = Query(...),
    current_user: User = Depends(require_role(["creator", "admin"])),
    _section: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """List active ad sets under a campaign for launch selection."""
    try:
        adsets = get_available_adsets(db, campaign_id)
        return _api_response(data={"items": adsets})
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/launch/existing")
def launch_existing(
    body: LaunchExistingRequest,
    current_user: User = Depends(require_role(["creator", "admin"])),
    _section: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Launch approved combo into existing campaign."""
    try:
        approval = launch_to_existing_campaign(
            db=db,
            approval_id=body.approval_id,
            campaign_id=body.campaign_id,
            user_id=current_user.id,
            adset_id=body.adset_id,
        )
        return _api_response(data={
            "approval_id": approval.id,
            "launch_status": approval.launch_status,
            "launch_meta_ad_id": approval.launch_meta_ad_id,
            "launched_at": approval.launched_at.isoformat() if approval.launched_at else None,
        })
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.post("/launch/new-campaign")
def launch_new_campaign(
    body: LaunchNewCampaignRequest,
    current_user: User = Depends(require_role(["creator", "admin"])),
    _section: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Auto-create campaign + launch combo."""
    try:
        approval = launch_with_new_campaign(
            db=db,
            approval_id=body.approval_id,
            country=body.country,
            ta=body.ta,
            language=body.language,
            user_id=current_user.id,
        )
        return _api_response(data={
            "approval_id": approval.id,
            "launch_status": approval.launch_status,
            "launch_meta_ad_id": approval.launch_meta_ad_id,
            "launched_at": approval.launched_at.isoformat() if approval.launched_at else None,
        })
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/launch/auto-config")
def get_launch_auto_config(
    country: str = Query(...),
    ta: str = Query(...),
    language: str = Query(...),
    account_id: str | None = None,
    current_user: User = Depends(require_role(["creator", "admin"])),
    _section: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """Get auto-config for campaign creation."""
    try:
        config = get_auto_config(db, account_id, country, ta, language)
        if not config:
            return _api_response(error="No auto-config found for this combination")

        return _api_response(data={
            "id": config.id,
            "campaign_name_template": config.campaign_name_template,
            "default_objective": config.default_objective,
            "default_daily_budget": float(config.default_daily_budget),
            "default_funnel_stage": config.default_funnel_stage,
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/launch/{approval_id}/preflight")
def launch_preflight(
    approval_id: str,
    campaign_id: str | None = None,
    adset_id: str | None = None,
    country: str | None = None,
    ta: str | None = None,
    language: str | None = None,
    current_user: User = Depends(require_role(["creator", "admin"])),
    _section: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """Checklist of what must be in place before this combo can publish to
    Meta. Pass campaign_id (existing-campaign mode) or country+ta+language
    (auto-create mode) to get the mode-specific account + config checks."""
    try:
        result = get_launch_preflight(
            db,
            approval_id,
            campaign_id=campaign_id,
            adset_id=adset_id,
            country=country,
            ta=ta,
            language=language,
        )
        return _api_response(data=result)
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/launch/auto-config")
def create_launch_auto_config(
    body: AutoConfigCreateRequest,
    current_user: User = Depends(require_role(["creator", "admin"])),
    _section: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Create (or overwrite) a campaign auto-config so the Auto-Create New
    Campaign launch mode has the template + budget + objective it needs."""
    try:
        config = create_auto_config(
            db,
            account_id=body.account_id,
            country=body.country,
            ta=body.ta,
            language=body.language,
            campaign_name_template=body.campaign_name_template,
            default_objective=body.default_objective,
            default_daily_budget=body.default_daily_budget,
            default_funnel_stage=body.default_funnel_stage,
        )
        return _api_response(data={
            "id": config.id,
            "account_id": config.account_id,
            "country": config.country,
            "ta": config.ta,
            "language": config.language,
            "campaign_name_template": config.campaign_name_template,
            "default_objective": config.default_objective,
            "default_daily_budget": float(config.default_daily_budget),
            "default_funnel_stage": config.default_funnel_stage,
        })
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/launch/{approval_id}/status")
def get_launch_status(
    approval_id: str,
    current_user: User = Depends(require_role(["creator", "admin"])),
    _section: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """Check launch status for an approval."""
    try:
        approval = db.query(ComboApproval).filter(ComboApproval.id == approval_id).first()
        if not approval:
            return _api_response(error="Approval not found")

        return _api_response(data={
            "approval_id": approval.id,
            "status": approval.status,
            "launch_status": approval.launch_status,
            "launch_meta_ad_id": approval.launch_meta_ad_id,
            "launch_error": approval.launch_error,
            "launched_at": approval.launched_at.isoformat() if approval.launched_at else None,
        })
    except Exception as e:
        return _api_response(error=str(e))
