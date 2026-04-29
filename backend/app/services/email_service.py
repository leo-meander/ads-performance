import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, html_body: str) -> bool:
    """Send an email via SMTP. Returns True on success, False on failure.

    This function should only be called from a Celery task — never block the API response.
    """
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning("SMTP not configured — skipping email to %s: %s", to, subject)
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_USER}>"
        msg["To"] = to
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)

        logger.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as e:
        logger.exception("Failed to send email to %s: %s — %s", to, subject, e)
        return False


def render_review_request_email(
    combo_name: str,
    reviewer_name: str,
    submitter_name: str,
    working_file_url: str | None,
    approval_id: str,
    platform_url: str = "",
) -> tuple[str, str]:
    """Render email for review request. Returns (subject, html_body)."""
    subject = f"[Action Required] Review Combo: {combo_name}"
    review_url = f"{platform_url}/approvals/{approval_id}"

    working_file_section = ""
    if working_file_url:
        working_file_section = f"""
        <p><a href="{working_file_url}"
               style="display:inline-block;padding:10px 20px;background:#f0f0f0;
                      border-radius:6px;color:#333;text-decoration:none;font-weight:bold;">
            Open Working File
        </a></p>
        """

    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
        <div style="background:#1e40af;color:white;padding:20px;border-radius:8px 8px 0 0;">
            <h2 style="margin:0;">Review Requested</h2>
        </div>
        <div style="padding:20px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;">
            <p>Hi {reviewer_name},</p>
            <p><strong>{submitter_name}</strong> has submitted <strong>{combo_name}</strong> for your review.</p>
            {working_file_section}
            <p><a href="{review_url}"
                   style="display:inline-block;padding:12px 24px;background:#1e40af;
                          color:white;border-radius:6px;text-decoration:none;font-weight:bold;">
                Review Now
            </a></p>
            <hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0;">
            <p style="color:#6b7280;font-size:12px;">
                You are receiving this because you were assigned as a reviewer on the Meander Ads Platform.
            </p>
        </div>
    </div>
    """
    return subject, html_body


def render_approval_result_email(
    combo_name: str,
    creator_name: str,
    event: str,
    reviewer_name: str | None,
    approval_id: str,
    platform_url: str = "",
) -> tuple[str, str]:
    """Render email for approval result (approved/rejected/needs-revision). Returns (subject, html_body)."""
    if event == "APPROVED":
        subject = f"[Approved] {combo_name} is ready to launch"
        status_color = "#059669"
        status_text = "fully approved"
        action_text = "You can now launch it."
    elif event == "NEEDS_REVISION":
        subject = f"[Needs Revision] {combo_name}"
        status_color = "#d97706"
        status_text = (
            f"sent back for revision by {reviewer_name}"
            if reviewer_name else "sent back for revision"
        )
        action_text = "Revise the working file and submit a new round from the same approval."
    else:
        subject = f"[Rejected] {combo_name}"
        status_color = "#dc2626"
        status_text = f"rejected by {reviewer_name}" if reviewer_name else "rejected"
        action_text = "Check the working file for feedback."

    review_url = f"{platform_url}/approvals/{approval_id}"
    header_label = {
        "APPROVED": "Combo Approved",
        "REJECTED": "Combo Rejected",
        "NEEDS_REVISION": "Combo Needs Revision",
    }.get(event, f"Combo {event.title()}")

    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
        <div style="background:{status_color};color:white;padding:20px;border-radius:8px 8px 0 0;">
            <h2 style="margin:0;">{header_label}</h2>
        </div>
        <div style="padding:20px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;">
            <p>Hi {creator_name},</p>
            <p><strong>{combo_name}</strong> has been {status_text}. {action_text}</p>
            <p><a href="{review_url}"
                   style="display:inline-block;padding:12px 24px;background:{status_color};
                          color:white;border-radius:6px;text-decoration:none;font-weight:bold;">
                View Details
            </a></p>
            <hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0;">
            <p style="color:#6b7280;font-size:12px;">
                You are receiving this because you submitted this combo on the Meander Ads Platform.
            </p>
        </div>
    </div>
    """
    return subject, html_body
