import logging
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ad_combo import AdCombo
from app.models.approval import ApprovalReviewer, ComboApproval
from app.models.user import User
from app.services.email_service import render_approval_result_email, render_review_request_email
from app.services.notification_service import create_notification

logger = logging.getLogger(__name__)


def submit_for_approval(
    db: Session,
    combo_id: str,
    reviewer_ids: list[str],
    working_file_url: str | None,
    working_file_label: str | None,
    submitted_by: str,
    deadline: str | None = None,
) -> ComboApproval:
    """Submit a combo for approval. Creates combo_approval + reviewer rows + notifications."""
    combo = db.query(AdCombo).filter(AdCombo.id == combo_id).first()
    if not combo:
        raise ValueError(f"Combo {combo_id} not found")

    if not reviewer_ids:
        raise ValueError("At least one reviewer is required")

    # Determine round number
    max_round = (
        db.query(func.max(ComboApproval.round))
        .filter(ComboApproval.combo_id == combo_id)
        .scalar()
    )
    round_num = (max_round or 0) + 1

    now = datetime.now(timezone.utc)

    # Parse deadline
    parsed_deadline = None
    if deadline:
        from datetime import datetime as dt_cls
        try:
            parsed_deadline = dt_cls.fromisoformat(deadline)
        except (ValueError, TypeError):
            pass

    approval = ComboApproval(
        combo_id=combo_id,
        round=round_num,
        status="PENDING_APPROVAL",
        submitted_by=submitted_by,
        submitted_at=now,
        deadline=parsed_deadline,
        working_file_url=working_file_url,
        working_file_label=working_file_label,
    )
    db.add(approval)
    db.flush()  # Get approval.id

    submitter = db.query(User).filter(User.id == submitted_by).first()
    submitter_name = submitter.full_name if submitter else "Unknown"
    combo_name = combo.ad_name or combo.combo_id

    # Create reviewer rows + notifications
    email_tasks = []
    for rid in reviewer_ids:
        reviewer_row = ApprovalReviewer(
            approval_id=approval.id,
            reviewer_id=rid,
            status="PENDING",
            notified_system_at=now,
        )
        db.add(reviewer_row)

        # In-system notification
        create_notification(
            db,
            user_id=rid,
            type="REVIEW_REQUESTED",
            title=f"Review requested: {combo_name}",
            body=f"{submitter_name} submitted {combo_name} for your review.",
            reference_id=approval.id,
            reference_type="combo_approval",
        )

        # Queue email (collect info, send after commit)
        reviewer = db.query(User).filter(User.id == rid).first()
        if reviewer and reviewer.notification_email:
            subject, html = render_review_request_email(
                combo_name=combo_name,
                reviewer_name=reviewer.full_name,
                submitter_name=submitter_name,
                working_file_url=working_file_url,
                approval_id=approval.id,
            )
            email_tasks.append((reviewer.email, subject, html))

    db.commit()

    # Send emails async via Celery (after commit so data is persisted)
    _queue_emails(email_tasks)

    return approval


