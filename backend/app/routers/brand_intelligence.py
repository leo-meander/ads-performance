"""Brand Intelligence API — static brand identity per branch."""
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.brand_identity import BrandIdentity

router = APIRouter(prefix="/api/brand-intelligence", tags=["brand-intelligence"])


class BrandIdentityUpdate(BaseModel):
    human_desires: Optional[list[str]] = None
    brand_territory: Optional[str] = None
    brand_promise: Optional[str] = None
    emotional_themes: Optional[list[str]] = None
    never_say: Optional[list[str]] = None
    always_say: Optional[list[str]] = None
    feeling_target: Optional[str] = None


def _serialize(b: BrandIdentity) -> dict:
    return {
        "id": str(b.id),
        "branch_name": b.branch_name,
        "human_desires": b.human_desires or [],
        "brand_territory": b.brand_territory,
        "brand_promise": b.brand_promise,
        "emotional_themes": b.emotional_themes or [],
        "never_say": b.never_say or [],
        "always_say": b.always_say or [],
        "feeling_target": b.feeling_target,
        "updated_at": b.updated_at.isoformat() if b.updated_at else None,
    }


@router.get("")
def list_brand_identities(db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        rows = db.query(BrandIdentity).order_by(BrandIdentity.branch_name).all()
        return {"success": True, "data": [_serialize(r) for r in rows], "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/{branch_name}")
def get_brand_identity(branch_name: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        row = db.query(BrandIdentity).filter(BrandIdentity.branch_name == branch_name).first()
        if not row:
            raise HTTPException(status_code=404, detail=f"Brand identity not found: {branch_name}")
        return {"success": True, "data": _serialize(row), "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.patch("/{branch_name}")
def update_brand_identity(
    branch_name: str,
    payload: BrandIdentityUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        row = db.query(BrandIdentity).filter(BrandIdentity.branch_name == branch_name).first()
        if not row:
            raise HTTPException(status_code=404, detail=f"Brand identity not found: {branch_name}")
        for field, value in payload.model_dump(exclude_none=True).items():
            setattr(row, field, value)
        db.commit()
        db.refresh(row)
        return {"success": True, "data": _serialize(row), "error": None,
                "timestamp": datetime.now(timezone.utc).isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        return {"success": False, "data": None, "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}
