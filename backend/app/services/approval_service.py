import logging
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.approval import ApprovalReviewer, ComboApproval
from app.models.user import User
from app.services.canva_link_capture import capture_canva_link_from_approval
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

    branch = db.query(AdAccount).filter(AdAccount.id == combo.branch_id).first() if combo.branch_id else None
    branch_name = branch.account_name if branch else None

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
                branch_name=branch_name,
                deadline=parsed_deadline,
                platform_url=settings.FRONTEND_URL,
            )
            email_tasks.append((reviewer.email, subject, html))

    # Snapshot Canva working file → ad_materials at submit time so winning-ads
    # surfaces it immediately (no need to wait for APPROVED). Idempotent —
    # re-submits don't overwrite an already-captured URL.
    try:
        capture_canva_link_from_approval(db, approval)
    except Exception:
        logger.exception("Canva link capture failed at submit for approval %s", approval.id)

    db.commit()

    # Send emails async via Celery (after commit so data is persisted)
    _queue_emails(email_tasks)

    return approval


def record_decision(
    db: Session,
    approval_id: str,
    reviewer_id: str,
    decision: str,
    feedback: str | None = None,
) -> ComboApproval:
    """Record a reviewer's decision (APPROVED or REJECTED).
    After each decision, check if all reviewers have decided and update approval status.
    """
    if decision not in ("APPROVED", "REJECTED", "NEEDS_REVISION"):
        raise ValueError("Decision must be APPROVED, REJECTED, or NEEDS_REVISION")

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
    cleaned_feedback = (feedback or "").strip() or None
    if cleaned_feedback is not None:
        reviewer_row.feedback = cleaned_feedback

    # Check all reviewers' decisions
    all_reviewers = (
        db.query(ApprovalReviewer)
        .filter(ApprovalReviewer.approval_id == approval_id)
        .all()
    )

    email_tasks = []

    # ANY rejected → REJECTED (terminal); ANY needs-revision → NEEDS_REVISION
    # so the creator can revise without waiting for remaining reviewers
    if decision == "REJECTED":
        approval.status = "REJECTED"
        approval.resolved_at = now
        _notify_creator_of_result(db, approval, "REJECTED", reviewer_id, email_tasks)
    elif decision == "NEEDS_REVISION":
        approval.status = "NEEDS_REVISION"
        approval.resolved_at = now
        _notify_creator_of_result(db, approval, "NEEDS_REVISION", reviewer_id, email_tasks)
    else:
        # Check if ALL approved
        all_decided = all(r.status != "PENDING" for r in all_reviewers)
        all_approved = all(r.status == "APPROVED" for r in all_reviewers)

        if all_decided and all_approved:
            approval.status = "APPROVED"
            approval.resolved_at = now
            # Snapshot Canva working file → ad_materials so winning ads can
            # later be regenerated without losing the source link.
            try:
                capture_canva_link_from_approval(db, approval)
            except Exception:
                logger.exception("Canva link capture failed for approval %s", approval.id)
            _notify_creator_of_result(db, approval, "APPROVED", None, email_tasks)

    db.commit()
    _queue_emails(email_tasks)
    return approval


