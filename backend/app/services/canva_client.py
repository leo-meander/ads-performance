"""Thin wrapper around the Canva Connect API for the regenerate flow.

Two operations are needed:
  1. clone_template(template_id, autofill) — produces a new design with the
     supplied placeholder values applied. Maps to the Canva Connect
     "create design from brand template + autofill" endpoint.
  2. get_design(design_id) — fetches the public edit URL of a design.

Stub mode (CANVA_API_TOKEN empty): returns deterministic mock URLs so the
end-to-end regenerate flow is exercisable without an Enterprise Canva org.
The stub also mirrors the autofill payload back so tests / UI can verify
the placeholders were threaded through correctly.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class CanvaDesign:
    design_id: str
    edit_url: str
    view_url: str
    autofill_echo: Optional[dict[str, Any]] = None  # populated only in stub mode


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

    def clone_template(
        self,
        template_id: str,
        autofill: dict[str, Any],
        title: Optional[str] = None,
    ) -> CanvaDesign:
        """Create a new design from a brand template, applying autofill values.

        autofill maps placeholder names (as wired in the Canva template) to
        either text strings or {"asset_id": "..."} dicts for image slots.
        """
        if self.is_stub:
            return self._stub_clone(template_id, autofill, title)

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

        body = resp.json()
        # The autofills endpoint is async (status: in_progress|success|failed).
        # For Phase 2 we only care about the immediate-success path; the queued
        # path needs a job-poll loop which we'll add when we wire a worker.
        job = body.get("job") or body
        status = job.get("status")
        if status and status != "success":
            raise CanvaClientError(
                f"Canva autofill not ready (status={status}); polling not implemented yet"
            )
        result = job.get("result") or {}
        design = result.get("design") or {}
        design_id = design.get("id")
        edit_url = design.get("url") or design.get("edit_url")
        if not design_id or not edit_url:
            raise CanvaClientError(f"Canva response missing design.id/url: {body}")

        return CanvaDesign(
            design_id=design_id,
            edit_url=edit_url,
            view_url=design.get("view_url") or edit_url,
        )

    # ── Stub implementation ──────────────────────────────────

    def _stub_clone(
        self,
        template_id: str,
        autofill: dict[str, Any],
        title: Optional[str],
    ) -> CanvaDesign:
        design_id = f"DAFstub_{uuid.uuid4().hex[:12]}"
        edit_url = f"https://www.canva.com/design/{design_id}/edit"
        logger.info(
            "Canva stub clone: template=%s title=%s placeholders=%s -> %s",
            template_id, title, list(autofill.keys()), design_id,
        )
        return CanvaDesign(
            design_id=design_id,
            edit_url=edit_url,
            view_url=edit_url,
            autofill_echo=autofill,
        )

    # ── Internals ────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }


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
