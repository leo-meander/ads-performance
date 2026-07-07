from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user, require_page, require_role
from app.models.approval import ApprovalReviewer, ComboApproval
from app.models.user import User
from app.services.approval_service import (
    add_comment,
    get_approval_detail,
    get_approvals_list_summary,
    get_batch_detail,
    get_comments,
    record_batch_branch_manager_approval,
    record_batch_decision,
    record_branch_manager_approval,
    record_decision,
    resend_batch_review_request_emails,
    resend_review_request_emails,
    resubmit,
    revise_batch,
    revise_pending_approval,
    submit_batch,
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
    note: str | None = None
    hypothesis_id: str | None = None  # HYP-xxx — links the approval to an experiment


class DecisionRequest(BaseModel):
    decision: str  # APPROVED | REJECTED | NEEDS_REVISION
    feedback: str | None = None


class BranchManagerApproveRequest(BaseModel):
    proof_image: str  # base64 data URL of the approval screenshot


class BatchVersion(BaseModel):
    combo_id: str
    working_file_url: str | None = None
    working_file_label: str | None = None


class SubmitBatchRequest(BaseModel):
    versions: list[BatchVersion]
    reviewer_ids: list[str]
    deadline: str | None = None  # ISO8601 datetime string
    note: str | None = None
    hypothesis_id: str | None = None  # HYP-xxx — shared across all versions in this batch


class ReviseBatchVersion(BaseModel):
    """Per-version edits inside a batch revise. approval_id targets the child
    combo_approval. Any field omitted (None) is left unchanged."""
    approval_id: str
    working_file_url: str | None = None
    working_file_label: str | None = None
    angle_id: str | None = None
    keypoint_ids: list[str] | None = None
    headline: str | None = None
    body_text: str | None = None
    cta: str | None = None
    language: str | None = None
    target_audience: str | None = None


class ReviseBatchRequest(BaseModel):
    """In-place edit on a PENDING batch. deadline + reviewer_ids are batch-wide;
    per-version content lives in `versions`."""
    deadline: str | None = None
    reviewer_ids: list[str] | None = None
    versions: list[ReviseBatchVersion] = []


class ResubmitRequest(BaseModel):
    reviewer_ids: list[str] | None = None  # None/empty -> reuse previous round
    working_file_url: str | None = None
    working_file_label: str | None = None
    deadline: str | None = None


class ReviseRequest(BaseModel):
    """In-place edit on a PENDING approval. Any field omitted (None) is left unchanged."""
    working_file_url: str | None = None
    working_file_label: str | None = None
    deadline: str | None = None
    angle_id: str | None = None
    keypoint_ids: list[str] | None = None
    reviewer_ids: list[str] | None = None
    # Copy fields — clone-on-shared, in-place if exclusive
    headline: str | None = None
    body_text: str | None = None
    cta: str | None = None
    language: str | None = None
    target_audience: str | None = None


class CommentRequest(BaseModel):
    body: str
    parent_id: str | None = None


# ── Endpoints ────────────────────────────────────────────────


@router.post("/approvals")
def submit_approval(
    body: SubmitApprovalRequest,
    current_user: User = Depends(require_role(["creator", "admin"])),
    _section: User = Depends(require_page("approvals", "edit")),
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
            note=body.note,
            hypothesis_id=body.hypothesis_id,
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
    current_user: User = Depends(require_page("approvals")),
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

        items = get_approvals_list_summary(db, approvals)

        return _api_response(data={"items": items, "total": total})
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/approvals/pending")
def list_pending_reviews(
    current_user: User = Depends(require_role(["reviewer", "admin"])),
    _section: User = Depends(require_page("approvals")),
    db: Session = Depends(get_db),
):
    """List approvals awaiting this reviewer's decision."""
    try:
        pending_rows = (
            db.query(ApprovalReviewer.approval_id)
            .filter(
                ApprovalReviewer.reviewer_id == current_user.id,
                ApprovalReviewer.status == "ONGOING",
            )
            .all()
        )
        approval_ids = [row.approval_id for row in pending_rows]

        approvals = (
            db.query(ComboApproval)
            .filter(
                ComboApproval.id.in_(approval_ids),
                ComboApproval.status == "ONGOING",
            )
            .order_by(ComboApproval.created_at.desc())
            .all()
            if approval_ids else []
        )

        items = get_approvals_list_summary(db, approvals)

        return _api_response(data={"items": items, "total": len(items)})
    except Exception as e:
        return _api_response(error=str(e))


# ── Approval batches (multi-version reviews) ─────────────────


@router.post("/approval-batches")
def submit_approval_batch(
    body: SubmitBatchRequest,
    current_user: User = Depends(require_role(["creator", "admin"])),
    _section: User = Depends(require_page("approvals", "edit")),
    db: Session = Depends(get_db),
):
    """Submit N combo versions of one target as a single review batch."""
    try:
        batch = submit_batch(
            db=db,
            versions=[v.model_dump() for v in body.versions],
            reviewer_ids=body.reviewer_ids,
            submitted_by=current_user.id,
            deadline=body.deadline,
            note=body.note,
            hypothesis_id=body.hypothesis_id,
        )
        detail = get_batch_detail(db, batch.id)
        return _api_response(data=detail)
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/approval-batches/{batch_id}")
def get_approval_batch(
    batch_id: str,
    current_user: User = Depends(require_page("approvals")),
    db: Session = Depends(get_db),
):
    """Get full batch detail (all versions + batch-level reviewer states)."""
    try:
        detail = get_batch_detail(db, batch_id)
        if not detail:
            return _api_response(error="Batch not found")

        user_roles = current_user.roles or []
        if "admin" not in user_roles:
            is_creator = detail["submitted_by"] == current_user.id
            is_reviewer = any(r["reviewer_id"] == current_user.id for r in detail["reviewers"])
            if not is_creator and not is_reviewer:
                return _api_response(error="Access denied")

        return _api_response(data=detail)
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/approval-batches/{batch_id}/decide")
def decide_approval_batch(
    batch_id: str,
    body: DecisionRequest,
    current_user: User = Depends(require_role(["reviewer", "admin"])),
    _section: User = Depends(require_page("approvals")),
    db: Session = Depends(get_db),
):
    """Submit one reviewer decision for the whole batch (all-or-nothing)."""
    try:
        batch = record_batch_decision(
            db=db,
            batch_id=batch_id,
            reviewer_id=current_user.id,
            decision=body.decision,
            feedback=body.feedback,
        )
        detail = get_batch_detail(db, batch.id)
        return _api_response(data=detail)
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.post("/approval-batches/{batch_id}/branch-manager-approve")
def branch_manager_approve_batch(
    batch_id: str,
    body: BranchManagerApproveRequest,
    current_user: User = Depends(require_role(["creator", "admin"])),
    _section: User = Depends(require_page("approvals", "edit")),
    db: Session = Depends(get_db),
):
    """Record a branch-manager sign-off (with screenshot proof) for a whole
    batch and mark every version APPROVED — bypassing the reviewer round."""
    try:
        batch = record_batch_branch_manager_approval(
            db=db,
            batch_id=batch_id,
            actor_id=current_user.id,
            proof_image=body.proof_image,
        )
        detail = get_batch_detail(db, batch.id)
        return _api_response(data=detail)
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.post("/approval-batches/{batch_id}/resend-request")
def resend_batch_request(
    batch_id: str,
    current_user: User = Depends(require_role(["creator", "admin"])),
    _section: User = Depends(require_page("approvals", "edit")),
    db: Session = Depends(get_db),
):
    """Resend one consolidated review-request email per still-PENDING reviewer of a batch."""
    try:
        result = resend_batch_review_request_emails(
            db=db,
            batch_id=batch_id,
            requester_id=current_user.id,
        )
        return _api_response(data=result)
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.post("/approval-batches/{batch_id}/revise")
def revise_approval_batch(
    batch_id: str,
    body: ReviseBatchRequest,
    current_user: User = Depends(require_role(["creator", "admin"])),
    _section: User = Depends(require_page("approvals", "edit")),
    db: Session = Depends(get_db),
):
    """In-place edit while pending: bumps the batch + every version's round,
    resets reviewer decisions across all versions, re-notifies once."""
    try:
        batch = revise_batch(
            db=db,
            batch_id=batch_id,
            creator_id=current_user.id,
            deadline=body.deadline,
            reviewer_ids=body.reviewer_ids,
            versions=[v.model_dump() for v in body.versions],
        )
        detail = get_batch_detail(db, batch.id)
        return _api_response(data=detail)
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/approvals/{approval_id}")
def get_approval(
    approval_id: str,
    current_user: User = Depends(require_page("approvals")),
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
    _section: User = Depends(require_page("approvals")),
    db: Session = Depends(get_db),
):
    """Submit reviewer decision (APPROVED or REJECTED).

    Deciding is a reviewer's core action — it requires only view-level
    meta_ads access (same as loading the approval page). The real
    authorization is the reviewer role plus the assigned-reviewer check
    inside record_decision(); requiring edit-level access here wrongly
    locked out view-only reviewers with a 403.
    """
    try:
        approval = record_decision(
            db=db,
            approval_id=approval_id,
            reviewer_id=current_user.id,
            decision=body.decision,
            feedback=body.feedback,
        )
        detail = get_approval_detail(db, approval.id)
        return _api_response(data=detail)
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.post("/approvals/{approval_id}/branch-manager-approve")
def branch_manager_approve(
    approval_id: str,
    body: BranchManagerApproveRequest,
    current_user: User = Depends(require_role(["creator", "admin"])),
    _section: User = Depends(require_page("approvals", "edit")),
    db: Session = Depends(get_db),
):
    """Record a branch-manager sign-off (with screenshot proof) and mark the
    combo APPROVED — bypassing the in-app reviewer round."""
    try:
        approval = record_branch_manager_approval(
            db=db,
            approval_id=approval_id,
            actor_id=current_user.id,
            proof_image=body.proof_image,
        )
        detail = get_approval_detail(db, approval.id)
        return _api_response(data=detail)
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.post("/approvals/{approval_id}/resend-request")
def resend_request(
    approval_id: str,
    current_user: User = Depends(require_role(["creator", "admin"])),
    _section: User = Depends(require_page("approvals", "edit")),
    db: Session = Depends(get_db),
):
    """Resend the review-request email to all reviewers still PENDING."""
    try:
        result = resend_review_request_emails(
            db=db,
            approval_id=approval_id,
            requester_id=current_user.id,
        )
        return _api_response(data=result)
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.post("/approvals/{approval_id}/revise")
def revise_approval(
    approval_id: str,
    body: ReviseRequest,
    current_user: User = Depends(require_role(["creator", "admin"])),
    _section: User = Depends(require_page("approvals", "edit")),
    db: Session = Depends(get_db),
):
    """In-place edit while pending: bumps round, resets reviewer decisions, re-notifies."""
    try:
        approval = revise_pending_approval(
            db=db,
            approval_id=approval_id,
            creator_id=current_user.id,
            working_file_url=body.working_file_url,
            working_file_label=body.working_file_label,
            deadline=body.deadline,
            angle_id=body.angle_id,
            keypoint_ids=body.keypoint_ids,
            reviewer_ids=body.reviewer_ids,
            headline=body.headline,
            body_text=body.body_text,
            cta=body.cta,
            language=body.language,
            target_audience=body.target_audience,
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
    _section: User = Depends(require_page("approvals", "edit")),
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


# ── Comment threads ───────────────────────────────────────────


@router.get("/approvals/{approval_id}/comments")
def list_approval_comments(
    approval_id: str,
    current_user: User = Depends(require_page("approvals")),
    db: Session = Depends(get_db),
):
    """List comments (threaded) for a single approval."""
    try:
        thread = get_comments(db, approval_id=approval_id)
        return _api_response(data=thread)
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/approvals/{approval_id}/comments")
def post_approval_comment(
    approval_id: str,
    body: CommentRequest,
    current_user: User = Depends(require_page("approvals")),
    db: Session = Depends(get_db),
):
    """Add a comment to an approval."""
    try:
        comment = add_comment(
            db,
            user_id=current_user.id,
            body=body.body,
            approval_id=approval_id,
            parent_id=body.parent_id,
        )
        thread = get_comments(db, approval_id=approval_id)
        return _api_response(data=thread)
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/approvals/batch/{batch_id}/comments")
def list_batch_comments(
    batch_id: str,
    current_user: User = Depends(require_page("approvals")),
    db: Session = Depends(get_db),
):
    """List comments (threaded) for a batch."""
    try:
        thread = get_comments(db, batch_id=batch_id)
        return _api_response(data=thread)
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/approvals/batch/{batch_id}/comments")
def post_batch_comment(
    batch_id: str,
    body: CommentRequest,
    current_user: User = Depends(require_page("approvals")),
    db: Session = Depends(get_db),
):
    """Add a comment to an approval batch."""
    try:
        comment = add_comment(
            db,
            user_id=current_user.id,
            body=body.body,
            batch_id=batch_id,
            parent_id=body.parent_id,
        )
        thread = get_comments(db, batch_id=batch_id)
        return _api_response(data=thread)
    except ValueError as e:
        return _api_response(error=str(e))
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))