def revise_pending_approval(
    db: Session,
    approval_id: str,
    creator_id: str,
    working_file_url: str | None = None,
    working_file_label: str | None = None,
    deadline: str | None = None,
    angle_id: str | None = None,
    keypoint_ids: list[str] | None = None,
    reviewer_ids: list[str] | None = None,
) -> ComboApproval:
    """Edit a pending approval in place — bumps round, resets reviewers, re-notifies.

    Use case: creator gets verbal feedback before reviewers click through, fixes
    things directly. Same approval row stays (for URL stability); round bumps so
    history is implied; all reviewers reset to PENDING because content changed.

    Sentinel: pass empty string for working_file_url/working_file_label to clear,
    None to leave unchanged. Same for angle_id (empty string clears).
    """
    approval = db.query(ComboApproval).filter(ComboApproval.id == approval_id).first()
    if not approval:
        raise ValueError("Approval not found")

    if approval.status != "PENDING_APPROVAL":
        raise ValueError(
            f"Only PENDING_APPROVAL approvals can be revised in place; current status: {approval.status}"
        )

    if approval.submitted_by != creator_id:
        raise ValueError("Only the original creator can revise this approval")

    combo = db.query(AdCombo).filter(AdCombo.id == approval.combo_id).first()
    if not combo:
        raise ValueError("Combo not found")

    now = datetime.now(timezone.utc)

    # Bump round + refresh submission timestamp
    approval.round = (approval.round or 0) + 1
    approval.submitted_at = now

    if working_file_url is not None:
        approval.working_file_url = working_file_url or None
    if working_file_label is not None:
        approval.working_file_label = working_file_label or None
    if deadline is not None:
        from datetime import datetime as dt_cls
        if deadline:
            try:
                approval.deadline = dt_cls.fromisoformat(deadline)
            except (ValueError, TypeError):
                pass
        else:
            approval.deadline = None

    if angle_id is not None:
        combo.angle_id = angle_id or None
    if keypoint_ids is not None:
        combo.keypoint_ids = keypoint_ids or None

    # Reviewer set: replace if caller passed a non-empty list, else reset existing.
    existing = (
        db.query(ApprovalReviewer)
        .filter(ApprovalReviewer.approval_id == approval_id)
        .all()
    )

    if reviewer_ids:
        new_ids = set(reviewer_ids)
        if not new_ids:
            raise ValueError("At least one reviewer is required")
        existing_by_rid = {r.reviewer_id: r for r in existing}

        for rid, row in existing_by_rid.items():
            if rid not in new_ids:
                db.delete(row)
            else:
                row.status = "PENDING"
                row.decided_at = None
                row.feedback = None
                row.notified_email_at = None
                row.notified_system_at = now

        for rid in new_ids - set(existing_by_rid.keys()):
            db.add(ApprovalReviewer(
                approval_id=approval.id,
                reviewer_id=rid,
                status="PENDING",
                notified_system_at=now,
            ))
    else:
        for r in existing:
            r.status = "PENDING"
            r.decided_at = None
            r.feedback = None
            r.notified_email_at = None
            r.notified_system_at = now

    db.flush()

    submitter = db.query(User).filter(User.id == creator_id).first()
    submitter_name = submitter.full_name if submitter else "Unknown"
    combo_name = combo.ad_name or combo.combo_id
    branch = db.query(AdAccount).filter(AdAccount.id == combo.branch_id).first() if combo.branch_id else None
    branch_name = branch.account_name if branch else None

    # Re-snapshot Canva working file → ad_materials (idempotent)
    try:
        capture_canva_link_from_approval(db, approval)
    except Exception:
        logger.exception("Canva link capture failed at revise for approval %s", approval.id)

    pending_reviewers = (
        db.query(ApprovalReviewer)
        .filter(
            ApprovalReviewer.approval_id == approval.id,
            ApprovalReviewer.status == "PENDING",
        )
        .all()
    )

    email_tasks = []
    for ar in pending_reviewers:
        reviewer = db.query(User).filter(User.id == ar.reviewer_id).first()
        if not reviewer:
            continue
        create_notification(
            db,
            user_id=ar.reviewer_id,
            type="REVIEW_REQUESTED",
            title=f"Revised — please re-review: {combo_name}",
            body=f"{submitter_name} updated {combo_name} (round {approval.round}). Please re-review.",
            reference_id=approval.id,
            reference_type="combo_approval",
        )
        if reviewer.notification_email and reviewer.email:
            subject, html = render_review_request_email(
                combo_name=combo_name,
                reviewer_name=reviewer.full_name,
                submitter_name=submitter_name,
                working_file_url=approval.working_file_url,
                approval_id=approval.id,
                branch_name=branch_name,
                deadline=approval.deadline,
                platform_url=settings.FRONTEND_URL,
            )
            email_tasks.append((reviewer.email, subject, html))
            ar.notified_email_at = now

    db.commit()
    _queue_emails(email_tasks)
    return approval


