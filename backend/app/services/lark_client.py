"""Thin wrapper around the Lark (Feishu) Open Platform API.

Scope here is deliberately small — everything the "Send to Lark" flow needs:

  - _tenant_token()            internal-app tenant_access_token (cached)
  - create_bitable_record()    add a row to a Base (Bitable) table

Auth model: a custom app authenticates with app_id + app_secret to mint a
tenant_access_token (valid ~2h). Bitable writes additionally require the app to
be added to the target Base as a collaborator with edit rights — that grant is
done in the Lark UI, not here.

Stub-free: unlike figma_client there is no fake mode; if credentials or the
Base/table ids are missing the methods raise LarkClientError so the caller can
surface a clear "not configured" message.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class LarkClientError(RuntimeError):
    """Raised on any Lark API failure, misconfiguration, or invalid response."""


class LarkClient:
    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 15.0,
    ):
        self.app_id = app_id if app_id is not None else settings.LARK_APP_ID
        self.app_secret = app_secret if app_secret is not None else settings.LARK_APP_SECRET
        self.base_url = (base_url or settings.LARK_API_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._token: Optional[str] = None
        self._token_exp: float = 0.0
        self._lock = threading.Lock()

    # ── Auth ─────────────────────────────────────────────────

    def _tenant_token(self) -> str:
        if not self.app_id or not self.app_secret:
            raise LarkClientError(
                "Lark is not configured — set LARK_APP_ID and LARK_APP_SECRET."
            )
        with self._lock:
            now = time.time()
            # Refresh a minute early to dodge edge-of-expiry races.
            if self._token and now < self._token_exp - 60:
                return self._token
            try:
                resp = httpx.post(
                    f"{self.base_url}/auth/v3/tenant_access_token/internal",
                    json={"app_id": self.app_id, "app_secret": self.app_secret},
                    timeout=self.timeout,
                )
            except httpx.HTTPError as e:
                raise LarkClientError(f"Lark token request failed: {e}") from e

            data = self._json(resp)
            if data.get("code") != 0:
                raise LarkClientError(
                    f"tenant_access_token error {data.get('code')}: {data.get('msg')}"
                )
            self._token = data.get("tenant_access_token") or ""
            self._token_exp = now + int(data.get("expire", 7200))
            if not self._token:
                raise LarkClientError("Lark returned an empty tenant_access_token")
            return self._token

    # ── Bitable ──────────────────────────────────────────────

    def create_bitable_record(
        self,
        *,
        app_token: str,
        table_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Create one record. `fields` is keyed by the Base's column NAMES.

        Returns the created record dict (includes `record_id`).
        """
        if not app_token or not table_id:
            raise LarkClientError(
                "Lark Base target is not configured — set LARK_BASE_APP_TOKEN "
                "and LARK_TASKS_TABLE_ID (from the Base URL)."
            )
        url = f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        try:
            resp = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._tenant_token()}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={"fields": fields},
                timeout=self.timeout,
            )
        except httpx.HTTPError as e:
            raise LarkClientError(f"Lark create-record request failed: {e}") from e

        data = self._json(resp)
        if data.get("code") != 0:
            raise LarkClientError(
                f"create record error {data.get('code')}: {data.get('msg')}"
            )
        return (data.get("data") or {}).get("record") or {}

    def list_table_fields(self, *, app_token: str, table_id: str) -> list[dict[str, Any]]:
        """List a table's fields (name + type) — used to confirm how to write
        each column (text vs single_select vs user vs link)."""
        if not app_token or not table_id:
            raise LarkClientError(
                "Lark Base target is not configured — set LARK_BASE_APP_TOKEN "
                "and LARK_TASKS_TABLE_ID."
            )
        url = f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
        try:
            resp = httpx.get(
                url,
                headers={"Authorization": f"Bearer {self._tenant_token()}"},
                timeout=self.timeout,
            )
        except httpx.HTTPError as e:
            raise LarkClientError(f"Lark list-fields request failed: {e}") from e
        data = self._json(resp)
        if data.get("code") != 0:
            raise LarkClientError(
                f"list fields error {data.get('code')}: {data.get('msg')}"
            )
        return (data.get("data") or {}).get("items") or []

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _json(resp: httpx.Response) -> dict[str, Any]:
        try:
            return resp.json()
        except ValueError as e:
            raise LarkClientError(
                f"Lark returned non-JSON (HTTP {resp.status_code}): {resp.text[:200]}"
            ) from e
