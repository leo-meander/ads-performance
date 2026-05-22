"""Winning ads endpoints — list combos joined with their material + copy.

The Canva-based regenerate flow that previously lived here has been removed.
Variant generation is moving to Figma and lives under /api/figma + /api/creative/brief.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.permissions import scoped_account_ids
from app.database import get_db
from app.dependencies.auth import require_page
from app.models.user import User
from app.services.winning_ads_service import (
    get_winning_ad_detail,
    list_winning_ads,
)

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/winning-ads")
def list_winning_ads_endpoint(
    branch_id: str | None = None,
    target_audience: str | None = None,
    country: str | None = None,
    verdict: str | None = None,
    sort_by: str = Query("roas"),
    sort_dir: str = Query("desc"),
    limit: int = Query(100, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_page("figma")),
    db: Session = Depends(get_db),
):
    try:
        ok, scoped_ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=branch_id
        )
        if not ok:
            return _api_response(error=err)

        result = list_winning_ads(
            db,
            scoped_account_ids=scoped_ids,
            branch_id=branch_id,
            target_audience=target_audience,
            country=country,
            verdict=verdict,
            sort_by=sort_by,
            sort_dir=sort_dir,
            limit=limit,
            offset=offset,
        )
        return _api_response(data=result)
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/winning-ads/{material_id}")
def get_winning_ad_endpoint(
    material_id: str,
    current_user: User = Depends(require_page("figma")),
    db: Session = Depends(get_db),
):
    try:
        ok, scoped_ids, err = scoped_account_ids(db, current_user, "meta_ads")
        if not ok:
            return _api_response(error=err)

        detail = get_winning_ad_detail(db, material_id, scoped_account_ids=scoped_ids)
        if detail is None:
            return _api_response(error="Material not found or not accessible")

        return _api_response(data=detail)
    except Exception as e:
        return _api_response(error=str(e))
