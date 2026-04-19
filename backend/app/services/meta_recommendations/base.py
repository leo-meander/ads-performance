"""Detector base class and shared value types (Meta).

A Detector produces zero or more DetectorFindings. The orchestrator
(engine.run_recommendations) collects findings across all registered
detectors, enriches them with Claude, and upserts into meta_recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Iterable

from sqlalchemy.orm import Session

from app.services.meta_recommendations.catalog import CATALOG, RecTypeSpec


@dataclass
class DetectorTarget:
    """An entity a detector evaluates against."""
    entity_level: str  # account | campaign | ad_set | ad
    entity_id: str
    account_id: str
    campaign_id: str | None = None
    ad_set_id: str | None = None
    ad_id: str | None = None
    funnel_stage: str | None = None  # TOF | MOF | BOF (parsed from campaign name)
    targeted_country: str | None = None  # ISO-2 (ad_set only); None for campaign/account roll-ups
    context: dict[str, Any] = field(default_factory=dict)

    def dedup_key(self, rec_type: str) -> str:
        return f"{rec_type}:{self.entity_level}:{self.entity_id}"


@dataclass
class DetectorFinding:
    """Raw detector output — evidence of a playbook violation.

    `evidence` stores the metrics and thresholds that triggered the rule.
    `metrics_snapshot` is the wider context persisted to the recommendation.
    `action_kwargs` override the catalog defaults (e.g. computed pct bump).
    """
    evidence: dict[str, Any]
    metrics_snapshot: dict[str, Any]
    action_kwargs: dict[str, Any] = field(default_factory=dict)
    warning_vars: dict[str, Any] = field(default_factory=dict)
    title_override: str | None = None


class Detector:
    """Base class for Meta playbook detectors.

    Subclasses must:
    - Set `rec_type` to a key in CATALOG.
    - Implement `scope(db, account_ids)` yielding DetectorTarget.
    - Implement `evaluate(db, target)` returning DetectorFinding | None.
    - Override `build_action(target, finding)` if auto_applicable=True.
    """

    rec_type: ClassVar[str] = ""

    def __init__(self) -> None:
        if not self.rec_type:
            raise ValueError(f"{type(self).__name__}.rec_type must be set")
        if self.rec_type not in CATALOG:
            raise ValueError(
                f"{type(self).__name__}.rec_type={self.rec_type!r} is not in CATALOG",
            )
        self.spec: RecTypeSpec = CATALOG[self.rec_type]

    # -- Catalog passthroughs -------------------------------------------------
    @property
    def severity(self) -> str: return self.spec.severity
    @property
    def cadence(self) -> str: return self.spec.cadence
    @property
    def sop_reference(self) -> str: return self.spec.sop_reference
    @property
    def auto_applicable(self) -> bool: return self.spec.auto_applicable
    @property
    def default_title(self) -> str: return self.spec.default_title
    @property
    def warning_template(self) -> str: return self.spec.warning_template

    # -- Must override --------------------------------------------------------
    def scope(self, db: Session, account_ids: list[str] | None = None) -> Iterable[DetectorTarget]:
        raise NotImplementedError

    def evaluate(self, db: Session, target: DetectorTarget) -> DetectorFinding | None:
        raise NotImplementedError

    def build_action(self, target: DetectorTarget, finding: DetectorFinding) -> dict[str, Any]:
        """Return the `suggested_action` dict stored on the recommendation.

        Default: guidance-only. Auto-applicable detectors must override.
        """
        if self.auto_applicable:
            raise NotImplementedError(
                f"{type(self).__name__} is auto_applicable but did not override build_action",
            )
        return {"function": None, "kwargs": {}}

    def render_warning(self, finding: DetectorFinding) -> str:
        if not finding.warning_vars:
            return self.warning_template
        try:
            return self.warning_template.format(**finding.warning_vars)
        except (KeyError, IndexError):
            return self.warning_template

    def render_title(self, finding: DetectorFinding) -> str:
        return finding.title_override or self.default_title
