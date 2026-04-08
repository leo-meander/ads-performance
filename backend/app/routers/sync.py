import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.services.parse_utils import parse_adset_metadata, parse_campaign_metadata
from app.services.sync_engine import sync_all_platforms

logger = logging.getLogger(__name__)
router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


class ReparseBody(BaseModel):
    scope: str = "all"  # all | campaigns | adsets
    account_id: str | None = None


@router.post("/sync/trigger")
def trigger_sync(platform: str | None = None, db: Session = Depends(get_db)):
    """Manually trigger a data sync for one or all platforms."""
    try:
        results = sync_all_platforms(db)
        if platform:
            results = [r for r in results if r["platform"] == platform]
        return _api_response(data={
            "message": "Sync completed",
            "accounts_processed": len(results),
            "results": results,
        })
    except Exception as e:
        return _api_response(error=str(e))


@router.post("/sync/reparse")
def reparse_names(body: ReparseBody = ReparseBody(), db: Session = Depends(get_db)):
    """Re-parse all campaign/adset names without full sync."""
    try:
        reparsed = 0
        unknown_ta = 0
        unknown_funnel = 0
        unknown_country = 0

        if body.scope in ("all", "campaigns"):
            q = db.query(Campaign)
            if body.account_id:
                q = q.filter(Campaign.account_id == body.account_id)
            campaigns = q.all()

            for c in campaigns:
                parsed = parse_campaign_metadata(c.name)
                c.ta = parsed["ta"]
                c.funnel_stage = parsed["funnel_stage"]
                reparsed += 1
                if parsed["ta"] == "Unknown":
                    unknown_ta += 1
                if parsed["funnel_stage"] == "Unknown":
                    unknown_funnel += 1

        if body.scope in ("all", "adsets"):
            q = db.query(AdSet)
            if body.account_id:
                q = q.filter(AdSet.account_id == body.account_id)
            adsets = q.all()

            for a in adsets:
                parsed = parse_adset_metadata(a.name)
                a.country = parsed["country"]
                reparsed += 1
                if parsed["country"] == "Unknown":
                    unknown_country += 1

        db.commit()
        logger.info("Re-parse complete: %d items, %d unknown TA, %d unknown country", reparsed, unknown_ta, unknown_country)

        return _api_response(data={
            "reparsed": reparsed,
            "unknown_ta": unknown_ta,
            "unknown_funnel_stage": unknown_funnel,
            "unknown_country": unknown_country,
        })
    except Exception as e:
        db.rollback()
        return _api_response(error=str(e))
