"""Tactics: preset materialization, lifecycle, revert phase, sunsetting steps."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.account import AdAccount
from app.models.action_log import ActionLog
from app.models.ad import Ad
# Force-import FK-target models so Base.metadata is complete before create_all.
# The default app.models __init__ doesn't include these, so tests must pull
# them in explicitly to avoid NoReferencedTableError during table creation.
from app.models.ad_angle import AdAngle  # noqa: F401
from app.models.ad_combo import AdCombo  # noqa: F401
from app.models.ad_copy import AdCopy  # noqa: F401
from app.models.ad_material import AdMaterial  # noqa: F401
from app.models.ad_set import AdSet
from app.models.base import Base
from app.models.campaign import Campaign
from app.models.rule import AutomationRule
from app.models.tactic import Tactic
from app.services import tactic_engine, tactic_service
from app.services.rule_engine import evaluate_all_rules
from app.services.tactic_presets import (
    PRESETS,
    REVERT_NEXT_DAY,
    REVERT_NONE,
    REVERT_ON_RECOVERY,
)

engine = create_engine(
    "sqlite:///test_tactics.db", connect_args={"check_same_thread": False},
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _seed_tree():
    """Create AdAccount → Campaign → AdSet → Ad and return the IDs."""
    db = TestSession()
    acc = AdAccount(
        id=str(uuid.uuid4()),
        platform="meta",
        account_id=f"act_{uuid.uuid4().hex[:6]}",
        account_name="Saigon",
        currency="VND",
        is_active=True,
        access_token_enc="token-x",
    )
    db.add(acc)
    db.flush()
    camp = Campaign(
        id=str(uuid.uuid4()),
        account_id=acc.id,
        platform="meta",
        platform_campaign_id=f"camp_{uuid.uuid4().hex[:6]}",
        name="Test Campaign",
        objective="OUTCOME_SALES",
        status="ACTIVE",
        daily_budget=500000,
    )
    db.add(camp)
    db.flush()
    adset = AdSet(
        id=str(uuid.uuid4()),
        campaign_id=camp.id,
        account_id=acc.id,
        platform="meta",
        platform_adset_id=f"adset_{uuid.uuid4().hex[:6]}",
        name="Test AdSet",
        status="ACTIVE",
        daily_budget=200000,
    )
    db.add(adset)
    db.flush()
    ad = Ad(
        id=str(uuid.uuid4()),
        ad_set_id=adset.id,
        campaign_id=camp.id,
        account_id=acc.id,
        platform="meta",
        platform_ad_id=f"ad_{uuid.uuid4().hex[:6]}",
        name="Test Ad",
        status="ACTIVE",
    )
    db.add(ad)
    db.commit()
    ids = {"acc": acc.id, "campaign": camp.id, "adset": adset.id, "ad": ad.id}
    db.close()
    return ids


# ---------------------------------------------------------------------------
# Preset → AutomationRule materialization
# ---------------------------------------------------------------------------

def test_create_from_preset_surf_adset_materializes_one_rule():
    ids = _seed_tree()
    db = TestSession()
    t = tactic_service.create_tactic_from_preset(
        db,
        preset_type="surf_adset",
        platform="meta",
        account_id=ids["acc"],
        config_overrides={"roas_min": 4.0, "budget_multiplier": 1.5},
    )
    assert t.preset_type == "surf_adset"
    assert t.config["roas_min"] == 4.0
    assert t.config["budget_multiplier"] == 1.5
    assert t.config["_revert_policy"] == REVERT_NEXT_DAY

    rules = db.query(AutomationRule).filter(AutomationRule.tactic_id == t.id).all()
    assert len(rules) == 1
    rule = rules[0]
    assert rule.entity_level == "ad_set"
    assert rule.action == "adjust_budget"
    # First condition is the user-tunable roas_min (after override).
    assert rule.conditions[0]["threshold"] == 4.0
    assert rule.action_params["budget_multiplier"] == 1.5
    assert rule.action_params["max_budget_cap_multiplier"] == 2.0  # preset default
    db.close()


def test_toggle_cascades_to_linked_rules():
    ids = _seed_tree()
    db = TestSession()
    t = tactic_service.create_tactic_from_preset(
        db, preset_type="stop_loss_ad", platform="meta", account_id=ids["acc"],
    )
    tactic_service.toggle_tactic(db, t.id, False)
    rule = db.query(AutomationRule).filter(AutomationRule.tactic_id == t.id).first()
    assert rule.is_active is False
    tactic_service.toggle_tactic(db, t.id, True)
    db.refresh(rule)
    assert rule.is_active is True
    db.close()


def test_update_config_rewrites_rules():
    ids = _seed_tree()
    db = TestSession()
    t = tactic_service.create_tactic_from_preset(
        db, preset_type="stop_loss_ad", platform="meta", account_id=ids["acc"],
    )
    tactic_service.update_tactic_config(db, t.id, {"roas_min": 0.5})
    rule = db.query(AutomationRule).filter(AutomationRule.tactic_id == t.id).first()
    # First condition is roas; the threshold should reflect the override.
    roas_cond = next(c for c in rule.conditions if c["metric"] == "roas")
    assert roas_cond["threshold"] == 0.5
    db.close()


def test_delete_cascades_rules():
    ids = _seed_tree()
    db = TestSession()
    t = tactic_service.create_tactic_from_preset(
        db, preset_type="surf_campaign", platform="meta", account_id=ids["acc"],
    )
    tactic_id = t.id
    tactic_service.delete_tactic(db, tactic_id)
    remaining = (
        db.query(AutomationRule).filter(AutomationRule.tactic_id == tactic_id).count()
    )
    assert remaining == 0
    db.close()


# ---------------------------------------------------------------------------
# Tactic budget computation
# ---------------------------------------------------------------------------

def test_surf_compute_applies_multiplier_and_cap():
    ids = _seed_tree()
    db = TestSession()
    t = tactic_service.create_tactic_from_preset(
        db, preset_type="surf_adset", platform="meta", account_id=ids["acc"],
        config_overrides={"budget_multiplier": 5.0, "max_budget_cap_multiplier": 2.0},
    )
    rule = db.query(AutomationRule).filter(AutomationRule.tactic_id == t.id).first()
    adset = db.query(AdSet).filter(AdSet.id == ids["adset"]).first()
    out = tactic_engine.compute_tactic_budget(db, rule, adset, "ad_set")
    # current=200000, 5x=1000000, cap at 2x=400000 → expect 400000
    assert out["new_budget"] == 400000
    assert out["cap_applied"] is True
    assert out["should_pause"] is False
    db.close()


def test_sunsetting_progresses_through_three_steps():
    ids = _seed_tree()
    db = TestSession()
    t = tactic_service.create_tactic_from_preset(
        db, preset_type="sunsetting", platform="meta", account_id=ids["acc"],
    )
    rule = db.query(AutomationRule).filter(AutomationRule.tactic_id == t.id).first()
    adset = db.query(AdSet).filter(AdSet.id == ids["adset"]).first()

    # Step 1: no prior logs → step=1, budget = 200000 * 0.75 = 150000.
    out = tactic_engine.compute_tactic_budget(db, rule, adset, "ad_set")
    assert out["sunsetting_step"] == 1
    assert out["new_budget"] == 150000

    # Simulate first sunsetting hit logged.
    db.add(ActionLog(
        rule_id=rule.id, campaign_id=adset.campaign_id, ad_set_id=adset.id, ad_id=None,
        platform="meta", action="adjust_budget",
        action_params={
            "tactic_id": t.id, "sunsetting": True,
            "original_state": {"daily_budget": 200000.0, "status": "ACTIVE"},
            "new_state": {"daily_budget": 150000.0, "status": "ACTIVE"},
        },
        triggered_by="rule", metrics_snapshot=None, success=True,
        executed_at=datetime.now(timezone.utc) - timedelta(days=2),
    ))
    db.commit()

    # Step 2: budget = 200000 * 0.50 = 100000 (cumulative from origin).
    out2 = tactic_engine.compute_tactic_budget(db, rule, adset, "ad_set")
    assert out2["sunsetting_step"] == 2
    assert out2["new_budget"] == 100000
    assert out2["should_pause"] is False

    # Simulate second sunsetting hit.
    db.add(ActionLog(
        rule_id=rule.id, campaign_id=adset.campaign_id, ad_set_id=adset.id, ad_id=None,
        platform="meta", action="adjust_budget",
        action_params={
            "tactic_id": t.id, "sunsetting": True,
            "original_state": {"daily_budget": 150000.0, "status": "ACTIVE"},
            "new_state": {"daily_budget": 100000.0, "status": "ACTIVE"},
        },
        triggered_by="rule", metrics_snapshot=None, success=True,
        executed_at=datetime.now(timezone.utc) - timedelta(days=1),
    ))
    db.commit()

    # Step 3: pause.
    out3 = tactic_engine.compute_tactic_budget(db, rule, adset, "ad_set")
    assert out3["sunsetting_step"] == 3
    assert out3["should_pause"] is True
    db.close()


def test_scale_winning_ratchets_until_cap():
    ids = _seed_tree()
    db = TestSession()
    t = tactic_service.create_tactic_from_preset(
        db, preset_type="scale_winning_adset", platform="meta", account_id=ids["acc"],
        config_overrides={"daily_step_pct": 0.20, "max_budget_cap_multiplier": 2.0},
    )
    rule = db.query(AutomationRule).filter(AutomationRule.tactic_id == t.id).first()
    adset = db.query(AdSet).filter(AdSet.id == ids["adset"]).first()

    # First fire: 200000 * 1.2 = 240000. origin = 200000 (no prior logs).
    out1 = tactic_engine.compute_tactic_budget(db, rule, adset, "ad_set")
    assert out1["new_budget"] == 240000
    assert out1["cap_applied"] is False

    # Seed first scale_winning log to anchor origin at 200000.
    db.add(ActionLog(
        rule_id=rule.id, campaign_id=adset.campaign_id, ad_set_id=adset.id, ad_id=None,
        platform="meta", action="adjust_budget",
        action_params={
            "tactic_id": t.id, "scale_winning": True,
            "original_state": {"daily_budget": 200000.0, "status": "ACTIVE"},
            "new_state": {"daily_budget": 240000.0, "status": "ACTIVE"},
        },
        triggered_by="rule", metrics_snapshot=None, success=True,
        executed_at=datetime.now(timezone.utc) - timedelta(days=3),
    ))
    db.commit()

    # Simulate current budget after several ratchets — closer to cap.
    adset.daily_budget = 380000
    db.commit()

    # 380000 * 1.2 = 456000, cap = 200000 * 2.0 = 400000 → 400000, cap_applied=True.
    out2 = tactic_engine.compute_tactic_budget(db, rule, adset, "ad_set")
    assert out2["new_budget"] == 400000
    assert out2["cap_applied"] is True
    db.close()


# ---------------------------------------------------------------------------
# Revert phase
# ---------------------------------------------------------------------------

def test_revert_finds_yesterday_next_day_actions_and_skips_already_reverted():
    ids = _seed_tree()
    db = TestSession()
    # One eligible mutation from yesterday + one identical mutation but flagged
    # as already-reverted by a sister log entry.
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    log_eligible = ActionLog(
        rule_id=None, campaign_id=ids["campaign"], ad_set_id=ids["adset"], ad_id=None,
        platform="meta", action="adjust_budget",
        action_params={
            "tactic_id": "fake", "preset_type": "surf_adset", "revert_policy": "next_day",
            "original_state": {"daily_budget": 200000.0, "status": "ACTIVE"},
            "new_state": {"daily_budget": 250000.0, "status": "ACTIVE"},
        },
        triggered_by="rule", metrics_snapshot=None, success=True, executed_at=yesterday,
    )
    db.add(log_eligible)
    db.commit()

    # Patch Meta calls — we want to exercise the revert flow without touching the network.
    with patch("app.services.tactic_engine.update_ad_set_budget", return_value=True):
        summary = tactic_engine.revert_tactic_actions(db, lookback_days=2)
    assert summary["candidates"] == 1
    assert summary["reverted"] == 1

    # Run again — the sister tactic_revert log should now block re-revert.
    with patch("app.services.tactic_engine.update_ad_set_budget", return_value=True):
        summary2 = tactic_engine.revert_tactic_actions(db, lookback_days=2)
    assert summary2["candidates"] == 1
    assert summary2["skipped_already_reverted"] == 1
    assert summary2["reverted"] == 0
    db.close()


def test_revert_ignores_actions_without_next_day_policy():
    ids = _seed_tree()
    db = TestSession()
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    db.add(ActionLog(
        rule_id=None, campaign_id=ids["campaign"], ad_set_id=ids["adset"], ad_id=None,
        platform="meta", action="pause_adset",
        action_params={
            "tactic_id": "fake", "revert_policy": "none",
            "original_state": {"daily_budget": 200000.0, "status": "ACTIVE"},
            "new_state": {"daily_budget": 200000.0, "status": "PAUSED"},
        },
        triggered_by="rule", metrics_snapshot=None, success=True, executed_at=yesterday,
    ))
    db.commit()
    summary = tactic_engine.revert_tactic_actions(db, lookback_days=2)
    assert summary["candidates"] == 0
    assert summary["reverted"] == 0
    db.close()


# ---------------------------------------------------------------------------
# Preset registry sanity
# ---------------------------------------------------------------------------

def test_evaluate_all_rules_tactics_filter_segregates_correctly():
    """Regression guard for the compound-multiplier bug.

    sync_all_platforms now calls evaluate_all_rules(tactics_filter='no_tactics')
    so tactic rules don't fire on every intraday sync. run-daily-tactics calls
    with tactics_filter='tactic_only'. Verify both filters return disjoint sets.
    """
    ids = _seed_tree()
    db = TestSession()
    # Create one standalone rule + one tactic.
    standalone = AutomationRule(
        id=str(uuid.uuid4()),
        name="standalone",
        platform="meta",
        account_id=ids["acc"],
        entity_level="ad",
        conditions=[{"metric": "roas", "operator": "<", "threshold": 0.5, "days": 1}],
        action="send_alert",
        is_active=True,
    )
    db.add(standalone)
    db.commit()
    t = tactic_service.create_tactic_from_preset(
        db, preset_type="stop_loss_ad", platform="meta", account_id=ids["acc"],
    )
    # Use send_alert action so evaluation doesn't try to hit Meta API.
    # The preset's conditions won't match (no metrics seeded) so we just count
    # the rules that get evaluated, not their actions.
    db.query(AutomationRule).filter(AutomationRule.tactic_id == t.id).update(
        {"action": "send_alert"}, synchronize_session=False,
    )
    db.commit()

    all_results = evaluate_all_rules(db, tactics_filter="all")
    no_tactics = evaluate_all_rules(db, tactics_filter="no_tactics")
    tactic_only = evaluate_all_rules(db, tactics_filter="tactic_only")

    rule_ids_all = {r["rule_id"] for r in all_results}
    rule_ids_no_tac = {r["rule_id"] for r in no_tactics}
    rule_ids_tac = {r["rule_id"] for r in tactic_only}

    assert standalone.id in rule_ids_no_tac
    assert standalone.id not in rule_ids_tac
    # Tactic-only set must include the tactic's rule.
    tactic_rule = db.query(AutomationRule).filter(AutomationRule.tactic_id == t.id).first()
    assert tactic_rule.id in rule_ids_tac
    assert tactic_rule.id not in rule_ids_no_tac
    # Union check.
    assert rule_ids_no_tac | rule_ids_tac == rule_ids_all
    assert rule_ids_no_tac & rule_ids_tac == set()
    db.close()


def test_custom_rule_preset_materializes_from_overrides():
    """The Custom preset passes the user's full rule definition straight
    through to the AutomationRule — no preset-config merging or threshold
    seeding."""
    ids = _seed_tree()
    db = TestSession()
    conditions = [
        {"metric": "spend", "operator": ">", "threshold": 50000, "days": 3},
        {"metric": "roas", "operator": "<", "threshold": 1.5, "days": 7},
    ]
    t = tactic_service.create_tactic_from_preset(
        db, preset_type="custom_rule", platform="meta", account_id=ids["acc"],
        config_overrides={
            "entity_level": "ad_set",
            "conditions": conditions,
            "action": "send_alert",
            "action_params": None,
        },
    )
    rules = db.query(AutomationRule).filter(AutomationRule.tactic_id == t.id).all()
    assert len(rules) == 1
    r = rules[0]
    assert r.entity_level == "ad_set"
    assert r.action == "send_alert"
    assert r.conditions == conditions
    assert r.action_params is None
    db.close()


def test_migrate_standalone_rules_wraps_each_in_custom_tactic():
    """The one-shot migration should wrap each standalone rule in a Custom
    tactic and re-link the rule — never duplicate or drop conditions."""
    ids = _seed_tree()
    db = TestSession()
    # Two standalone rules + one already linked to a tactic.
    pre_existing_tactic = tactic_service.create_tactic_from_preset(
        db, preset_type="stop_loss_ad", platform="meta", account_id=ids["acc"],
    )
    standalone1 = AutomationRule(
        id=str(uuid.uuid4()),
        name="legacy rule A",
        platform="meta",
        account_id=ids["acc"],
        entity_level="ad",
        conditions=[{"metric": "roas", "operator": "<", "threshold": 0.5, "days": 7}],
        action="send_alert",
        is_active=True,
    )
    standalone2 = AutomationRule(
        id=str(uuid.uuid4()),
        name="legacy rule B",
        platform="meta",
        account_id=ids["acc"],
        entity_level="campaign",
        conditions=[{"metric": "spend", "operator": ">", "threshold": 1000000, "days": 1}],
        action="pause_campaign",
        is_active=False,
    )
    db.add_all([standalone1, standalone2])
    db.commit()

    summary = tactic_service.migrate_standalone_rules_to_custom_tactics(db)
    assert summary["migrated"] == 2

    # Both standalone rules now linked to a Custom tactic.
    db.refresh(standalone1)
    db.refresh(standalone2)
    assert standalone1.tactic_id is not None
    assert standalone2.tactic_id is not None

    # is_active carries through.
    t1 = db.query(Tactic).filter(Tactic.id == standalone1.tactic_id).first()
    t2 = db.query(Tactic).filter(Tactic.id == standalone2.tactic_id).first()
    assert t1.preset_type == "custom_rule"
    assert t1.is_active is True
    assert t2.is_active is False

    # Re-run is idempotent (no further migrations).
    summary2 = tactic_service.migrate_standalone_rules_to_custom_tactics(db)
    assert summary2["migrated"] == 0

    # Pre-existing tactic untouched.
    pre_rule = (
        db.query(AutomationRule)
        .filter(AutomationRule.tactic_id == pre_existing_tactic.id)
        .first()
    )
    assert pre_rule is not None
    db.close()


def test_evaluate_rule_summary_includes_fail_examples():
    """The evaluation_summary action_log now includes a sample of concrete
    failure reasons so the diagnostics UI can show *why* — not just metric
    name + count."""
    ids = _seed_tree()
    db = TestSession()
    # Tactic with a condition no entity can satisfy (we have an Ad but no
    # metrics seeded, so 'no metrics data' is the expected fail reason).
    t = tactic_service.create_tactic_from_preset(
        db, preset_type="custom_rule", platform="meta", account_id=ids["acc"],
        config_overrides={
            "entity_level": "ad",
            "conditions": [{"metric": "roas", "operator": ">", "threshold": 999, "days": 7}],
            "action": "send_alert",
            "action_params": None,
        },
    )
    rule = db.query(AutomationRule).filter(AutomationRule.tactic_id == t.id).first()

    from app.services.rule_engine import evaluate_rule
    evaluate_rule(db, rule)

    summary_log = (
        db.query(ActionLog)
        .filter(ActionLog.rule_id == rule.id, ActionLog.action == "evaluation_summary")
        .first()
    )
    assert summary_log is not None
    snap = summary_log.metrics_snapshot
    assert "fail_examples" in snap
    assert len(snap["fail_examples"]) >= 1
    # Each example carries the entity name + the failure reason text.
    ex = snap["fail_examples"][0]
    assert "entity_name" in ex
    assert "reason" in ex
    db.close()


def test_funnel_stage_filter_segregates_entities():
    """Engine should only see entities whose parent Campaign matches the
    tactic's funnel_stage filter."""
    ids = _seed_tree()
    db = TestSession()
    # Existing seed campaign has no funnel_stage. Set it to TOF.
    camp = db.query(Campaign).filter(Campaign.id == ids["campaign"]).first()
    camp.funnel_stage = "TOF"
    # Add a second campaign + adset under MOF for the same account so we can
    # confirm only TOF entities show up under a TOF-filtered tactic.
    mof_camp = Campaign(
        id=str(uuid.uuid4()),
        account_id=ids["acc"],
        platform="meta",
        platform_campaign_id="camp_mof",
        name="MOF Campaign",
        objective="OUTCOME_SALES",
        status="ACTIVE",
        funnel_stage="MOF",
    )
    db.add(mof_camp)
    db.flush()
    mof_adset = AdSet(
        id=str(uuid.uuid4()),
        campaign_id=mof_camp.id,
        account_id=ids["acc"],
        platform="meta",
        platform_adset_id="adset_mof",
        name="MOF AdSet",
        status="ACTIVE",
        daily_budget=300000,
    )
    db.add(mof_adset)
    db.commit()

    from app.services.rule_engine import _get_matching_adsets

    # Tactic with funnel_stage=TOF — should only see the TOF adset.
    t_tof = tactic_service.create_tactic_from_preset(
        db, preset_type="stop_loss_adset", platform="meta", account_id=ids["acc"],
        config_overrides={"funnel_stage": "TOF"},
    )
    rule_tof = db.query(AutomationRule).filter(AutomationRule.tactic_id == t_tof.id).first()
    tof_matches = _get_matching_adsets(db, rule_tof, funnel_stage="TOF")
    tof_ids = {a.id for a in tof_matches}
    assert ids["adset"] in tof_ids
    assert mof_adset.id not in tof_ids

    # Same rule but funnel_stage=MOF → only the MOF adset.
    mof_matches = _get_matching_adsets(db, rule_tof, funnel_stage="MOF")
    mof_ids = {a.id for a in mof_matches}
    assert mof_adset.id in mof_ids
    assert ids["adset"] not in mof_ids

    # No funnel filter → both.
    all_matches = _get_matching_adsets(db, rule_tof, funnel_stage=None)
    assert {ids["adset"], mof_adset.id}.issubset({a.id for a in all_matches})
    db.close()


