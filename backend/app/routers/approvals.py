from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user, require_role, require_section
from app.models.approval import ApprovalReviewer, ComboApproval
from app.models.user import User
from app.services.approval_service import (
    get_approval_detail,
    record_decision,
    resubmit,
    submit_for_approval,
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


class SubmitApprovalRequest(BaseModel):
    combo_id: str
    reviewer_ids: list[str]
    working_file_url: str | None = None
    working_file_label: str | None = None
    deadline: str | None = None  # ISO8601 datetime string


class DecisionRequest(BaseModel):
    decision: str  # APPROVED | REJECTED | NEEDS_REVISION


class ResubmitRequest(BaseModel):
    reviewer_ids: list[str] | None = None  # None/empty -> reuse previous round
    working_file_url: str | None = None
    working_file_label: str | None = None
    deadline: str | None = None


# ── Endpoints ────────────────────────────────────────────────


@router.post("/approvals")
def submit_approval(
    body: SubmitApprovalRequest,
    current_user: User = Depends(require_role(["creator", "admin"])),
    _section: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Submit a combo for approval."""
    try:
        approval = submit_for_approval(
            db=db,
            combo_id=body.combo_id,
            reviewer_ids=body.reviewer_ids,
            working_file_url=body.working_file_url,
            working_file_label=body.working_file_label,
            submitted_by=current_user.id,
            deadline=body.deadline,
        )
        detail = get_approval_detail(db, approval.id)
        return _api_response(data=detail)
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/approvals")
def list_approvals(
    status: str | None = None,
    combo_id: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """List approvals. Creator sees own. Admin sees all. Reviewer sees assigned."""
    try:
        q = db.query(ComboApproval)

        user_roles = current_user.roles or []
        if "admin" not in user_roles:
            if "creator" in user_roles and "reviewer" in user_roles:
                # See own submissions + assigned reviews
                own_ids = [a.id for a in db.query(ComboApproval.id).filter(
                    ComboApproval.submitted_by == current_user.id
                ).all()]
                assigned_ids = [ar.approval_id for ar in db.query(ApprovalReviewer.approval_id).filter(
                    ApprovalReviewer.reviewer_id == current_user.id
                ).all()]
                all_ids = list(set(own_ids + assigned_ids))
                q = q.filter(ComboApproval.id.in_(all_ids)) if all_ids else q.filter(ComboApproval.id == None)
            elif "creator" in user_roles:
                q = q.filter(ComboApproval.submitted_by == current_user.id)
            elif "reviewer" in user_roles:
                assigned_ids = [ar.approval_id for ar in db.query(ApprovalReviewer.approval_id).filter(
                    ApprovalReviewer.reviewer_id == current_user.id
                ).all()]
                q = q.filter(ComboApproval.id.in_(assigned_ids)) if assigned_ids else q.filter(ComboApproval.id == None)

        if status:
            q = q.filter(ComboApproval.status == status)
        if combo_id:
            q = q.filter(ComboApproval.combo_id == combo_id)

        total = q.count()
        approvals = q.order_by(ComboApproval.created_at.desc()).offset(offset).limit(limit).all()

        items = []
        for a in approvals:
            detail = get_approval_detail(db, a.id)
            if detail:
                items.append(detail)

        return _api_response(data={"items": items, "total": total})
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/approvals/pending")
def list_pending_reviews(
    current_user: User = Depends(require_role(["reviewer", "admin"])),
    _section: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """List approvals awaiting this reviewer's decision."""
    try:
        pending_rows = (
            db.query(ApprovalReviewer)
            .filter(
                ApprovalReviewer.reviewer_id == current_user.id,
                ApprovalReviewer.status == "PENDING",
            )
            .all()
        )

        items = []
        for row in pending_rows:
            detail = get_approval_detail(db, row.approval_id)
            if detail and detail["status"] == "PENDING_APPROVAL":
                items.append(detail)

        return _api_response(data={"items": items, "total": len(items)})
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/approvals/{approval_id}")
def get_approval(
    approval_id: str,
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """Get approval detail."""
    try:
        detail = get_approval_detail(db, approval_id)
        if not detail:
            return _api_response(error="Approval not found")

        # Check access: admin sees all, creator sees own, reviewer sees assigned
        user_roles = current_user.roles or []
        if "admin" not in user_roles:
            is_creator = detail["submitted_by"] == current_user.id
            is_reviewer = any(r["reviewer_id"] == current_user.id for r in detail["reviewers"])
            if not is_creator and not is_reviewer:
                return _api_response(error="Access denied")

        return _api_response(data=detail)
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/approvals/{approval_id}/decide")
def decide_approval(
    approval_id: str,
    body: DecisionRequest,
    current_user: User = Depends(require_role(["reviewer", "admin"])),
    _section: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Submit reviewer decision (APPROVED or REJECTED)."""
    try:
        approval = record_decision(
            db=db,
            approval_id=approval_id,
            reviewer_id=current_user.id,
            decision=body.decision,
        )
        detail = get_approval_detail(db, approval.id)
        return _api_response(data=detail)
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.post("/approvals/{approval_id}/resubmit")
def resubmit_approval(
    approval_id: str,
    body: ResubmitRequest,
    current_user: User = Depends(require_role(["creator", "admin"])),
    _section: User = Depends(require_section("meta_ads", "edit")),
    db: Session = Depends(get_db),
):
    """Re-submit a rejected approval with new round."""
    try:
        new_approval = resubmit(
            db=db,
            approval_id=approval_id,
            reviewer_ids=body.reviewer_ids,
            working_file_url=body.working_file_url,
            working_file_label=body.working_file_label,
            creator_id=current_user.id,
            deadline=body.deadline,
        )
        detail = get_approval_detail(db, new_approval.id)
        return _api_response(data=detail)
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))
