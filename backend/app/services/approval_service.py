import logging
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.approval import ApprovalBatch, ApprovalReviewer, ComboApproval
from app.models.user import User
from app.services.email_service import render_approval_result_email, render_review_request_email
from app.services.figma_service import ensure_template_from_url
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
    note: str | None = None,
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
        note=(note or "").strip() or None,
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

    db.commit()

    # Auto-register the working Figma frame as a reusable template so it
    # shows up in /winning-ads/templates and future briefs can pick it up.
    # Idempotent: skipped if the URL isn't a Figma link or the same
    # (file_key, node_id) is already registered. Wrapped — a Figma hiccup
    # must NEVER block an approval submission.
    if working_file_url:
        try:
            ensure_template_from_url(
                db,
                figma_url=working_file_url,
                branch_id=combo.branch_id,
                name=combo_name,
                created_by=submitted_by,
            )
        except Exception:
            logger.exception("Auto-template registration failed for combo %s", combo_id)

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
            _notify_creator_of_result(db, approval, "APPROVED", None, email_tasks)

    db.commit()

    # If this decision pushed the combo to fully APPROVED and the approval
    # carried a Figma working file, queue a render job that pushes the approved
    # copy into that exact frame. The approval outcome is already committed
    # above, so a Figma hiccup here can never change it.
    if approval.status == "APPROVED":
        try:
            _auto_queue_figma_render(db, approval)
        except Exception:
            logger.exception(
                "Auto-queue Figma render on approval failed for %s", approval_id
            )

    _queue_emails(email_tasks)
    return approval


# Branch-manager screenshots are stored inline as base64 data URLs (no blob
# storage in this app). Cap the payload so a stray huge image can't bloat the
# row / response. ~8M chars of base64 ≈ 6 MB of binary — plenty for a chat
# screenshot.
_MAX_PROOF_IMAGE_CHARS = 8_000_000


def _validate_proof_image(proof_image: str | None) -> str:
    """Validate a pasted screenshot data URL; return it trimmed.

    Must be a non-empty `data:image/...;base64,...` URL within the size cap.
    """
    cleaned = (proof_image or "").strip()
    if not cleaned:
        raise ValueError("A screenshot of the branch-manager approval is required")
    if not cleaned.startswith("data:image/"):
        raise ValueError("Proof must be a pasted/uploaded image")
    if len(cleaned) > _MAX_PROOF_IMAGE_CHARS:
        raise ValueError("Screenshot is too large; please paste a smaller image")
    return cleaned


def record_branch_manager_approval(
    db: Session,
    approval_id: str,
    actor_id: str,
    proof_image: str,
) -> ComboApproval:
    """Record a branch-manager sign-off (done offline) with a screenshot as
    proof, and mark the combo APPROVED immediately — bypassing the reviewer
    round. The status transition is server-enforced.

    Only works while the approval is still open (PENDING_APPROVAL or
    NEEDS_REVISION); already-resolved approvals are rejected so this can't
    silently overwrite a real reviewer verdict.
    """
    proof = _validate_proof_image(proof_image)

    approval = db.query(ComboApproval).filter(ComboApproval.id == approval_id).first()
    if not approval:
        raise ValueError("Approval not found")

    if approval.status not in ("PENDING_APPROVAL", "NEEDS_REVISION"):
        raise ValueError(
            f"Approval is already {approval.status}; branch-manager approval only "
            "applies while it's still open"
        )

    now = datetime.now(timezone.utc)
    approval.status = "APPROVED"
    approval.resolved_at = now
    approval.bm_approved_at = now
    approval.bm_approved_by = actor_id
    approval.bm_proof_image = proof

    email_tasks: list = []
    _notify_creator_of_result(db, approval, "APPROVED", None, email_tasks)

    db.commit()

    # Mirror record_decision: on full approval with a Figma working file, queue
    # the render. Best-effort — the approval is already committed.
    try:
        _auto_queue_figma_render(db, approval)
    except Exception:
        logger.exception(
            "Auto-queue Figma render on branch-manager approval failed for %s",
            approval_id,
        )

    _queue_emails(email_tasks)
    return approval


def record_batch_branch_manager_approval(
    db: Session,
    batch_id: str,
    actor_id: str,
    proof_image: str,
) -> ApprovalBatch:
    """Apply a branch-manager sign-off to every version of a batch at once
    (all-or-nothing), mirroring record_batch_decision's APPROVED path. The same
    screenshot is stored on each child as the shared proof.
    """
    proof = _validate_proof_image(proof_image)

    batch = db.query(ApprovalBatch).filter(ApprovalBatch.id == batch_id).first()
    if not batch:
        raise ValueError("Batch not found")

    children = (
        db.query(ComboApproval)
        .filter(ComboApproval.batch_id == batch_id)
        .all()
    )
    if not children:
        raise ValueError("Batch has no versions")

    current_status = _rollup_batch_status([c.status for c in children])
    if current_status not in ("PENDING_APPROVAL", "NEEDS_REVISION"):
        raise ValueError(
            f"Batch is already {current_status}; branch-manager approval only "
            "applies while it's still open"
        )

    now = datetime.now(timezone.utc)
    for child in children:
        child.status = "APPROVED"
        child.resolved_at = now
        child.bm_approved_at = now
        child.bm_approved_by = actor_id
        child.bm_proof_image = proof

    email_tasks: list = []
    _notify_creator_of_batch_result(db, batch, children, "APPROVED", None, email_tasks)

    db.commit()

    for child in children:
        try:
            _auto_queue_figma_render(db, child)
        except Exception:
            logger.exception(
                "Auto-queue Figma render on batch branch-manager approval failed for %s",
                child.id,
            )

    _queue_emails(email_tasks)
    return batch


