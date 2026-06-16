"""Tactic CRUD + lifecycle.

A Tactic is the user-facing toggle; AutomationRules are what the engine runs.
This service translates between the two: creating a tactic materializes its
preset's rule_specs into AutomationRule rows linked back via tactic_id.

Toggling a tactic's is_active cascades to all its rules so the engine's
existing `is_active` filter still works without modification.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.rule import AutomationRule
from app.models.tactic import Tactic
from app.services.tactic_presets import PRESETS, RuleSpec, get_preset

logger = logging.getLogger(__name__)


def create_tactic_from_preset(
    db: Session,
    *,
    preset_type: str,
    name: str | None = None,
    platform: str = "meta",
    account_id: str | None = None,
    config_overrides: dict[str, Any] | None = None,
    created_by: str | None = None,
) -> Tactic:
    """Create a Tactic and its associated AutomationRules in a single transaction.

    `config_overrides` shallow-merges over preset defaults — e.g. pass
    `{"roas_min": 2.0}` to tighten one threshold without restating the rest.
    """
    preset = get_preset(preset_type)
    if platform not in preset.valid_platforms:
        raise ValueError(
            f"Preset {preset_type} doesn't support platform {platform}. "
            f"Valid: {preset.valid_platforms}",
        )

    # Resolve final config: defaults overlaid with user overrides.
    config: dict[str, Any] = {**preset.default_config}
    if config_overrides:
        config.update(config_overrides)
    # Stamp the policy + preset_type onto config so the engine can read them
    # off the tactic without re-importing the preset module.
    config["_preset_type"] = preset_type
    config["_revert_policy"] = preset.revert_policy

    tactic = Tactic(
        name=name or preset.name,
        preset_type=preset_type,
        platform=platform,
        account_id=account_id,
        config=config,
        is_active=True,
        created_by=created_by,
    )
    db.add(tactic)
    db.flush()  # populate tactic.id for FK on rules

    # Materialize rules.
    for spec in preset.rule_specs_fn(config):
        _create_rule_for_tactic(db, tactic, spec, config, created_by)

    db.commit()
    db.refresh(tactic)
    logger.info(
        "Created tactic %s (preset=%s, account=%s) with %d rules",
        tactic.id, preset_type, account_id,
        len(preset.rule_specs_fn(config)),
    )
    return tactic


def _create_rule_for_tactic(
    db: Session,
    tactic: Tactic,
    spec: RuleSpec,
    config: dict[str, Any],
    created_by: str | None,
) -> AutomationRule:
    rule = AutomationRule(
        name=f"[{tactic.name}] {spec.name_suffix}"[:200],
        platform=tactic.platform,
        account_id=tactic.account_id,
        entity_level=spec.entity_level,
        conditions=spec.conditions,
        action=spec.action,
        action_params=spec.action_params,
        is_active=tactic.is_active,
        created_by=created_by,
        tactic_id=tactic.id,
    )
    db.add(rule)
    return rule


def toggle_tactic(db: Session, tactic_id: str, is_active: bool) -> Tactic:
    """Flip a tactic on/off — cascades to all linked rules so the engine's
    existing AutomationRule.is_active filter does the right thing."""
    tactic = db.query(Tactic).filter(Tactic.id == tactic_id).first()
    if not tactic:
        raise ValueError(f"Tactic not found: {tactic_id}")

    tactic.is_active = is_active
    tactic.updated_at = datetime.now(timezone.utc)

    db.query(AutomationRule).filter(AutomationRule.tactic_id == tactic_id).update(
        {"is_active": is_active, "updated_at": datetime.now(timezone.utc)},
        synchronize_session=False,
    )
    db.commit()
    db.refresh(tactic)
    return tactic


def delete_tactic(db: Session, tactic_id: str) -> None:
    """Hard delete the tactic + its linked rules.

    Postgres has FK ON DELETE CASCADE so the rules go automatically there,
    but SQLite (used by tests) doesn't enforce cascades unless foreign_keys
    pragma is on. Explicitly removing the rules first keeps the behavior
    identical across backends.

    action_logs.rule_id is ON DELETE SET NULL on both backends, so historical
    logs survive — only the rule definitions go away.
    """
    tactic = db.query(Tactic).filter(Tactic.id == tactic_id).first()
    if not tactic:
        raise ValueError(f"Tactic not found: {tactic_id}")
    db.query(AutomationRule).filter(AutomationRule.tactic_id == tactic_id).delete(
        synchronize_session=False,
    )
    db.delete(tactic)
    db.commit()


def update_tactic_config(
    db: Session, tactic_id: str, config_overrides: dict[str, Any],
) -> Tactic:
    """Merge overrides into tactic.config + rewrite linked rules from the preset.

    Used when the user tweaks thresholds (e.g. roas_min from 3.0 to 2.5) and we
    need the rules to reflect the new numbers next time the engine runs.
    """
    tactic = db.query(Tactic).filter(Tactic.id == tactic_id).first()
    if not tactic:
        raise ValueError(f"Tactic not found: {tactic_id}")

    preset = get_preset(tactic.preset_type)
    new_config: dict[str, Any] = {**(tactic.config or {}), **config_overrides}
    # Re-stamp internal markers (defensive: don't trust caller).
    new_config["_preset_type"] = tactic.preset_type
    new_config["_revert_policy"] = preset.revert_policy

    tactic.config = new_config
    tactic.updated_at = datetime.now(timezone.utc)

    # Wipe existing rules + regenerate so condition thresholds reflect new config.
    db.query(AutomationRule).filter(AutomationRule.tactic_id == tactic_id).delete(
        synchronize_session=False,
    )
    for spec in preset.rule_specs_fn(new_config):
        _create_rule_for_tactic(db, tactic, spec, new_config, tactic.created_by)

    db.commit()
    db.refresh(tactic)
    return tactic


def list_tactics(
    db: Session,
    *,
    account_id: str | None = None,
    platform: str | None = None,
    is_active: bool | None = None,
) -> list[Tactic]:
    q = db.query(Tactic)
    if account_id:
        q = q.filter(Tactic.account_id == account_id)
    if platform:
        q = q.filter(Tactic.platform == platform)
    if is_active is not None:
        q = q.filter(Tactic.is_active == is_active)
    return q.order_by(Tactic.created_at.desc()).all()


def get_tactic(db: Session, tactic_id: str) -> Tactic | None:
    return db.query(Tactic).filter(Tactic.id == tactic_id).first()


def count_rules_for_tactic(db: Session, tactic_id: str) -> int:
    return db.query(AutomationRule).filter(AutomationRule.tactic_id == tactic_id).count()


def get_valid_preset_types() -> list[str]:
    return sorted(PRESETS.keys())


def enroll_campaign_in_tactic(
    db: Session,
    *,
    campaign_id: str,
    account_id: str,
    preset_type: str,
    account_name: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Add a campaign to an allowlist-style tactic's `config.campaign_ids`.

    Used by the Action Needed "Enroll" button: instead of a one-shot Meta
    mutation, the campaign opts into a continuous tactic (e.g. SURF intraday).

    If the account has no active tactic of `preset_type` yet, one is created
    from its preset defaults (which, for SURF intraday, means dry_run=True —
    the operator must flip it live on /tactics). This keeps a single click
    from silently enabling live budget automation.

    Idempotent: re-enrolling a campaign already in the list is a no-op.

    Returns a summary dict: tactic_id, tactic_name, created, already_enrolled,
    dry_run, campaign_count.
    """
    tactic = (
        db.query(Tactic)
        .filter(
            Tactic.preset_type == preset_type,
            Tactic.account_id == account_id,
            Tactic.is_active.is_(True),
        )
        .order_by(Tactic.created_at.desc())
        .first()
    )

    created = False
    if tactic is None:
        preset = get_preset(preset_type)
        name = f"{preset.name} — {account_name}" if account_name else None
        tactic = create_tactic_from_preset(
            db,
            preset_type=preset_type,
            name=name,
            platform="meta",
            account_id=account_id,
            created_by=created_by,
        )
        created = True

    # Reassign a fresh dict so SQLAlchemy's dirty tracking fires (JSONType is
    # not a MutableDict — in-place .append would not be detected).
    cfg = dict(tactic.config or {})
    ids = list(cfg.get("campaign_ids") or [])
    already_enrolled = campaign_id in ids
    if not already_enrolled:
        ids.append(campaign_id)
        cfg["campaign_ids"] = ids
        tactic.config = cfg
        db.add(tactic)
        db.commit()
        db.refresh(tactic)

    final_cfg = tactic.config or {}
    return {
        "tactic_id": tactic.id,
        "tactic_name": tactic.name,
        "created": created,
        "already_enrolled": already_enrolled,
        "dry_run": bool(final_cfg.get("dry_run", True)),
        "campaign_count": len(final_cfg.get("campaign_ids") or []),
    }