def test_compute_branch_percentile_returns_none_when_insufficient_data():
    """Percentile needs ≥3 distinct entities; otherwise fall through so the
    safety_bound can act as the threshold."""
    ids = _seed_tree()
    db = TestSession()
    # Only one entity in the DB — should return None.
    result = tactic_engine.compute_branch_percentile(
        db,
        account_id=ids["acc"],
        entity_level="ad",
        funnel_stage=None,
        metric="roas",
        percentile=50,
        days=30,
    )
    assert result is None
    db.close()


def test_dynamic_threshold_resolver_falls_back_to_safety_bound_on_insufficient_data():
    """When there isn't enough branch data to compute the percentile, the
    resolver should clamp to the safety_bound so the tactic can still fire."""
    ids = _seed_tree()
    db = TestSession()
    t = tactic_service.create_tactic_from_preset(
        db, preset_type="stop_loss_ad", platform="meta", account_id=ids["acc"],
        config_overrides={
            "funnel_stage": "TOF",
            "threshold_mode": "dynamic",
            "lookback_days": 30,
            "days": 3,
            "roas_percentile": 25,
            "roas_safety_bound": 1.5,
            "spend_min": 100,
        },
    )
    rule = db.query(AutomationRule).filter(AutomationRule.tactic_id == t.id).first()

    from app.services.rule_engine import _resolve_dynamic_conditions
    patched, debug = _resolve_dynamic_conditions(db, rule, t)

    # ROAS condition should now carry the safety_bound as its threshold.
    roas_cond = next((c for c in patched if c["metric"] == "roas"), None)
    assert roas_cond is not None
    assert roas_cond["threshold"] == 1.5
    # Effective thresholds include the metric with a "fallback to safety_bound" source.
    assert "roas" in debug["effective_thresholds"]
    assert "fallback" in debug["effective_thresholds"]["roas"]["source"].lower()
    db.close()


