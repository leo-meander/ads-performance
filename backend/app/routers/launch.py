from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_role
from app.models.approval import ComboApproval
from app.models.user import User
from app.services.launch_service import (
    get_auto_config,
    get_available_campaigns,
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


class LaunchNewCampaignRequest(BaseModel):
    approval_id: str
    country: str
    ta: str
    language: str


# ── Endpoints ────────────────────────────────────────────────


@router.get("/launch/campaigns")
def list_launch_campaigns(
    account_id: str | None = None,
    current_user: User = Depends(require_role(["creator", "admin"])),
    db: Session = Depends(get_db),
):
    """List campaigns available to launch ads into."""
    try:
        campaigns = get_available_campaigns(db, account_id)
        return _api_response(data={"items": campaigns})
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/launch/existing")
def launch_existing(
    body: LaunchExistingRequest,
    current_user: User = Depends(require_role(["creator", "admin"])),
    db: Session = Depends(get_db),
):
    """Launch approved combo into existing campaign."""
    try:
        approval = launch_to_existing_campaign(
            db=db,
            approval_id=body.approval_id,
            campaign_id=body.campaign_id,
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


@router.post("/launch/new-campaign")
def launch_new_campaign(
    body: LaunchNewCampaignRequest,
    current_user: User = Depends(require_role(["creator", "admin"])),
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


@router.get("/launch/{approval_id}/status")
def get_launch_status(
    approval_id: str,
    current_user: User = Depends(require_role(["creator", "admin"])),
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