def record_decision(
    db: Session,
    approval_id: str,
    reviewer_id: str,
    decision: str,
) -> ComboApproval:
    """Record a reviewer's decision (APPROVED or REJECTED).
    After each decision, check if all reviewers have decided and update approval status.
    """
    if decision not in ("APPROVED", "REJECTED"):
        raise ValueError("Decision must be APPROVED or REJECTED")

    approval = db.query(ComboApproval).filter(ComboApproval.id == approval_id).first()
    if not approval:
        raise ValueError("Approval not found")

    if approval.status != "PENDING_APPROVAL":
        raise ValueError(f"Approval is already {approval.status}")

    reviewer_row = (
        db.query(ApprovalReviewer)
        .filter(
            ApprovalReviewer.approval_id == approval_id,
            ApprovalReviewer.reviewer_id == reviewer_id,
        )
        .first()
    )
    if not reviewer_row:
        raise ValueError("You are not assigned as a reviewer for this approval")

    if reviewer_row.status != "PENDING":
        raise ValueError(f"You have already decided: {reviewer_row.status}")

    now = datetime.now(timezone.utc)
    reviewer_row.status = decision
    reviewer_row.decided_at = now

    # Check all reviewers' decisions
    all_reviewers = (
        db.query(ApprovalReviewer)
        .filter(ApprovalReviewer.approval_id == approval_id)
        .all()
    )

    email_tasks = []

    # ANY rejected → REJECTED
    if decision == "REJECTED":
        approval.status = "REJECTED"
        approval.resolved_at = now
        _notify_creator_of_result(db, approval, "REJECTED", reviewer_id, email_tasks)
    else:
        # Check if ALL approved
        all_decided = all(r.status != "PENDING" for r in all_reviewers)
        all_approved = all(r.status == "APPROVED" for r in all_reviewers)

        if all_decided and all_approved:
            approval.status = "APPROVED"
            approval.resolved_at = now
            _notify_creator_of_result(db, approval, "APPROVED", None, email_tasks)

    db.commit()
    _queue_emails(email_tasks)
    return approval


def resubmit(
    db: Session,
    approval_id: str,
    reviewer_ids: list[str],
    working_file_url: str | None,
    working_file_label: str | None,
    creator_id: str,
    deadline: str | None = None,
) -> ComboApproval:
    """Re-submit a rejected approval. Creates a new round."""
    old_approval = db.query(ComboApproval).filter(ComboApproval.id == approval_id).first()
    if not old_approval:
        raise ValueError("Approval not found")

    if old_approval.status != "REJECTED":
        raise ValueError("Only rejected approvals can be re-submitted")

    if old_approval.submitted_by != creator_id:
        raise ValueError("Only the original creator can re-submit")

    return submit_for_approval(
        db=db,
        combo_id=old_approval.combo_id,
        reviewer_ids=reviewer_ids,
        working_file_url=working_file_url or old_approval.working_file_url,
        working_file_label=working_file_label or old_approval.working_file_label,
        submitted_by=creator_id,
        deadline=deadline,
    )


