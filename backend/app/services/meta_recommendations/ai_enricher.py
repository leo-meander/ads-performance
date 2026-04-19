"""Claude enrichment layer for Meta playbook recommendation findings.

For each (detector, target, finding) tuple, call Claude with the playbook
excerpt + branch-specific ICP block as prompt-cacheable blocks and ask it to:
- write a concise English reasoning paragraph citing the branch name + metrics
- propose tailored action params (overrides the catalog defaults)
- return a confidence score and risk_flags

If Claude fails or returns malformed JSON, the recommendation is still
persisted — ai_reasoning stays NULL and the UI shows the static warning
template as fallback.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from anthropic import Anthropic

from app.config import settings
from app.models.account import AdAccount
from app.models.campaign import Campaign
from app.services.meta_recommendations.base import (
    Detector,
    DetectorFinding,
    DetectorTarget,
)
from app.services.meta_recommendations.sop_text import (
    PLAYBOOK_SUMMARY,
    branch_icp_block,
    excerpt_for,
    full_playbook_context,
)

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 768
MAX_BATCH_PER_CADENCE = 50

_SYSTEM_PROMPT = (
    "You are a performance-marketing analyst for MEANDER Group's Meta Ads, "
    "working from the internal Meta Ads Playbook. Every recommendation you "
    "enrich must be actionable, specific to the branch and its metrics, and "
    "written in ENGLISH. Never output Vietnamese. Never fabricate numbers — "
    "only cite values provided. Respond with a single valid JSON object and "
    "nothing else."
)

_JSON_INSTRUCTION = (
    "Return ONLY a JSON object matching this schema:\n"
    "{\n"
    '  "reasoning": "<2-4 sentences in English. Cite the branch name and the '
    'specific metric values from the finding. Explain WHY this matters per the '
    'playbook. Do not repeat the title verbatim.>",\n'
    '  "tailored_action_params": { ... optional overrides of catalog-default '
    'action kwargs; empty object {} if no override needed },\n'
    '  "confidence": <float 0.0-1.0>,\n'
    '  "risk_flags": [<zero or more short strings like "learning_phase_reset", '
    '"audience_cooling", "attribution_drift">]\n'
    "}"
)


@dataclass
class EnrichedFinding:
    detector: Detector
    target: DetectorTarget
    finding: DetectorFinding
    reasoning: str | None
    tailored_action_params: dict[str, Any]
    confidence: float | None
    risk_flags: list[str]


def _render_finding_block(
    detector: Detector,
    target: DetectorTarget,
    finding: DetectorFinding,
    account: AdAccount | None,
    campaign: Campaign | None,
) -> str:
    ctx: dict[str, Any] = {
        "rec_type": detector.rec_type,
        "severity": detector.severity,
        "sop_reference": detector.sop_reference,
        "default_title": detector.default_title,
        "auto_applicable": detector.auto_applicable,
        "branch_name": account.account_name if account else None,
        "branch_currency": account.currency if account else None,
        "campaign_id": target.campaign_id,
        "campaign_name": campaign.name if campaign else None,
        "funnel_stage": target.funnel_stage,
        "targeted_country": target.targeted_country,
        "evidence": finding.evidence,
        "metrics_snapshot": finding.metrics_snapshot,
        "catalog_warning_template": detector.warning_template,
    }
    return json.dumps(ctx, default=str, ensure_ascii=False, indent=2)


def _build_messages(
    detector: Detector,
    target: DetectorTarget,
    finding: DetectorFinding,
    account: AdAccount | None,
    campaign: Campaign | None,
) -> list[dict[str, Any]]:
    excerpt = excerpt_for(detector.sop_reference) or PLAYBOOK_SUMMARY
    icp_block = branch_icp_block(account.account_name if account else None)
    finding_block = _render_finding_block(detector, target, finding, account, campaign)
    branch_context = f"\n\nBRANCH CONTEXT:\n{icp_block}" if icp_block else ""
    user_content = (
        f"PLAYBOOK EXCERPT ({detector.sop_reference}):\n{excerpt}"
        f"{branch_context}\n\n"
        f"DETECTOR FINDING:\n{finding_block}\n\n"
        f"{_JSON_INSTRUCTION}"
    )
    return [{"role": "user", "content": user_content}]


def _build_system_blocks() -> list[dict[str, Any]]:
    """System with the full playbook cached as an ephemeral block."""
    return [
        {"type": "text", "text": _SYSTEM_PROMPT},
        {
            "type": "text",
            "text": (
                "MEANDER META ADS PLAYBOOK — ground every recommendation in "
                "this body of guidance.\n\n"
                + full_playbook_context()
            ),
            "cache_control": {"type": "ephemeral"},
        },
    ]


def _parse_response(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("meta enricher: JSON parse failed, text=%s", text[:400])
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _empty(detector: Detector, target: DetectorTarget, finding: DetectorFinding) -> EnrichedFinding:
    return EnrichedFinding(
        detector=detector,
        target=target,
        finding=finding,
        reasoning=None,
        tailored_action_params={},
        confidence=None,
        risk_flags=[],
    )


def enrich_one(
    client: Anthropic,
    detector: Detector,
    target: DetectorTarget,
    finding: DetectorFinding,
    account: AdAccount | None,
    campaign: Campaign | None,
) -> EnrichedFinding:
    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=_build_system_blocks(),
            messages=_build_messages(detector, target, finding, account, campaign),
        )
    except Exception as exc:
        logger.warning(
            "meta enricher: Claude call failed for %s (%s): %s",
            detector.rec_type, target.entity_id, exc,
        )
        return _empty(detector, target, finding)

    text_parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    parsed = _parse_response("".join(text_parts))
    if parsed is None:
        return _empty(detector, target, finding)

    reasoning = parsed.get("reasoning") if isinstance(parsed.get("reasoning"), str) else None
    tailored = parsed.get("tailored_action_params")
    tailored = tailored if isinstance(tailored, dict) else {}
    confidence = parsed.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    risk_flags = parsed.get("risk_flags") or []
    if not isinstance(risk_flags, list):
        risk_flags = []
    risk_flags = [str(x) for x in risk_flags if isinstance(x, (str, int, float))]

    return EnrichedFinding(
        detector=detector,
        target=target,
        finding=finding,
        reasoning=reasoning,
        tailored_action_params=tailored,
        confidence=confidence,
        risk_flags=risk_flags,
    )


def enrich_batch(
    items: list[tuple[Detector, DetectorTarget, DetectorFinding]],
    account_map: dict[str, AdAccount],
    campaign_map: dict[str, Campaign],
    *,
    api_key: str | None = None,
    max_items: int = MAX_BATCH_PER_CADENCE,
) -> list[EnrichedFinding]:
    if not items:
        return []
    api_key = api_key or settings.ANTHROPIC_API_KEY
    if not api_key:
        logger.info("meta enricher: ANTHROPIC_API_KEY not set — skipping enrichment")
        return [_empty(d, t, f) for d, t, f in items[:max_items]]

    client = Anthropic(api_key=api_key)
    out: list[EnrichedFinding] = []
    for detector, target, finding in items[:max_items]:
        account = account_map.get(target.account_id)
        campaign = campaign_map.get(target.campaign_id) if target.campaign_id else None
        out.append(enrich_one(client, detector, target, finding, account, campaign))
    return out
