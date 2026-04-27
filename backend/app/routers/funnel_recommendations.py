"""Funnel recommendations endpoint.

Computes the bottleneck-detector output dynamically — there is no stored table
for these recommendations because they always read the latest sync state of
metrics_cache. This is a read-only analytics endpoint, scoped to the
"analytics" section.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.permissions import scoped_account_ids
from app.database import get_db
from app.dependencies.auth import require_section
from app.models.user import User
from app.services.funnel_recommendations import analyze_funnel

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/dashboard/funnel-recommendations")
def funnel_recommendations(
    date_from: str | None = Query(None, description="ISO date; defaults to last-7-day window"),
    date_to: str | None = Query(None, description="ISO date; defaults to today"),
    platform: str | None = Query(None),
    branches: str | None = Query(None, description="Comma-separated branch names"),
    max_results: int = Query(12, ge=1, le=30),
    current_user: User = Depends(require_section("analytics")),
    db: Session = Depends(get_db),
):
    """Return ranked funnel-bottleneck recommendations for the analytics page.

    Each recommendation pinpoints one transition (e.g. Click → Search) for one
    slice (e.g. country=VN, ta=Solo) where conversion is most degraded vs the
    matching prior period. The card includes a deep-link target so the user
    can jump straight to the page that owns that root cause.
    """
    try:
        # Default to last 7 days
        if date_to is None:
            d_to = date.today()
        else:
            d_to = date.fromisoformat(date_to)
        if date_from is None:
            d_from = d_to - timedelta(days=6)
        else:
            d_from = date.fromisoformat(date_from)

        if d_from > d_to:
            return _api_response(error="date_from must be <= date_to")

        # Scope to user's accessible accounts
        branch_list = [b.strip() for b in branches.split(",") if b.strip()] if branches else None
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "analytics",
            requested_branches=branch_list,
        )
        if not ok:
            return _api_response(error=err)

        payload = analyze_funnel(
            db,
            d_from=d_from, d_to=d_to,
            platform=(platform or None),
            account_ids=scoped_ids,
            branches_param=branches,
            max_results=max_results,
        )
        return _api_response(data=payload)
    except Exception as e:
        return _api_response(error=str(e))