def test_dynamic_threshold_resolver_clamps_to_safety_bound_for_stop_loss():
    """Stop-loss tactic (operator '<'): when computed percentile is HIGHER
    than the safety bound, we use the lower (safer) of the two.

    Ensures a thriving branch's P25 doesn't murder mid-pack ads. We mock
    compute_branch_percentile so this test stays focused on the clamping
    logic itself (the percentile SQL is exercised separately).
    """
    ids = _seed_tree()
    db = TestSession()
    t = tactic_service.create_tactic_from_preset(
        db, preset_type="stop_loss_ad", platform="meta", account_id=ids["acc"],
        config_overrides={
            "funnel_stage": "TOF",
            "threshold_mode": "dynamic",
            "roas_percentile": 25,
            "roas_safety_bound": 1.5,
            "spend_min": 50,
        },
    )
    rule = db.query(AutomationRule).filter(AutomationRule.tactic_id == t.id).first()

    # Branch P25 is computed as 6.0 (high — branch thriving). Operator '<' must
    # clamp DOWN to the 1.5 safety bound or we'd murder mid-pack ads.
    from app.services import rule_engine as re_mod
    with patch.object(re_mod, "_resolve_dynamic_conditions", wraps=re_mod._resolve_dynamic_conditions), \
         patch("app.services.tactic_engine.compute_branch_percentile", return_value=6.0):
        patched, debug = re_mod._resolve_dynamic_conditions(db, rule, t)

    roas_cond = next(c for c in patched if c["metric"] == "roas")
    assert roas_cond["threshold"] == 1.5
    assert debug["baselines"]["roas_p25"] == 6.0
    db.close()


