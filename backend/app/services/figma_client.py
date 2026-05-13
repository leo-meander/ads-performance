"""Thin wrapper around the Figma REST API.

The Figma REST surface is read-mostly: GET /v1/files/{key} for structure +
text content, GET /v1/images for renders. There is no public endpoint that
overwrites text content on a frame from outside Figma — variant *generation*
needs either the Figma plugin runtime (out-of-process) or the Variables API
(Enterprise). For now this client supports:

  - get_file(file_key)              full file tree
  - get_node(file_key, node_id)     single node + descendants
  - get_text_layers(...)            recursive walk yielding (id, name, characters)
  - export_images(file_key, ids)    render frames as PNG/SVG/PDF

Stub mode: when FIGMA_ACCESS_TOKEN is empty the client returns deterministic
fake responses so the regenerate flow is testable without OAuth setup.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class FigmaClientError(RuntimeError):
    """Raised on any Figma API failure or invalid response."""


@dataclass
class FigmaTextLayer:
    """A text node inside a Figma frame."""
    node_id: str
    name: str
    characters: str
    parent_path: list[str] = field(default_factory=list)


@dataclass
class FigmaExport:
    node_id: str
    image_url: str
    format: str = "png"


class FigmaClient:
    def __init__(
        self,
        access_token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.access_token = (
            access_token if access_token is not None else settings.FIGMA_ACCESS_TOKEN
        )
        self.base_url = (base_url or settings.FIGMA_API_BASE_URL).rstrip("/")
        self.timeout = timeout

    @property
    def is_stub(self) -> bool:
        return not self.access_token

    # ── HTTP plumbing ────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {"X-Figma-Token": self.access_token}

    def _get(self, path: str, params: Optional[dict] = None) -> dict[str, Any]:
        try:
            resp = httpx.get(
                f"{self.base_url}{path}",
                headers=self._headers(),
                params=params or {},
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise FigmaClientError(f"Figma GET {path} failed: {e}") from e
        return resp.json()

    # ── Public ops ────────────────────────────────────────────

    def get_file(self, file_key: str) -> dict[str, Any]:
        """Full file structure. Heavy — prefer get_node when you have an id."""
        if self.is_stub:
            return {"name": f"stub-file-{file_key}", "document": _stub_document()}
        return self._get(f"/files/{file_key}")

    def get_node(self, file_key: str, node_id: str) -> dict[str, Any]:
        """Single node tree. Returns Figma's `nodes` envelope."""
        if self.is_stub:
            return {
                "nodes": {
                    node_id: {
                        "document": _stub_node(node_id),
                        "components": {},
                        "styles": {},
                    }
                }
            }
        return self._get(f"/files/{file_key}/nodes", {"ids": node_id})

    def get_text_layers(
        self, file_key: str, node_id: str
    ) -> list[FigmaTextLayer]:
        """Walk the node tree returning every TEXT child with its text content."""
        envelope = self.get_node(file_key, node_id)
        node_block = envelope.get("nodes", {}).get(node_id) or {}
        document = node_block.get("document") or {}

        out: list[FigmaTextLayer] = []
        _collect_text_layers(document, [], out)
        return out

    def export_images(
        self,
        file_key: str,
        node_ids: Iterable[str],
        *,
        fmt: str = "png",
        scale: float = 1.0,
    ) -> list[FigmaExport]:
        """Render the given nodes. Returns presigned image URLs (Figma CDN)."""
        ids = list(node_ids)
        if not ids:
            return []

        if self.is_stub:
            return [
                FigmaExport(
                    node_id=nid,
                    image_url=f"https://figma-stub.example/{file_key}/{nid}.{fmt}",
                    format=fmt,
                )
                for nid in ids
            ]

        body = self._get(
            f"/images/{file_key}",
            {"ids": ",".join(ids), "format": fmt, "scale": scale},
        )
        if body.get("err"):
            raise FigmaClientError(f"Figma image export error: {body['err']}")
        urls = body.get("images", {})
        return [
            FigmaExport(node_id=nid, image_url=url, format=fmt)
            for nid, url in urls.items()
            if url
        ]


# ── Module-level helpers ─────────────────────────────────────


def _collect_text_layers(
    node: dict[str, Any],
    parent_path: list[str],
    out: list[FigmaTextLayer],
) -> None:
    if not isinstance(node, dict):
        return
    node_type = node.get("type")
    name = node.get("name") or ""

    if node_type == "TEXT":
        out.append(FigmaTextLayer(
            node_id=node.get("id") or "",
            name=name,
            characters=node.get("characters") or "",
            parent_path=list(parent_path),
        ))

    children = node.get("children") or []
    if isinstance(children, list):
        for child in children:
            _collect_text_layers(child, parent_path + [name], out)


# ── Stub fixtures ────────────────────────────────────────────


def _stub_node(node_id: str) -> dict[str, Any]:
    """A small frame with 3 named text layers used by tests + design previews."""
    return {
        "id": node_id,
        "name": "Stub Frame",
        "type": "FRAME",
        "children": [
            {
                "id": f"{node_id}:headline",
                "name": "headline",
                "type": "TEXT",
                "characters": "Stub Headline",
            },
            {
                "id": f"{node_id}:subhead",
                "name": "subhead",
                "type": "TEXT",
                "characters": "Stub subhead text.",
            },
            {
                "id": f"{node_id}:cta",
                "name": "cta",
                "type": "TEXT",
                "characters": "Book Now",
            },
        ],
    }


def _stub_document() -> dict[str, Any]:
    return {
        "id": "0:0",
        "name": "Document",
        "type": "DOCUMENT",
        "children": [
            {
                "id": "1:1",
                "name": "Page 1",
                "type": "CANVAS",
                "children": [_stub_node("2:1")],
            }
        ],
    }