def resubmit(
    db: Session,
    approval_id: str,
    reviewer_ids: list[str] | None,
    working_file_url: str | None,
    working_file_label: str | None,
    creator_id: str,
    deadline: str | None = None,
) -> ComboApproval:
    """Re-submit an approval after rejection or revision request. New round."""
    old_approval = db.query(ComboApproval).filter(ComboApproval.id == approval_id).first()
    if not old_approval:
        raise ValueError("Approval not found")

    if old_approval.status not in ("REJECTED", "NEEDS_REVISION"):
        raise ValueError("Only rejected or needs-revision approvals can be re-submitted")

    if old_approval.submitted_by != creator_id:
        raise ValueError("Only the original creator can re-submit")

    # Default to the previous round's reviewers when caller doesn't pass any.
    if not reviewer_ids:
        reviewer_ids = [
            r.reviewer_id for r in db.query(ApprovalReviewer)
            .filter(ApprovalReviewer.approval_id == old_approval.id)
            .all()
        ]
        if not reviewer_ids:
            raise ValueError("No previous reviewers to inherit; specify reviewer_ids")

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
            "feedback": r.feedback,
        })

    # Fetch copy, material, branch, angle, keypoints for reviewer context
    copy_data = None
    material_data = None
    branch_data = None
    angle_data = None
    keypoint_list: list[dict] = []
    if combo:
        from app.models.account import AdAccount
        from app.models.ad_angle import AdAngle
        from app.models.ad_copy import AdCopy
        from app.models.ad_material import AdMaterial
        from app.models.keypoint import BranchKeypoint

        copy = db.query(AdCopy).filter(AdCopy.copy_id == combo.copy_id).first() if combo.copy_id else None
        material = db.query(AdMaterial).filter(AdMaterial.material_id == combo.material_id).first() if combo.material_id else None
        branch = db.query(AdAccount).filter(AdAccount.id == combo.branch_id).first() if combo.branch_id else None

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
        if branch:
            branch_data = {
                "id": branch.id,
                "name": branch.account_name,
                "platform": branch.platform,
                "currency": branch.currency,
            }

        # Resolve keypoint titles + aggregate per-keypoint metrics (scoped to
        # the same branch as the combo, since keypoints are branch-specific).
        if combo.keypoint_ids:
            kps = (
                db.query(BranchKeypoint)
                .filter(BranchKeypoint.id.in_(combo.keypoint_ids))
                .all()
            )

            # Pull every combo on this branch that has any keypoint, then
            # bucket spend/revenue/conversions/clicks per keypoint id.
            branch_combos_with_kp = db.query(AdCombo).filter(
                AdCombo.branch_id == combo.branch_id,
                AdCombo.keypoint_ids.isnot(None),
            ).all()
            kp_metrics: dict[str, dict] = {}
            for c in branch_combos_with_kp:
                ids = c.keypoint_ids if isinstance(c.keypoint_ids, list) else []
                for kid in ids:
                    if kid not in kp_metrics:
                        kp_metrics[kid] = {"combos": 0, "spend": 0.0, "revenue": 0.0, "clicks": 0, "conversions": 0}
                    m = kp_metrics[kid]
                    m["combos"] += 1
                    m["spend"] += float(c.spend or 0)
                    m["revenue"] += float(c.revenue or 0)
                    m["clicks"] += int(c.clicks or 0)
                    m["conversions"] += int(c.conversions or 0)

            # Branch benchmark for keypoint verdicts (reuse if angle block already
            # computed it; otherwise compute here so this block is independent).
            kp_branch_combos = db.query(AdCombo).filter(AdCombo.branch_id == combo.branch_id).all()
            kp_b_spend = sum(float(c.spend or 0) for c in kp_branch_combos)
            kp_b_rev = sum(float(c.revenue or 0) for c in kp_branch_combos)
            kp_branch_benchmark = kp_b_rev / kp_b_spend if kp_b_spend > 0 else 0.0

            from app.services.creative_service import classify_verdict
            for k in kps:
                m = kp_metrics.get(k.id, {"combos": 0, "spend": 0.0, "revenue": 0.0, "clicks": 0, "conversions": 0})
                kp_roas = m["revenue"] / m["spend"] if m["spend"] > 0 else 0.0
                kp_verdict = (
                    classify_verdict(m["clicks"], m["conversions"], kp_roas, kp_branch_benchmark)
                    if m["combos"] > 0 else "TEST"
                )
                keypoint_list.append({
                    "id": k.id,
                    "title": k.title,
                    "category": k.category,
                    "combos": m["combos"],
                    "spend": m["spend"],
                    "roas": kp_roas,
                    "conversions": m["conversions"],
                    "branch_verdict": kp_verdict,
                })

        # Angle context — angles are global (branch_id=NULL), so we scope the
        # aggregated ROAS to the current combo's branch to mirror what the
        # /angles list page shows next to each angle row.
        if combo.angle_id:
            angle = db.query(AdAngle).filter(AdAngle.angle_id == combo.angle_id).first()
            if angle:
                branch_combos_for_angle = db.query(AdCombo).filter(
                    AdCombo.angle_id == combo.angle_id,
                    AdCombo.branch_id == combo.branch_id,
                ).all()
                ang_spend = sum(float(c.spend or 0) for c in branch_combos_for_angle)
                ang_revenue = sum(float(c.revenue or 0) for c in branch_combos_for_angle)
                ang_clicks = sum(int(c.clicks or 0) for c in branch_combos_for_angle)
                ang_conversions = sum(int(c.conversions or 0) for c in branch_combos_for_angle)
                ang_roas = ang_revenue / ang_spend if ang_spend > 0 else 0.0

                # Branch benchmark = total branch revenue / total branch spend
                branch_combos = db.query(AdCombo).filter(AdCombo.branch_id == combo.branch_id).all()
                b_spend = sum(float(c.spend or 0) for c in branch_combos)
                b_rev = sum(float(c.revenue or 0) for c in branch_combos)
                branch_benchmark = b_rev / b_spend if b_spend > 0 else 0.0

                if ang_clicks <= 9000 and ang_conversions < 10:
                    branch_verdict = "TEST"
                elif branch_benchmark > 0 and ang_roas >= branch_benchmark:
                    branch_verdict = "WIN"
                else:
                    branch_verdict = "LOSE"

                angle_data = {
                    "angle_id": angle.angle_id,
                    "angle_type": angle.angle_type or angle.hook or "",
                    "angle_explain": angle.angle_explain or "",
                    "hook_examples": angle.hook_examples or [],
                    "status": angle.status,
                    "branch_verdict": branch_verdict,
                    "branch_benchmark": branch_benchmark,
                    "combos": len(branch_combos_for_angle),
                    "spend": ang_spend,
                    "revenue": ang_revenue,
                    "roas": ang_roas,
                    "conversions": ang_conversions,
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
            "country": combo.country,
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
        "branch": branch_data,
        "angle": angle_data,
        "keypoints": keypoint_list,
    }


