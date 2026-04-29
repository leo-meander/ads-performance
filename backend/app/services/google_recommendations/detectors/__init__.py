"""Detector implementations.

Each module below registers one detector via @register. Importing this package
triggers all @register decorators.

Currently implemented:
- Phase 3 smoke-test detectors (5)
- Phase 6 extensions (12)
- Phase 7 PMax full-coverage (4) — depend on google_sync_engine fields
  bidding_strategy_type, target_cpa_micros, target_roas, audience_signals,
  has_brand_exclusion which are populated in google_sync_engine.
"""

from app.services.google_recommendations.detectors import (  # noqa: F401
    # Phase 3 smoke-test detectors
    dg_missing_video,
    pmax_learning_stuck,
    seasonality_lead_time_approaching,
    budget_mix_off_target,
    zero_conversions_7d,
    # Phase 6 extensions
    dg_ctr_below_benchmark,
    rsa_insufficient_assets,
    pmax_asset_group_incomplete,
    pmax_tcpa_change_too_large,
    spend_vs_budget_anomaly,
    impressions_drop_50,
    ctr_spike_100,
    budget_daily_exhausted_early,
    pmax_branded_leak,
    conv_ads_vs_pms_delta,
    seasonality_tcpa_adjust_due,
    low_season_shift_to_demandgen,
    # Phase 7 PMax full-coverage
    pmax_missing_audience_signal,
    pmax_bid_strategy_lifecycle_mismatch,
    pmax_count_vs_scale,
    pmax_missing_brand_exclusion,
)
