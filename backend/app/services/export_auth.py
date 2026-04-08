"""Export API key authentication and rate limiting."""

import hashlib
import logging
import secrets
from datetime import date, datetime, timezone

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.api_key import ApiKey

logger = logging.getLogger(__name__)


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns (plaintext_key, key_hash, key_prefix).
    Plaintext is returned once and never stored.
    """
    plaintext = secrets.token_hex(32)  # 64 char hex string
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    key_prefix = plaintext[:8]
    return plaintext, key_hash, key_prefix


def create_api_key(db: Session, name: str, created_by: str | None = None) -> tuple[ApiKey, str]:
    """Create and store a new API key. Returns (model, plaintext_key).

    The plaintext key is returned ONCE at creation — never again.
    """
    plaintext, key_hash, key_prefix = generate_api_key()

    api_key = ApiKey(
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        created_by=created_by,
    )
    db.add(api_key)
    db.flush()

    return api_key, plaintext


def validate_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> ApiKey:
    """FastAPI dependency to validate API key from X-API-Key header.

    Also handles rate limiting (daily request count).
    """
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()

    api_key = db.query(ApiKey).filter(
        ApiKey.key_hash == key_hash,
        ApiKey.is_active.is_(True),
    ).first()

    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")

    # Rate limiting
    today = date.today()
    if api_key.daily_count_reset_at != today:
        api_key.daily_request_count = 0
        api_key.daily_count_reset_at = today

    daily_limit = getattr(settings, "EXPORT_API_RATE_LIMIT_DAILY", 1000)
    if api_key.daily_request_count >= daily_limit:
        raise HTTPException(status_code=429, detail="Daily rate limit exceeded")

    api_key.daily_request_count += 1
    api_key.last_used_at = datetime.now(timezone.utc)
    db.commit()

    return api_key