def resend_review_request_emails(
    db: Session,
    approval_id: str,
    requester_id: str,
) -> dict:
    """Resend the review-request email to every reviewer still PENDING.

    Only the original creator or an admin should call this; we enforce that
    here so the router stays thin.
    """
    approval = db.query(ComboApproval).filter(ComboApproval.id == approval_id).first()
    if not approval:
        raise ValueError("Approval not found")

    if approval.status != "PENDING_APPROVAL":
        raise ValueError(f"Approval is {approval.status}; only PENDING_APPROVAL can be resent")

    requester = db.query(User).filter(User.id == requester_id).first()
    requester_roles = (requester.roles if requester else None) or []
    if "admin" not in requester_roles and approval.submitted_by != requester_id:
        raise ValueError("Only the creator or an admin can resend review requests")

    combo = db.query(AdCombo).filter(AdCombo.id == approval.combo_id).first()
    if not combo:
        raise ValueError("Combo not found")

    submitter = db.query(User).filter(User.id == approval.submitted_by).first() if approval.submitted_by else None
    submitter_name = submitter.full_name if submitter else "Unknown"
    combo_name = combo.ad_name or combo.combo_id

    branch = db.query(AdAccount).filter(AdAccount.id == combo.branch_id).first() if combo.branch_id else None
    branch_name = branch.account_name if branch else None

    pending_reviewers = (
        db.query(ApprovalReviewer)
        .filter(
            ApprovalReviewer.approval_id == approval_id,
            ApprovalReviewer.status == "PENDING",
        )
        .all()
    )

    email_tasks = []
    queued: list[dict] = []
    skipped: list[dict] = []
    now = datetime.now(timezone.utc)

    for ar in pending_reviewers:
        reviewer = db.query(User).filter(User.id == ar.reviewer_id).first()
        if not reviewer:
            skipped.append({"reviewer_id": ar.reviewer_id, "reason": "user not found"})
            continue
        if not reviewer.notification_email:
            skipped.append({"reviewer_id": ar.reviewer_id, "reason": "notification_email opt-out"})
            continue
        if not reviewer.email:
            skipped.append({"reviewer_id": ar.reviewer_id, "reason": "no email on user record"})
            continue

        subject, html = render_review_request_email(
            combo_name=combo_name,
            reviewer_name=reviewer.full_name,
            submitter_name=submitter_name,
            working_file_url=approval.working_file_url,
            approval_id=approval.id,
            branch_name=branch_name,
            deadline=approval.deadline,
            platform_url=settings.FRONTEND_URL,
        )
        email_tasks.append((reviewer.email, subject, html))
        ar.notified_email_at = now
        queued.append({"reviewer_id": ar.reviewer_id, "email": reviewer.email})

    db.commit()
    _queue_emails(email_tasks)

    return {
        "approval_id": approval_id,
        "queued_count": len(queued),
        "queued": queued,
        "skipped": skipped,
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

    branch_name = None
    if combo and combo.branch_id:
        branch = db.query(AdAccount).filter(AdAccount.id == combo.branch_id).first()
        branch_name = branch.account_name if branch else None

    rejector_name = None
    if rejector_id:
        rejector = db.query(User).filter(User.id == rejector_id).first()
        rejector_name = rejector.full_name if rejector else None

    if event == "APPROVED":
        title = f"Approved: {combo_name}"
        body = f"{combo_name} has been fully approved. You can now launch it."
        notif_type = "COMBO_APPROVED"
    elif event == "NEEDS_REVISION":
        title = f"Needs revision: {combo_name}"
        body = (
            f"{rejector_name or 'A reviewer'} asked for changes on {combo_name}. "
            "Open the approval, revise the working file, then submit a new round."
        )
        notif_type = "COMBO_NEEDS_REVISION"
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
                branch_name=branch_name,
                platform_url=settings.FRONTEND_URL,
            )
            email_tasks.append((creator.email, subject, html))


def _queue_emails(email_tasks: list):
    """Send emails out-of-band so the API response isn't blocked.

    Production runs on Zeabur cron (no Celery/Redis); we fire-and-forget
    via a daemon thread so the request returns immediately. Calling
    Celery's .delay() here would block on broker-connection retries
    against the now-removed Redis instance.
    """
    if not email_tasks:
        return

    import threading

    from app.services.email_service import send_email

    def _send_all():
        for to, subject, html in email_tasks:
            try:
                send_email(to, subject, html)
            except Exception:
                logger.exception("Failed to send email to %s: %s", to, subject)

    threading.Thread(target=_send_all, daemon=True).start()