def test_dynamic_threshold_resolver_clamps_to_safety_bound_for_surf():
    """Surf tactic (operator '>='): when computed percentile is LOWER than
    the safety bound, we use the higher (more conservative) of the two."""
    ids = _seed_tree()
    db = TestSession()
    t = tactic_service.create_tactic_from_preset(
        db, preset_type="surf_adset", platform="meta", account_id=ids["acc"],
        config_overrides={
            "funnel_stage": "TOF",
            "threshold_mode": "dynamic",
            "roas_percentile": 75,
            "roas_safety_bound": 3.0,
            "spend_min": 50,
        },
    )
    rule = db.query(AutomationRule).filter(AutomationRule.tactic_id == t.id).first()

    # Branch P75 mocked as 1.2 (struggling branch). Operator '>=' must clamp
    # UP to 3.0 so we don't scale losers.
    from app.services import rule_engine as re_mod
    with patch("app.services.tactic_engine.compute_branch_percentile", return_value=1.2):
        patched, _ = re_mod._resolve_dynamic_conditions(db, rule, t)

    roas_cond = next(c for c in patched if c["metric"] == "roas")
    assert roas_cond["threshold"] == 3.0
    db.close()


def test_all_presets_have_required_fields():
    # Engine-driven presets that intentionally have NO AutomationRule specs:
    # they own their own scheduling loop (cron + service package) instead of
    # going through the rule_engine evaluator.
    _ENGINE_DRIVEN_PRESETS = {"surf_intraday_campaign"}

    for key, preset in PRESETS.items():
        assert preset.name
        assert preset.default_config
        assert preset.revert_policy in (REVERT_NEXT_DAY, REVERT_NONE, REVERT_ON_RECOVERY)
        # rule_specs_fn must accept the default config; engine-driven presets
        # may return [] (no AutomationRule materialization).
        specs = preset.rule_specs_fn({**preset.default_config, "_preset_type": key})
        if key in _ENGINE_DRIVEN_PRESETS:
            assert specs == [], f"engine-driven preset {key} unexpectedly produced rule specs"
            continue
        assert specs, f"preset {key} produced no rule specs"
        for s in specs:
            assert s.entity_level in ("campaign", "ad_set", "ad")
            assert s.action