def get_approval_detail(db: Session, approval_id: str) -> dict | None:
    """Get full approval detail including combo info and reviewer list."""
    approval = db.query(ComboApproval).filter(ComboApproval.id == approval_id).first()
    if not approval:
        return None

    combo = db.query(AdCombo).filter(AdCombo.id == approval.combo_id).first()
    submitter = db.query(User).filter(User.id == approval.submitted_by).first() if approval.submitted_by else None

    reviewers = (
        db.query(ApprovalReviewer)
        .filter(ApprovalReviewer.approval_id == approval_id)
        .all()
    )

    reviewer_list = []
    for r in reviewers:
        user = db.query(User).filter(User.id == r.reviewer_id).first()
        reviewer_list.append({
            "id": r.id,
            "reviewer_id": r.reviewer_id,
            "reviewer_name": user.full_name if user else "Unknown",
            "reviewer_email": user.email if user else None,
            "status": r.status,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        })

    # Fetch copy and material details for reviewer context
    copy_data = None
    material_data = None
    if combo:
        from app.models.ad_copy import AdCopy
        from app.models.ad_material import AdMaterial

        copy = db.query(AdCopy).filter(AdCopy.copy_id == combo.copy_id).first() if combo.copy_id else None
        material = db.query(AdMaterial).filter(AdMaterial.material_id == combo.material_id).first() if combo.material_id else None

        if copy:
            copy_data = {
                "copy_id": copy.copy_id,
                "headline": copy.headline,
                "body_text": copy.body_text,
                "cta": copy.cta,
                "language": copy.language,
                "target_audience": copy.target_audience,
                "derived_verdict": copy.derived_verdict,
            }
        if material:
            material_data = {
                "material_id": material.material_id,
                "material_type": material.material_type,
                "file_url": material.file_url,
                "description": material.description,
                "target_audience": material.target_audience,
                "derived_verdict": material.derived_verdict,
            }

    # Combo performance data
    combo_performance = None
    if combo:
        combo_performance = {
            "verdict": combo.verdict,
            "spend": float(combo.spend) if combo.spend else None,
            "impressions": combo.impressions,
            "clicks": combo.clicks,
            "conversions": combo.conversions,
            "revenue": float(combo.revenue) if combo.revenue else None,
            "roas": float(combo.roas) if combo.roas else None,
            "ctr": float(combo.ctr) if combo.ctr else None,
            "hook_rate": float(combo.hook_rate) if combo.hook_rate else None,
            "thruplay_rate": float(combo.thruplay_rate) if combo.thruplay_rate else None,
            "engagement_rate": float(combo.engagement_rate) if combo.engagement_rate else None,
            "target_audience": combo.target_audience,
            "keypoint_ids": combo.keypoint_ids,
            "angle_id": combo.angle_id,
        }

    return {
        "id": approval.id,
        "combo_id": approval.combo_id,
        "combo_name": combo.ad_name if combo else None,
        "combo_id_display": combo.combo_id if combo else None,
        "material_id": combo.material_id if combo else None,
        "copy_id": combo.copy_id if combo else None,
        "round": approval.round,
        "status": approval.status,
        "submitted_by": approval.submitted_by,
        "submitter_name": submitter.full_name if submitter else None,
        "submitted_at": approval.submitted_at.isoformat() if approval.submitted_at else None,
        "deadline": approval.deadline.isoformat() if approval.deadline else None,
        "resolved_at": approval.resolved_at.isoformat() if approval.resolved_at else None,
        "working_file_url": approval.working_file_url,
        "working_file_label": approval.working_file_label,
        "launch_status": approval.launch_status,
        "launch_meta_ad_id": approval.launch_meta_ad_id,
        "launched_at": approval.launched_at.isoformat() if approval.launched_at else None,
        "reviewers": reviewer_list,
        "copy": copy_data,
        "material": material_data,
        "performance": combo_performance,
    }


def _notify_creator_of_result(
    db: Session,
    approval: ComboApproval,
    event: str,
    rejector_id: str | None,
    email_tasks: list,
):
    """Create notification + queue email for the creator when approval resolves."""
    combo = db.query(AdCombo).filter(AdCombo.id == approval.combo_id).first()
    combo_name = combo.ad_name if combo else "Unknown"
    creator = db.query(User).filter(User.id == approval.submitted_by).first() if approval.submitted_by else None

    rejector_name = None
    if rejector_id:
        rejector = db.query(User).filter(User.id == rejector_id).first()
        rejector_name = rejector.full_name if rejector else None

    if event == "APPROVED":
        title = f"Approved: {combo_name}"
        body = f"{combo_name} has been fully approved. You can now launch it."
        notif_type = "COMBO_APPROVED"
    else:
        title = f"Rejected: {combo_name}"
        body = f"{combo_name} was rejected by {rejector_name or 'a reviewer'}. Check the working file for feedback."
        notif_type = "COMBO_REJECTED"

    if creator:
        create_notification(
            db,
            user_id=creator.id,
            type=notif_type,
            title=title,
            body=body,
            reference_id=approval.id,
            reference_type="combo_approval",
        )

        if creator.notification_email:
            subject, html = render_approval_result_email(
                combo_name=combo_name,
                creator_name=creator.full_name,
                event=event,
                reviewer_name=rejector_name,
                approval_id=approval.id,
            )
            email_tasks.append((creator.email, subject, html))


def _queue_emails(email_tasks: list):
    """Queue email sends via Celery task."""
    try:
        from app.tasks.email_tasks import send_email_task

        for to, subject, html in email_tasks:
            send_email_task.delay(to, subject, html)
    except Exception as e:
        logger.warning("Could not queue email tasks (Celery may not be running): %s", e)
