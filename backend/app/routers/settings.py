from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import require_role
from app.models.currency_rate import CurrencyRate
from app.models.user import User

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _rate_to_dict(r: CurrencyRate) -> dict:
    return {
        "currency": r.currency,
        "rate_to_usd": float(r.rate_to_usd) if r.rate_to_usd is not None else None,
        "updated_by": r.updated_by,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


# ── Schemas ──────────────────────────────────────────────────


class UpsertRateRequest(BaseModel):
    currency: str
    rate_to_usd: float


class BulkUpsertRequest(BaseModel):
    rates: list[UpsertRateRequest]


# ── Endpoints ────────────────────────────────────────────────


@router.get("/settings/currency-rates")
def list_currency_rates(
    current_user: User = Depends(require_role(["admin", "creator", "reviewer"])),
    db: Session = Depends(get_db),
):
    """List all currency → USD conversion rates. Any authenticated user can read."""
    try:
        rates = db.query(CurrencyRate).order_by(CurrencyRate.currency).all()
        return _api_response(data={"items": [_rate_to_dict(r) for r in rates]})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/settings/currency-rates")
def upsert_currency_rates(
    body: BulkUpsertRequest,
    current_user: User = Depends(require_role(["admin"])),
    db: Session = Depends(get_db),
):
    """Bulk upsert currency rates. Admin only.

    Accepts a list; each entry inserts a new currency row or updates the
    existing one. Rates must be positive floats. Currency code is uppercased
    and trimmed to 3 chars (ISO-4217).
    """
    try:
        updated = []
        for item in body.rates:
            code = (item.currency or "").strip().upper()
            if len(code) != 3 or not code.isalpha():
                raise HTTPException(status_code=400, detail=f"Invalid currency code: {item.currency!r}")
            try:
                rate = Decimal(str(item.rate_to_usd))
            except (InvalidOperation, TypeError):
                raise HTTPException(status_code=400, detail=f"Invalid rate for {code}")
            if rate <= 0:
                raise HTTPException(status_code=400, detail=f"Rate for {code} must be > 0")

            row = db.query(CurrencyRate).filter(CurrencyRate.currency == code).first()
            if row is None:
                row = CurrencyRate(currency=code, rate_to_usd=rate, updated_by=current_user.email)
                db.add(row)
            else:
                row.rate_to_usd = rate
                row.updated_by = current_user.email
            updated.append(code)

        db.commit()
        rows = (
            db.query(CurrencyRate)
            .filter(CurrencyRate.currency.in_(updated))
            .order_by(CurrencyRate.currency)
            .all()
        )
        return _api_response(data={"items": [_rate_to_dict(r) for r in rows]})
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/settings/currency-rates/{currency}")
def delete_currency_rate(
    currency: str,
    current_user: User = Depends(require_role(["admin"])),
    db: Session = Depends(get_db),
):
    """Remove a currency row. Admin only."""
    try:
        code = (currency or "").strip().upper()
        row = db.query(CurrencyRate).filter(CurrencyRate.currency == code).first()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Currency {code} not found")
        db.delete(row)
        db.commit()
        return _api_response(data={"deleted": code})
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