# ---------------------------------------------------------------------------
# Change Log endpoint (per-tactic Madgicx-style action history)
# ---------------------------------------------------------------------------

def test_action_kind_buckets_actions_into_icon_families():
    from app.routers.tactics import _action_kind
    assert _action_kind("pause_ad", {}, {}) == "pause"
    assert _action_kind("enable_ad", {}, {}) == "enable"
    assert _action_kind("reenable_ad", {}, {}) == "enable"
    assert _action_kind("adjust_budget", {"daily_budget": 100}, {"daily_budget": 150}) == "budget_up"
    assert _action_kind("adjust_budget", {"daily_budget": 150}, {"daily_budget": 100}) == "budget_down"
    assert _action_kind("send_alert", {}, {}) == "alert"
    assert _action_kind("totally_unknown", {}, {}) == "other"


def test_change_log_endpoint_returns_paginated_searchable_history():
    from types import SimpleNamespace

    from app.routers.tactics import get_tactic_change_log

    ids = _seed_tree()
    db = TestSession()
    t = tactic_service.create_tactic_from_preset(
        db, preset_type="stop_loss_ad", platform="meta", account_id=ids["acc"],
    )
    rule = db.query(AutomationRule).filter(AutomationRule.tactic_id == t.id).first()
    ad = db.query(Ad).filter(Ad.id == ids["ad"]).first()
    now = datetime.now(timezone.utc)

    # success pause (older)
    db.add(ActionLog(
        rule_id=rule.id, campaign_id=ad.campaign_id, ad_set_id=ad.ad_set_id, ad_id=ad.id,
        platform="meta", action="pause_ad",
        action_params={"original_state": {"status": "ACTIVE"}, "new_state": {"status": "PAUSED"}},
        triggered_by="rule", metrics_snapshot={"roas": 0.5, "ctr": 0.012, "spend": 75.0},
        success=True, executed_at=now - timedelta(hours=2),
    ))
    # success budget increase
    db.add(ActionLog(
        rule_id=rule.id, campaign_id=ad.campaign_id, ad_set_id=ad.ad_set_id, ad_id=ad.id,
        platform="meta", action="adjust_budget",
        action_params={"original_state": {"daily_budget": 700.0}, "new_state": {"daily_budget": 900.0}},
        triggered_by="rule", metrics_snapshot={"roas": 2.4}, success=True,
        executed_at=now - timedelta(hours=1),
    ))
    # failed pause — most recent, must surface error + success=False
    db.add(ActionLog(
        rule_id=rule.id, campaign_id=ad.campaign_id, ad_set_id=ad.ad_set_id, ad_id=ad.id,
        platform="meta", action="pause_ad",
        action_params={"original_state": {"status": "ACTIVE"}, "new_state": {"status": "ACTIVE"}},
        triggered_by="rule", metrics_snapshot=None, success=False,
        error_message="User does not have permission for this action.",
        executed_at=now,
    ))
    # evaluation_summary — MUST be excluded from the change log
    db.add(ActionLog(
        rule_id=rule.id, campaign_id=ad.campaign_id, ad_set_id=None, ad_id=None,
        platform="meta", action="evaluation_summary",
        triggered_by="rule", metrics_snapshot={"entities_checked": 5}, success=True,
        executed_at=now - timedelta(hours=3),
    ))
    db.commit()

    user = SimpleNamespace(roles=["admin"])
    resp = get_tactic_change_log(t.id, limit=25, offset=0, q=None, current_user=user, db=db)
    assert resp["success"] is True
    data = resp["data"]
    assert data["total"] == 3, "evaluation_summary must be excluded"
    assert data["account_timezone"]
    entries = data["entries"]

    # newest first → failed pause leads
    assert entries[0]["success"] is False
    assert entries[0]["kind"] == "pause"
    assert "permission" in (entries[0]["error_message"] or "")
    # deep link carries the platform ad id
    assert ad.platform_ad_id in (entries[0]["external_url"] or "")

    # budget entry carries before/after + direction
    budget_entry = next(e for e in entries if e["action"] == "adjust_budget")
    assert budget_entry["kind"] == "budget_up"
    assert budget_entry["before"]["daily_budget"] == 700.0
    assert budget_entry["after"]["daily_budget"] == 900.0

    # metrics surfaced on the successful pause
    pause_ok = next(e for e in entries if e["action"] == "pause_ad" and e["success"])
    assert pause_ok["metrics"]["roas"] == 0.5
    assert pause_ok["label"] == "Ad paused"

    # search filters by acted-on entity name
    hit = get_tactic_change_log(t.id, limit=25, offset=0, q="Test Ad", current_user=user, db=db)
    assert hit["data"]["total"] == 3
    miss = get_tactic_change_log(t.id, limit=25, offset=0, q="zzz-nope", current_user=user, db=db)
    assert miss["data"]["total"] == 0

    # pagination caps page size
    paged = get_tactic_change_log(t.id, limit=2, offset=0, q=None, current_user=user, db=db)
    assert len(paged["data"]["entries"]) == 2
    assert paged["data"]["total"] == 3
    db.close()