def migrate_standalone_rules_to_custom_tactics(db: Session) -> dict:
    """Wrap each existing standalone AutomationRule (tactic_id IS NULL) in a
    Custom tactic and re-link the rule to it.

    Idempotent: rules with tactic_id already set are skipped. Run once after
    deploying the tactics-only-eval change so legacy rules continue firing
    via the daily tactics cron.

    Returns a summary dict for logging:
        {"scanned": N, "migrated": M, "skipped_already_linked": K}
    """
    from app.models.tactic import PRESET_CUSTOM_RULE

    standalone = (
        db.query(AutomationRule)
        .filter(AutomationRule.tactic_id.is_(None))
        .all()
    )
    migrated = 0
    for rule in standalone:
        config = {
            "entity_level": rule.entity_level,
            "conditions": rule.conditions,
            "action": rule.action,
            "action_params": rule.action_params,
            "_preset_type": PRESET_CUSTOM_RULE,
            "_revert_policy": "none",
        }
        tactic = Tactic(
            name=f"[Custom] {rule.name}"[:200],
            preset_type=PRESET_CUSTOM_RULE,
            platform=rule.platform,
            account_id=rule.account_id,
            config=config,
            is_active=rule.is_active,
            created_by=rule.created_by,
        )
        db.add(tactic)
        db.flush()
        rule.tactic_id = tactic.id
        migrated += 1
    db.commit()
    summary = {
        "scanned": len(standalone),
        "migrated": migrated,
        "skipped_already_linked": 0,
    }
    logger.info("migrate_standalone_rules_to_custom_tactics: %s", summary)
    return summary
