"""Meta Ads playbook recommendation engine.

Mirrors the Google recommendation engine shape so the two modules stay
swappable. The public surface used by routers + Celery tasks is:

    engine.run_recommendations(db, cadence, account_ids=None, source_task_id=None)
    engine.regenerate_recommendation(db, recommendation_id)
    applier.apply_recommendation(...)
    applier.dismiss_recommendation(...)

Detectors are auto-loaded by `registry._ensure_loaded()` — simply create a
new module under `detectors/` and decorate your class with `@register`.
"""
