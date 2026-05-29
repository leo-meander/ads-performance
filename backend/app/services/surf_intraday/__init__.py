"""SURF Intraday automation — Madgicx-style intraday budget boosting.

Architecture (6 modules, each with a single responsibility):

  engine.py         — orchestrator. `poll_active_surfs(db)` is the cron entry.
  tier_resolver.py  — pure function. ROAS → tier multiplier (with Double Check).
  checkpoint.py     — SurfRun / SurfCheckpoint persistence + idempotency reads.
  meta_intraday.py  — Meta Insights API (date_preset=today, omni_purchase).
  budget_writer.py  — cap stack (per_check, per_day, max_mult, sanity) + write.
  revert.py         — end-of-day restore (per-branch IANA timezone).

Why parallel to rule_engine instead of inside it: rule_engine reads daily
MetricsCache snapshots and evaluates conditions on day windows. SURF intraday
reads live Meta API (today only), tracks spend-threshold crossings instead of
condition booleans, and applies multi-tier multipliers. Same database, same
audit (action_logs + surf_checkpoints), but different code path.

Money path safety: any change to budget_writer.py or the cap stack ordering
needs a paired test in tests/test_surf_intraday/. The cap stack order is
intentional — per_check is checked FIRST so the operator can pin a hard
ceiling that no other layer can override.
"""

from app.services.surf_intraday.engine import poll_active_surfs
from app.services.surf_intraday.revert import revert_end_of_day_runs

__all__ = ["poll_active_surfs", "revert_end_of_day_runs"]
