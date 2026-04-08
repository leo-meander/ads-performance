"""Export API endpoints with API key authentication."""

import calendar
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.api_key import ApiKey
from app.models.budget import BudgetPlan
from app.models.metrics import MetricsCache
from app.services.export_auth import create_api_key, validate_api_key

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


class KeyCreate(BaseModel):
    name: str
    created_by: str | None = None


@router.post("/export/keys")
def create_key(body: KeyCreate, db: Session = Depends(get_db)):
    """Create a new API key. Returns plaintext ONCE."""
    try:
        api_key, plaintext = create_api_key(db, body.name, body.created_by)
        db.commit()
        return _api_response(data={
            "id": str(api_key.id),
            "name": api_key.name,
            "key": plaintext,  # Shown once, never again
            "key_prefix": api_key.key_prefix,
            "created_at": api_key.created_at.isoformat() if api_key.created_at else None,
        })
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/export/keys")
def list_keys(db: Session = Depends(get_db)):
    """List API keys (no plaintext shown)."""
    try:
        keys = db.query(ApiKey).filter(ApiKey.is_active.is_(True)).all()
        return _api_response(data=[
            {
                "id": str(k.id),
                "name": k.name,
                "key_prefix": k.key_prefix,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                "daily_request_count": k.daily_request_count,
                "created_at": k.created_at.isoformat() if k.created_at else None,
            }
            for k in keys
        ])
    except Exception as e:
        return _api_response(error=str(e))


@router.delete("/export/keys/{key_id}")
def deactivate_key(key_id: str, db: Session = Depends(get_db)):
    """Deactivate an API key (soft delete)."""
    try:
        api_key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
        if not api_key:
            return _api_response(error="API key not found")
        api_key.is_active = False
        db.commit()
        return _api_response(data={"id": key_id, "deactivated": True})
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))


@router.get("/export/budget/monthly")
def export_budget_monthly(
    month: str = Query(None, description="YYYY-MM format"),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """Export monthly budget data. Requires API key."""
    try:
        if month:
            month_date = date.fromisoformat(f"{month}-01")
        else:
            today = date.today()
            month_date = date(today.year, today.month, 1)

        plans = (
            db.query(BudgetPlan)
            .filter(BudgetPlan.month == month_date, BudgetPlan.is_active.is_(True))
            .all()
        )

        return _api_response(data={
            "month": month_date.isoformat(),
            "plans": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "branch": p.branch,
                    "channel": p.channel,
                    "total_budget": float(p.total_budget),
                    "currency": p.currency,
                }
                for p in plans
            ],
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.get("/export/spend/daily")
def export_spend_daily(
    date_from: str = Query(...),
    date_to: str = Query(...),
    platform: str = Query(None),
    api_key: ApiKey = Depends(validate_api_key),
    db: Session = Depends(get_db),
):
    """Export daily spend breakdown. Requires API key."""
    try:
        q = db.query(
            MetricsCache.date,
            MetricsCache.platform,
            func.sum(MetricsCache.spend).label("spend"),
            func.sum(MetricsCache.impressions).label("impressions"),
            func.sum(MetricsCache.clicks).label("clicks"),
            func.sum(MetricsCache.conversions).label("conversions"),
            func.sum(MetricsCache.revenue).label("revenue"),
        ).filter(
            MetricsCache.date >= date.fromisoformat(date_from),
            MetricsCache.date <= date.fromisoformat(date_to),
        )

        if platform:
            q = q.filter(MetricsCache.platform == platform)

        rows = q.group_by(MetricsCache.date, MetricsCache.platform).order_by(MetricsCache.date).all()

        return _api_response(data=[
            {
                "date": row.date.isoformat(),
                "platform": row.platform,
                "spend": float(row.spend or 0),
                "impressions": int(row.impressions or 0),
                "clicks": int(row.clicks or 0),
                "conversions": int(row.conversions or 0),
                "revenue": float(row.revenue or 0),
            }
            for row in rows
        ])
    except Exception as e:
        return _api_response(error=str(e))
