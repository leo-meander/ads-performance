"""Thin wrapper around the Canva Connect API for the regenerate flow.

Canva's autofill endpoint is async. Two-step contract:
  1. start_autofill(template_id, autofill, title) → AutofillJob (might be
     status=in_progress with no design yet, OR status=success with design
     attached when the queue is empty).
  2. get_autofill_job(job_id) → AutofillJob — poll until status != in_progress.

`clone_template` is a convenience that starts then returns the immediate-
success path, raising if the job queues. Used in tests and stub mode where
the queue is synthetic.

Stub mode (CANVA_API_TOKEN empty): start_autofill returns a deterministic
"completed" job synchronously. This means the stub never exercises the
poll path — that's verified separately by injecting a non-stub client into
unit tests for the polling task.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class CanvaDesign:
    design_id: str
    edit_url: str
    view_url: str
    autofill_echo: Optional[dict[str, Any]] = None  # populated only in stub mode


@dataclass
class AutofillJob:
    """Mirror of Canva's autofill job resource.

    status: 'in_progress' | 'success' | 'failed'
    design: present when status='success'
    error: present when status='failed'
    autofill_echo: stub-only — what placeholders were applied
    """
    job_id: str
    status: Literal["in_progress", "success", "failed"]
    design: Optional[CanvaDesign] = None
    error: Optional[str] = None
    autofill_echo: Optional[dict[str, Any]] = None


class CanvaClientError(RuntimeError):
    """Raised on any Canva API failure or invalid response."""


class CanvaClient:
    def __init__(
        self,
        api_token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.api_token = api_token if api_token is not None else settings.CANVA_API_TOKEN
        self.base_url = (base_url or settings.CANVA_API_BASE_URL).rstrip("/")
        self.timeout = timeout

    @property
    def is_stub(self) -> bool:
        return not self.api_token

    # ── Public ops ────────────────────────────────────────────

    def start_autofill(
        self,
        template_id: str,
        autofill: dict[str, Any],
        title: Optional[str] = None,
    ) -> AutofillJob:
        """Kick off an autofill job. May return an in-progress job (caller polls)
        or a completed job if Canva finished synchronously.
        """
        if self.is_stub:
            return self._stub_start(template_id, autofill, title)

        payload = {
            "brand_template_id": template_id,
            "data": _to_canva_autofill(autofill),
        }
        if title:
            payload["title"] = title

        try:
            resp = httpx.post(
                f"{self.base_url}/autofills",
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise CanvaClientError(f"Canva autofill request failed: {e}") from e

        return _parse_job(resp.json())

    def get_autofill_job(self, job_id: str) -> AutofillJob:
        """Poll an autofill job. Stub mode treats the job_id as already-completed
        (matches start_autofill's stub behavior)."""
        if self.is_stub:
            # Stub jobs are completed at start; if someone calls poll the design
            # has already been returned. Treat as success with a synthetic design.
            return AutofillJob(
                job_id=job_id,
                status="success",
                design=_stub_design_from_job_id(job_id),
            )

        try:
            resp = httpx.get(
                f"{self.base_url}/autofills/{job_id}",
                headers=self._headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise CanvaClientError(f"Canva autofill poll failed: {e}") from e

        return _parse_job(resp.json())

    def clone_template(
        self,
        template_id: str,
        autofill: dict[str, Any],
        title: Optional[str] = None,
    ) -> CanvaDesign:
        """Convenience: kick off autofill and require immediate completion.

        Used when the caller can't wait — tests, stub mode. Real flows should
        use start_autofill + persist the job_id, then let the cron poller
        finish the row when status flips to success/failed.
        """
        job = self.start_autofill(template_id, autofill, title)
        if job.status == "in_progress":
            raise CanvaClientError(
                f"Canva autofill queued (job_id={job.job_id}); "
                f"this caller requires synchronous completion"
            )
        if job.status == "failed":
            raise CanvaClientError(f"Canva autofill failed: {job.error}")
        if job.design is None:
            raise CanvaClientError("Canva autofill success but no design attached")
        # Carry the stub echo through so existing tests can introspect it.
        if job.autofill_echo is not None:
            job.design.autofill_echo = job.autofill_echo
        return job.design

    # ── Stub implementation ──────────────────────────────────

    def _stub_start(
        self,
        template_id: str,
        autofill: dict[str, Any],
        title: Optional[str],
    ) -> AutofillJob:
        design_id = f"DAFstub_{uuid.uuid4().hex[:12]}"
        edit_url = f"https://www.canva.com/design/{design_id}/edit"
        logger.info(
            "Canva stub start_autofill: template=%s title=%s placeholders=%s -> %s",
            template_id, title, list(autofill.keys()), design_id,
        )
        design = CanvaDesign(
            design_id=design_id,
            edit_url=edit_url,
            view_url=edit_url,
        )
        return AutofillJob(
            job_id=f"job_stub_{uuid.uuid4().hex[:10]}",
            status="success",
            design=design,
            autofill_echo=autofill,
        )

    # ── Internals ────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }


# ── Module-level parsing helpers ─────────────────────────────


def _parse_job(body: dict[str, Any]) -> AutofillJob:
    """Convert a Canva autofills response into our AutofillJob dataclass."""
    job = body.get("job") or body
    job_id = job.get("id") or ""
    status = (job.get("status") or "in_progress").lower()
    if status not in ("in_progress", "success", "failed"):
        raise CanvaClientError(f"Unexpected Canva job status: {status} (body={body})")

    design = None
    if status == "success":
        result = job.get("result") or {}
        design_obj = result.get("design") or {}
        design_id = design_obj.get("id")
        edit_url = design_obj.get("url") or design_obj.get("edit_url")
        if not design_id or not edit_url:
            raise CanvaClientError(f"Canva success response missing design.id/url: {body}")
        design = CanvaDesign(
            design_id=design_id,
            edit_url=edit_url,
            view_url=design_obj.get("view_url") or edit_url,
        )

    error = None
    if status == "failed":
        error = (job.get("error") or {}).get("message") or str(job.get("error") or "unknown")

    return AutofillJob(job_id=job_id, status=status, design=design, error=error)


def _stub_design_from_job_id(job_id: str) -> CanvaDesign:
    suffix = job_id.replace("job_stub_", "") or uuid.uuid4().hex[:12]
    design_id = f"DAFstub_{suffix}"
    edit_url = f"https://www.canva.com/design/{design_id}/edit"
    return CanvaDesign(design_id=design_id, edit_url=edit_url, view_url=edit_url)


def _to_canva_autofill(autofill: dict[str, Any]) -> dict[str, Any]:
    """Convert our flat {name: value} into Canva's tagged autofill format.

    Canva expects: {"placeholder_name": {"type": "text", "text": "..."}}
    or             {"placeholder_name": {"type": "image", "asset_id": "..."}}
    """
    out: dict[str, Any] = {}
    for name, value in autofill.items():
        if isinstance(value, dict) and "asset_id" in value:
            out[name] = {"type": "image", "asset_id": value["asset_id"]}
        else:
            out[name] = {"type": "text", "text": str(value)}
    return out