def _apply_combo_content_edits(
    db: Session,
    combo: AdCombo,
    *,
    angle_id: str | None = None,
    keypoint_ids: list[str] | None = None,
    headline: str | None = None,
    body_text: str | None = None,
    cta: str | None = None,
    language: str | None = None,
    target_audience: str | None = None,
) -> None:
    """Apply angle / keypoint / copy edits onto a combo in place (no commit).

    Shared by single-approval and batch revise. Sentinel: None leaves a field
    unchanged; empty string clears angle_id / keypoint_ids.

    Copy edits clone-on-shared: if the linked AdCopy is used by more than one
    combo, a fresh copy_id is cloned and the combo re-pointed so the change does
    not leak; if exclusive, edited in place.
    """
    if angle_id is not None:
        combo.angle_id = angle_id or None
    if keypoint_ids is not None:
        combo.keypoint_ids = keypoint_ids or None

    copy_fields_changed = any(
        x is not None for x in (headline, body_text, cta, language, target_audience)
    )
    if not copy_fields_changed:
        return

    from app.models.ad_copy import AdCopy
    from app.services.creative_service import next_copy_id

    copy = db.query(AdCopy).filter(AdCopy.copy_id == combo.copy_id).first()
    if not copy:
        return

    shared_count = db.query(AdCombo).filter(AdCombo.copy_id == combo.copy_id).count()
    if shared_count > 1:
        new_id = next_copy_id(db)
        clone = AdCopy(
            branch_id=copy.branch_id,
            copy_id=new_id,
            target_audience=target_audience if target_audience is not None else copy.target_audience,
            angle_id=copy.angle_id,
            headline=headline if headline is not None else copy.headline,
            body_text=body_text if body_text is not None else copy.body_text,
            cta=(cta if cta is not None else copy.cta) or None,
            language=language if language is not None else copy.language,
        )
        db.add(clone)
        db.flush()
        combo.copy_id = new_id
    else:
        if headline is not None:
            copy.headline = headline
        if body_text is not None:
            copy.body_text = body_text
        if cta is not None:
            copy.cta = cta or None
        if language is not None:
            copy.language = language
        if target_audience is not None:
            copy.target_audience = target_audience


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
    headline: str | None = None,
    body_text: str | None = None,
    cta: str | None = None,
    language: str | None = None,
    target_audience: str | None = None,
) -> ComboApproval:
    """Edit a pending approval in place — bumps round, resets reviewers, re-notifies.

    Use case: creator gets verbal feedback before reviewers click through, fixes
    things directly. Same approval row stays (for URL stability); round bumps so
    history is implied; all reviewers reset to PENDING because content changed.

    Copy edits (headline/body_text/cta/language/target_audience): if the linked
    AdCopy is shared with other combos, a fresh copy_id is cloned and the combo
    re-pointed so the change does not leak. If exclusive to this combo, edited
    in place.

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

    _apply_combo_content_edits(
        db,
        combo,
        angle_id=angle_id,
        keypoint_ids=keypoint_ids,
        headline=headline,
        body_text=body_text,
        cta=cta,
        language=language,
        target_audience=target_audience,
    )

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


def get_approvals_list_summary(db: Session, approvals: list[ComboApproval]) -> list[dict]:
    """Lightweight list rows for the Approvals table — batched, no per-row N+1.

    Only resolves what the list UI renders (combo name, submitter, reviewer
    name + status). Deliberately skips the heavy copy/material/branch/angle/
    keypoint aggregation that get_approval_detail does for the detail page.
    """
    if not approvals:
        return []

    approval_ids = [a.id for a in approvals]
    combo_ids = list({a.combo_id for a in approvals if a.combo_id})
    submitter_ids = {a.submitted_by for a in approvals if a.submitted_by}

    combos = (
        db.query(AdCombo).filter(AdCombo.id.in_(combo_ids)).all() if combo_ids else []
    )
    combo_by_id = {c.id: c for c in combos}

    reviewers = (
        db.query(ApprovalReviewer)
        .filter(ApprovalReviewer.approval_id.in_(approval_ids))
        .all()
    )
    reviewer_ids = {r.reviewer_id for r in reviewers}

    user_ids = submitter_ids | reviewer_ids
    users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
    user_by_id = {u.id: u for u in users}

    reviewers_by_approval: dict[str, list] = {}
    for r in reviewers:
        reviewers_by_approval.setdefault(r.approval_id, []).append(r)

    items = []
    for a in approvals:
        combo = combo_by_id.get(a.combo_id)
        submitter = user_by_id.get(a.submitted_by) if a.submitted_by else None
        reviewer_list = [
            {
                "reviewer_id": r.reviewer_id,
                "reviewer_name": (user_by_id.get(r.reviewer_id).full_name if user_by_id.get(r.reviewer_id) else "Unknown"),
                "status": r.status,
            }
            for r in reviewers_by_approval.get(a.id, [])
        ]
        items.append({
            "id": a.id,
            "batch_id": a.batch_id,
            "combo_id": a.combo_id,
            "combo_name": combo.ad_name if combo else None,
            "combo_id_display": combo.combo_id if combo else None,
            "round": a.round,
            "status": a.status,
            "submitted_by": a.submitted_by,
            "submitter_name": submitter.full_name if submitter else None,
            "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
            "deadline": a.deadline.isoformat() if a.deadline else None,
            "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
            # Proof image is intentionally omitted from the list (too heavy);
            # the timestamp is enough to badge a branch-manager-approved row.
            "bm_approved_at": a.bm_approved_at.isoformat() if a.bm_approved_at else None,
            "reviewers": reviewer_list,
        })
    return items


def _rollup_batch_status(child_statuses: list[str]) -> str:
    """Whole-batch status from its versions. ANY reject → REJECTED;
    ANY needs-revision → NEEDS_REVISION; ALL approved → APPROVED; else pending.
    Mirrors the single-approval terminal rules, applied across versions."""
    if any(s == "REJECTED" for s in child_statuses):
        return "REJECTED"
    if any(s == "NEEDS_REVISION" for s in child_statuses):
        return "NEEDS_REVISION"
    if child_statuses and all(s == "APPROVED" for s in child_statuses):
        return "APPROVED"
    return "PENDING_APPROVAL"


def submit_batch(
    db: Session,
    versions: list[dict],
    reviewer_ids: list[str],
    submitted_by: str,
    deadline: str | None = None,
    note: str | None = None,
) -> ApprovalBatch:
    """Submit N combo versions of one target as a single review batch.

    `versions` is a list of {combo_id, working_file_url?, working_file_label?}.
    Each becomes its own combo_approval (own launch lifecycle) sharing one
    batch_id + the same reviewer set. Reviewers get ONE consolidated
    request (notification + email) covering all versions, not one per version.
    """
    if not versions:
        raise ValueError("At least one version is required")
    if not reviewer_ids:
        raise ValueError("At least one reviewer is required")

    combo_ids = [v["combo_id"] for v in versions]
    combos = db.query(AdCombo).filter(AdCombo.id.in_(combo_ids)).all()
    combo_by_id = {c.id: c for c in combos}
    missing = [cid for cid in combo_ids if cid not in combo_by_id]
    if missing:
        raise ValueError(f"Combo(s) not found: {', '.join(missing)}")

    now = datetime.now(timezone.utc)

    parsed_deadline = None
    if deadline:
        from datetime import datetime as dt_cls
        try:
            parsed_deadline = dt_cls.fromisoformat(deadline)
        except (ValueError, TypeError):
            pass

    batch = ApprovalBatch(
        submitted_by=submitted_by,
        round=1,
        submitted_at=now,
        deadline=parsed_deadline,
        note=(note or "").strip() or None,
    )
    db.add(batch)
    db.flush()  # batch.id

    # Create one combo_approval per version, each carrying the same reviewer set.
    child_approvals = []
    for v in versions:
        combo = combo_by_id[v["combo_id"]]
        max_round = (
            db.query(func.max(ComboApproval.round))
            .filter(ComboApproval.combo_id == combo.id)
            .scalar()
        )
        approval = ComboApproval(
            batch_id=batch.id,
            combo_id=combo.id,
            round=(max_round or 0) + 1,
            status="PENDING_APPROVAL",
            submitted_by=submitted_by,
            submitted_at=now,
            deadline=parsed_deadline,
            working_file_url=v.get("working_file_url"),
            working_file_label=v.get("working_file_label"),
            note=(note or "").strip() or None,
        )
        db.add(approval)
        db.flush()
        child_approvals.append((approval, combo))

        for rid in reviewer_ids:
            db.add(ApprovalReviewer(
                approval_id=approval.id,
                reviewer_id=rid,
                status="PENDING",
                notified_system_at=now,
            ))

    submitter = db.query(User).filter(User.id == submitted_by).first()
    submitter_name = submitter.full_name if submitter else "Unknown"

    version_count = len(child_approvals)
    first_combo = child_approvals[0][1]
    first_name = first_combo.ad_name or first_combo.combo_id
    batch_label = (
        first_name if version_count == 1
        else f"{first_name} (+{version_count - 1} more)"
    )
    branch = (
        db.query(AdAccount).filter(AdAccount.id == first_combo.branch_id).first()
        if first_combo.branch_id else None
    )
    branch_name = branch.account_name if branch else None

    # One consolidated notification + email per reviewer.
    email_tasks = []
    for rid in reviewer_ids:
        create_notification(
            db,
            user_id=rid,
            type="REVIEW_REQUESTED",
            title=f"Review requested: {batch_label}",
            body=(
                f"{submitter_name} submitted {version_count} "
                f"version{'s' if version_count != 1 else ''} for your review."
            ),
            reference_id=batch.id,
            reference_type="approval_batch",
        )
        reviewer = db.query(User).filter(User.id == rid).first()
        if reviewer and reviewer.notification_email:
            subject, html = render_review_request_email(
                combo_name=batch_label,
                reviewer_name=reviewer.full_name,
                submitter_name=submitter_name,
                working_file_url=child_approvals[0][0].working_file_url,
                approval_id=batch.id,
                branch_name=branch_name,
                deadline=parsed_deadline,
                platform_url=settings.FRONTEND_URL,
            )
            email_tasks.append((reviewer.email, subject, html))

    db.commit()

    # Auto-register each version's Figma working file as a reusable template.
    # Idempotent + best-effort: a Figma hiccup must never block submission.
    for approval, combo in child_approvals:
        if approval.working_file_url:
            try:
                ensure_template_from_url(
                    db,
                    figma_url=approval.working_file_url,
                    branch_id=combo.branch_id,
                    name=combo.ad_name or combo.combo_id,
                    created_by=submitted_by,
                )
            except Exception:
                logger.exception("Auto-template registration failed for combo %s", combo.id)

    _queue_emails(email_tasks)
    return batch


def record_batch_decision(
    db: Session,
    batch_id: str,
    reviewer_id: str,
    decision: str,
    feedback: str | None = None,
) -> ApprovalBatch:
    """Apply ONE reviewer decision to every version in a batch (all-or-nothing).

    The reviewer decides the batch as a whole; we write that decision onto
    their reviewer row for each version, then roll up each version's status
    with the same rules as a single approval. The creator gets ONE
    consolidated result notification.
    """
    if decision not in ("APPROVED", "REJECTED", "NEEDS_REVISION"):
        raise ValueError("Decision must be APPROVED, REJECTED, or NEEDS_REVISION")

    batch = db.query(ApprovalBatch).filter(ApprovalBatch.id == batch_id).first()
    if not batch:
        raise ValueError("Batch not found")

    children = (
        db.query(ComboApproval)
        .filter(ComboApproval.batch_id == batch_id)
        .all()
    )
    if not children:
        raise ValueError("Batch has no versions")

    current_status = _rollup_batch_status([c.status for c in children])
    if current_status != "PENDING_APPROVAL":
        raise ValueError(f"Batch is already {current_status}")

    child_ids = [c.id for c in children]
    my_rows = (
        db.query(ApprovalReviewer)
        .filter(
            ApprovalReviewer.approval_id.in_(child_ids),
            ApprovalReviewer.reviewer_id == reviewer_id,
        )
        .all()
    )
    if not my_rows:
        raise ValueError("You are not assigned as a reviewer for this batch")
    if any(r.status != "PENDING" for r in my_rows):
        raise ValueError("You have already decided on this batch")

    now = datetime.now(timezone.utc)
    cleaned_feedback = (feedback or "").strip() or None

    # Write this reviewer's decision on every version.
    for r in my_rows:
        r.status = decision
        r.decided_at = now
        if cleaned_feedback is not None:
            r.feedback = cleaned_feedback

    # Roll up each version's status.
    all_reviewers = (
        db.query(ApprovalReviewer)
        .filter(ApprovalReviewer.approval_id.in_(child_ids))
        .all()
    )
    reviewers_by_child: dict[str, list] = {}
    for r in all_reviewers:
        reviewers_by_child.setdefault(r.approval_id, []).append(r)

    for child in children:
        rows = reviewers_by_child.get(child.id, [])
        if decision == "REJECTED":
            child.status = "REJECTED"
            child.resolved_at = now
        elif decision == "NEEDS_REVISION":
            child.status = "NEEDS_REVISION"
            child.resolved_at = now
        else:
            if rows and all(x.status == "APPROVED" for x in rows):
                child.status = "APPROVED"
                child.resolved_at = now

    batch_status = _rollup_batch_status([c.status for c in children])

    email_tasks = []
    if batch_status != "PENDING_APPROVAL":
        _notify_creator_of_batch_result(
            db, batch, children, batch_status, reviewer_id, email_tasks
        )

    db.commit()

    # Per approved version, queue its Figma render (outcome already committed).
    if batch_status == "APPROVED":
        for child in children:
            if child.status == "APPROVED":
                try:
                    _auto_queue_figma_render(db, child)
                except Exception:
                    logger.exception(
                        "Auto-queue Figma render on batch approval failed for %s", child.id
                    )

    _queue_emails(email_tasks)
    return batch


def revise_batch(
    db: Session,
    batch_id: str,
    creator_id: str,
    deadline: str | None = None,
    reviewer_ids: list[str] | None = None,
    versions: list[dict] | None = None,
) -> ApprovalBatch:
    """Edit a pending or needs-revision batch in place — bumps the batch + every
    version's round, resets ALL reviewers + version statuses across the batch,
    re-notifies once (consolidated). For a NEEDS_REVISION batch this is the
    resubmit path: the whole batch re-opens at PENDING_APPROVAL.

    Mirrors revise_pending_approval but for the all-or-nothing batch flow: the
    batch re-opens as a whole, so a single round bump and one consolidated
    re-review request cover every version.

    `versions` is a list of per-version edit dicts keyed by `approval_id` (the
    child combo_approval id). Each may carry working_file_url / working_file_label
    and content edits (angle_id, keypoint_ids, headline, body_text, cta, language,
    target_audience). A version absent from the list keeps its content but still
    has its round bumped + reviewers reset. `deadline` and `reviewer_ids` are
    batch-wide. Sentinel: None leaves a field unchanged; empty string clears.
    """
    batch = db.query(ApprovalBatch).filter(ApprovalBatch.id == batch_id).first()
    if not batch:
        raise ValueError("Batch not found")

    if batch.submitted_by != creator_id:
        raise ValueError("Only the original creator can revise this batch")

    children = (
        db.query(ComboApproval)
        .filter(ComboApproval.batch_id == batch_id)
        .order_by(ComboApproval.created_at.asc())
        .all()
    )
    if not children:
        raise ValueError("Batch has no versions")

    current_status = _rollup_batch_status([c.status for c in children])
    if current_status not in ("PENDING_APPROVAL", "NEEDS_REVISION"):
        raise ValueError(
            f"Only pending or needs-revision batches can be revised; current status: {current_status}"
        )

    now = datetime.now(timezone.utc)

    # Parse batch-wide deadline once (None = leave unchanged, "" = clear).
    parsed_deadline = None
    clear_deadline = False
    if deadline is not None:
        if deadline:
            from datetime import datetime as dt_cls
            try:
                parsed_deadline = dt_cls.fromisoformat(deadline)
            except (ValueError, TypeError):
                parsed_deadline = None
                deadline = None  # unparseable → leave unchanged
        else:
            clear_deadline = True

    if parsed_deadline is not None:
        batch.deadline = parsed_deadline
    elif clear_deadline:
        batch.deadline = None

    batch.round = (batch.round or 0) + 1
    # Re-open the batch as a whole — a NEEDS_REVISION batch returns to review.
    batch.status = "PENDING_APPROVAL"
    batch.resolved_at = None

    edits_by_approval = {v["approval_id"]: v for v in (versions or []) if v.get("approval_id")}

    for child in children:
        combo = db.query(AdCombo).filter(AdCombo.id == child.combo_id).first()
        child.round = (child.round or 0) + 1
        child.submitted_at = now
        # Reset any prior terminal verdict so the rollup reflects the re-open.
        child.status = "PENDING_APPROVAL"
        child.resolved_at = None
        if parsed_deadline is not None:
            child.deadline = parsed_deadline
        elif clear_deadline:
            child.deadline = None

        edit = edits_by_approval.get(child.id)
        if edit and combo:
            if edit.get("working_file_url") is not None:
                child.working_file_url = edit["working_file_url"] or None
            if edit.get("working_file_label") is not None:
                child.working_file_label = edit["working_file_label"] or None
            _apply_combo_content_edits(
                db,
                combo,
                angle_id=edit.get("angle_id"),
                keypoint_ids=edit.get("keypoint_ids"),
                headline=edit.get("headline"),
                body_text=edit.get("body_text"),
                cta=edit.get("cta"),
                language=edit.get("language"),
                target_audience=edit.get("target_audience"),
            )

    # Reconcile reviewers across EVERY version so the batch stays consistent.
    child_ids = [c.id for c in children]
    existing = (
        db.query(ApprovalReviewer)
        .filter(ApprovalReviewer.approval_id.in_(child_ids))
        .all()
    )
    rows_by_child: dict[str, list] = {}
    for r in existing:
        rows_by_child.setdefault(r.approval_id, []).append(r)

    if reviewer_ids:
        new_ids = set(reviewer_ids)
        for child in children:
            by_rid = {r.reviewer_id: r for r in rows_by_child.get(child.id, [])}
            for rid, row in by_rid.items():
                if rid not in new_ids:
                    db.delete(row)
                else:
                    row.status = "PENDING"
                    row.decided_at = None
                    row.feedback = None
                    row.notified_email_at = None
                    row.notified_system_at = now
            for rid in new_ids - set(by_rid.keys()):
                db.add(ApprovalReviewer(
                    approval_id=child.id,
                    reviewer_id=rid,
                    status="PENDING",
                    notified_system_at=now,
                ))
        final_reviewer_ids = new_ids
    else:
        for r in existing:
            r.status = "PENDING"
            r.decided_at = None
            r.feedback = None
            r.notified_email_at = None
            r.notified_system_at = now
        final_reviewer_ids = {r.reviewer_id for r in existing}

    db.flush()

    # One consolidated re-review request per reviewer (mirrors submit_batch).
    submitter = db.query(User).filter(User.id == creator_id).first()
    submitter_name = submitter.full_name if submitter else "Unknown"
    version_count = len(children)
    first_combo = db.query(AdCombo).filter(AdCombo.id == children[0].combo_id).first()
    first_name = (
        (first_combo.ad_name or first_combo.combo_id) if first_combo else "your submission"
    )
    batch_label = (
        first_name if version_count == 1 else f"{first_name} (+{version_count - 1} more)"
    )
    branch = (
        db.query(AdAccount).filter(AdAccount.id == first_combo.branch_id).first()
        if first_combo and first_combo.branch_id else None
    )
    branch_name = branch.account_name if branch else None
    working_file_url = children[0].working_file_url

    email_tasks = []
    for rid in final_reviewer_ids:
        reviewer = db.query(User).filter(User.id == rid).first()
        if not reviewer:
            continue
        create_notification(
            db,
            user_id=rid,
            type="REVIEW_REQUESTED",
            title=f"Revised — please re-review: {batch_label}",
            body=(
                f"{submitter_name} updated {version_count} "
                f"version{'s' if version_count != 1 else ''} "
                f"(round {batch.round}). Please re-review."
            ),
            reference_id=batch.id,
            reference_type="approval_batch",
        )
        if reviewer.notification_email and reviewer.email:
            subject, html = render_review_request_email(
                combo_name=batch_label,
                reviewer_name=reviewer.full_name,
                submitter_name=submitter_name,
                working_file_url=working_file_url,
                approval_id=batch.id,
                branch_name=branch_name,
                deadline=batch.deadline,
                platform_url=settings.FRONTEND_URL,
            )
            email_tasks.append((reviewer.email, subject, html))
            for row in db.query(ApprovalReviewer).filter(
                ApprovalReviewer.approval_id.in_(child_ids),
                ApprovalReviewer.reviewer_id == rid,
            ).all():
                row.notified_email_at = now

    db.commit()
    _queue_emails(email_tasks)
    return batch


def _notify_creator_of_batch_result(
    db: Session,
    batch: ApprovalBatch,
    children: list[ComboApproval],
    event: str,
    actor_id: str | None,
    email_tasks: list,
):
    """One consolidated creator notification when a batch resolves."""
    creator = (
        db.query(User).filter(User.id == batch.submitted_by).first()
        if batch.submitted_by else None
    )
    if not creator:
        return

    count = len(children)
    first_combo = (
        db.query(AdCombo).filter(AdCombo.id == children[0].combo_id).first()
        if children else None
    )
    first_name = (first_combo.ad_name if first_combo else None) or "your submission"
    label = first_name if count == 1 else f"{first_name} (+{count - 1} more)"

    actor_name = None
    if actor_id:
        actor = db.query(User).filter(User.id == actor_id).first()
        actor_name = actor.full_name if actor else None

    if event == "APPROVED":
        title = f"Approved: {label}"
        body = f"All {count} version{'s' if count != 1 else ''} of {label} were approved. You can now launch them."
        notif_type = "COMBO_APPROVED"
    elif event == "NEEDS_REVISION":
        title = f"Needs revision: {label}"
        body = f"{actor_name or 'A reviewer'} asked for changes on {label}. Revise and submit a new round."
        notif_type = "COMBO_NEEDS_REVISION"
    else:
        title = f"Rejected: {label}"
        body = f"{label} was rejected by {actor_name or 'a reviewer'}. Check the working files for feedback."
        notif_type = "COMBO_REJECTED"

    create_notification(
        db,
        user_id=creator.id,
        type=notif_type,
        title=title,
        body=body,
        reference_id=batch.id,
        reference_type="approval_batch",
    )
    if creator.notification_email:
        subject, html = render_approval_result_email(
            combo_name=label,
            creator_name=creator.full_name,
            event=event,
            reviewer_name=actor_name,
            approval_id=batch.id,
            branch_name=None,
            platform_url=settings.FRONTEND_URL,
        )
        email_tasks.append((creator.email, subject, html))


def get_batch_detail(db: Session, batch_id: str) -> dict | None:
    """Full batch detail: shared metadata, batch-level reviewer states, and the
    full per-version detail for each combo_approval in the batch."""
    batch = db.query(ApprovalBatch).filter(ApprovalBatch.id == batch_id).first()
    if not batch:
        return None

    children = (
        db.query(ComboApproval)
        .filter(ComboApproval.batch_id == batch_id)
        .order_by(ComboApproval.created_at.asc())
        .all()
    )

    versions = []
    for child in children:
        detail = get_approval_detail(db, child.id)
        if detail:
            versions.append(detail)

    # Reviewer states are identical across versions (decision is applied to the
    # whole batch), so derive the batch-level reviewer list from the first one.
    reviewers = versions[0]["reviewers"] if versions else []

    submitter = (
        db.query(User).filter(User.id == batch.submitted_by).first()
        if batch.submitted_by else None
    )

    # Branch-manager proof is applied to the whole batch at once (same screenshot
    # on every child), so surface it once at batch level from the first version
    # that carries it.
    bm_version = next((v for v in versions if v.get("bm_approved_at")), None)

    return {
        "id": batch.id,
        "round": batch.round,
        "status": _rollup_batch_status([c.status for c in children]),
        "bm_approved_at": bm_version["bm_approved_at"] if bm_version else None,
        "bm_approved_by_name": bm_version["bm_approved_by_name"] if bm_version else None,
        "bm_proof_image": bm_version["bm_proof_image"] if bm_version else None,
        "submitted_by": batch.submitted_by,
        "submitter_name": submitter.full_name if submitter else None,
        "submitted_at": batch.submitted_at.isoformat() if batch.submitted_at else None,
        "deadline": batch.deadline.isoformat() if batch.deadline else None,
        "note": batch.note,
        "reviewers": reviewers,
        "versions": versions,
    }


def get_approval_detail(db: Session, approval_id: str) -> dict | None:
    """Get full approval detail including combo info and reviewer list."""
    approval = db.query(ComboApproval).filter(ComboApproval.id == approval_id).first()
    if not approval:
        return None

    combo = db.query(AdCombo).filter(AdCombo.id == approval.combo_id).first()
    submitter = db.query(User).filter(User.id == approval.submitted_by).first() if approval.submitted_by else None
    bm_approver = (
        db.query(User).filter(User.id == approval.bm_approved_by).first()
        if approval.bm_approved_by else None
    )

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
        "note": approval.note,
        "launch_status": approval.launch_status,
        "launch_meta_ad_id": approval.launch_meta_ad_id,
        "launched_at": approval.launched_at.isoformat() if approval.launched_at else None,
        "bm_approved_at": approval.bm_approved_at.isoformat() if approval.bm_approved_at else None,
        "bm_approved_by": approval.bm_approved_by,
        "bm_approved_by_name": bm_approver.full_name if bm_approver else None,
        "bm_proof_image": approval.bm_proof_image,
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


def resend_batch_review_request_emails(
    db: Session,
    batch_id: str,
    requester_id: str,
) -> dict:
    """Resend ONE consolidated review-request email per still-PENDING reviewer
    of a batch — mirrors submit_batch's one-email-per-reviewer behaviour rather
    than firing one email per version.

    Only the batch creator or an admin may call this.
    """
    batch = db.query(ApprovalBatch).filter(ApprovalBatch.id == batch_id).first()
    if not batch:
        raise ValueError("Batch not found")

    children = (
        db.query(ComboApproval).filter(ComboApproval.batch_id == batch_id).all()
    )
    if not children:
        raise ValueError("Batch has no versions")

    status = _rollup_batch_status([c.status for c in children])
    if status != "PENDING_APPROVAL":
        raise ValueError(f"Batch is {status}; only PENDING_APPROVAL can be resent")

    requester = db.query(User).filter(User.id == requester_id).first()
    requester_roles = (requester.roles if requester else None) or []
    if "admin" not in requester_roles and batch.submitted_by != requester_id:
        raise ValueError("Only the creator or an admin can resend review requests")

    child_ids = [c.id for c in children]
    version_count = len(children)
    first_combo = (
        db.query(AdCombo).filter(AdCombo.id == children[0].combo_id).first()
    )
    first_name = (
        (first_combo.ad_name or first_combo.combo_id) if first_combo else "your submission"
    )
    batch_label = (
        first_name if version_count == 1 else f"{first_name} (+{version_count - 1} more)"
    )
    branch = (
        db.query(AdAccount).filter(AdAccount.id == first_combo.branch_id).first()
        if first_combo and first_combo.branch_id else None
    )
    branch_name = branch.account_name if branch else None
    submitter = (
        db.query(User).filter(User.id == batch.submitted_by).first()
        if batch.submitted_by else None
    )
    submitter_name = submitter.full_name if submitter else "Unknown"
    working_file_url = children[0].working_file_url

    # Decisions apply to the whole batch, so a reviewer's PENDING rows span all
    # versions — group by reviewer and send a single email covering the batch.
    pending_rows = (
        db.query(ApprovalReviewer)
        .filter(
            ApprovalReviewer.approval_id.in_(child_ids),
            ApprovalReviewer.status == "PENDING",
        )
        .all()
    )
    rows_by_reviewer: dict[str, list] = {}
    for r in pending_rows:
        rows_by_reviewer.setdefault(r.reviewer_id, []).append(r)

    email_tasks = []
    queued: list[dict] = []
    skipped: list[dict] = []
    now = datetime.now(timezone.utc)

    for rid, rows in rows_by_reviewer.items():
        reviewer = db.query(User).filter(User.id == rid).first()
        if not reviewer:
            skipped.append({"reviewer_id": rid, "reason": "user not found"})
            continue
        if not reviewer.notification_email:
            skipped.append({"reviewer_id": rid, "reason": "notification_email opt-out"})
            continue
        if not reviewer.email:
            skipped.append({"reviewer_id": rid, "reason": "no email on user record"})
            continue

        subject, html = render_review_request_email(
            combo_name=batch_label,
            reviewer_name=reviewer.full_name,
            submitter_name=submitter_name,
            working_file_url=working_file_url,
            approval_id=batch.id,
            branch_name=branch_name,
            deadline=batch.deadline,
            platform_url=settings.FRONTEND_URL,
        )
        email_tasks.append((reviewer.email, subject, html))
        for row in rows:
            row.notified_email_at = now
        queued.append({"reviewer_id": rid, "email": reviewer.email})

    db.commit()
    _queue_emails(email_tasks)

    return {
        "batch_id": batch_id,
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


def _auto_queue_figma_render(db: Session, approval: ComboApproval) -> None:
    """On full approval, push the approved copy into the Figma frame shipped
    with this approval.

    Strict by design (per product decision): fires ONLY when the approval has a
    working_file_url pointing at a specific Figma frame — that frame was
    auto-registered as a template at submit time (see submit_for_approval).
    There is no branch-template fallback: we render the exact frame that was
    reviewed, never a guessed one. The queued job carries source_combo_id so the
    combo surfaces under the Figma list's "Figma only" filter. Skips silently
    when there's no Figma working file or no active template registered for it.
    """
    if not approval.working_file_url:
        return

    from app.models.figma import FigmaTemplate
    from app.services.figma_service import create_job, parse_figma_url

    file_key, node_id = parse_figma_url(approval.working_file_url)
    if not file_key or not node_id:
        return

    template = (
        db.query(FigmaTemplate)
        .filter(
            FigmaTemplate.file_key == file_key,
            FigmaTemplate.node_id == node_id,
            FigmaTemplate.is_active.is_(True),
        )
        .first()
    )
    if not template:
        return

    combo = db.query(AdCombo).filter(AdCombo.id == approval.combo_id).first()
    if not combo:
        return

    job = create_job(
        db,
        template_id=template.id,
        request_payload=_build_render_payload(db, combo),
        requested_by=approval.submitted_by,
        source_combo_id=combo.combo_id,
    )

    # create_job already committed the job. Notify the creator and commit the
    # notification on its own so neither write is lost.
    if approval.submitted_by:
        combo_name = combo.ad_name or combo.combo_id
        create_notification(
            db,
            user_id=approval.submitted_by,
            type="FIGMA_RENDER_QUEUED",
            title=f"Render job queued: {combo_name}",
            body=(
                f"{combo_name} was approved — a Figma render job (#{str(job.id)[:8]}) "
                f"was queued into template '{template.name}'. A designer runs the "
                f"MEANDER plugin to fill it."
            ),
            reference_id=approval.id,
            reference_type="combo_approval",
        )
        db.commit()


def _build_render_payload(db: Session, combo: AdCombo) -> dict:
    """Map an approved combo's copy + keypoints onto the common $-slot names a
    template might declare (headline/hook/title, subhead/body, cta, benefit_N).

    Over-supplies on purpose — create_job() drops any key the template doesn't
    declare, so each template just takes the slots it actually has.
    """
    from app.models.ad_copy import AdCopy
    from app.models.keypoint import BranchKeypoint

    payload: dict[str, str] = {}

    copy = (
        db.query(AdCopy).filter(AdCopy.copy_id == combo.copy_id).first()
        if combo.copy_id else None
    )
    if copy:
        if copy.headline:
            payload["headline"] = copy.headline
            payload["hook"] = copy.headline
            payload["title"] = copy.headline
        if copy.body_text:
            payload["subhead"] = copy.body_text
            payload["body"] = copy.body_text
        if copy.cta:
            payload["cta"] = copy.cta

    kp_ids = combo.keypoint_ids if isinstance(combo.keypoint_ids, list) else []
    if kp_ids:
        rows = db.query(BranchKeypoint).filter(BranchKeypoint.id.in_(kp_ids)).all()
        by_id = {k.id: k for k in rows}
        titles = [
            by_id[kid].title for kid in kp_ids
            if kid in by_id and by_id[kid].title
        ]
        for i, title in enumerate(titles, start=1):
            payload[f"benefit_{i}"] = title

    return payload


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
