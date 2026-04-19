"""Meta seasonality scope — thin wrapper re-exporting the Google scope helpers.

The memory rule says: seasonality is per-branch home country UNION per-ad-set
targeted country. That logic lives in
`app.services.google_recommendations.seasonality_scope` and is already tested.
Meta detectors re-use it unchanged so there is a single source of truth.

The small extension here is `for_ad_set(db, ad_set_id)`: Meta's targeted
country is stored directly on AdSet.country (parsed at sync time), so we
can give detectors a simple "is this seasonal event relevant?" check.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.ad_set import AdSet
from app.services.google_recommendations.seasonality_scope import (
    BRANCH_COUNTRY_MAP,
    home_country_for_account,
    relevant_country_codes_for_account,
    relevant_country_codes_for_campaign,
    targeted_countries_for_campaign,
)

__all__ = [
    "BRANCH_COUNTRY_MAP",
    "home_country_for_account",
    "relevant_country_codes_for_account",
    "relevant_country_codes_for_campaign",
    "relevant_country_codes_for_ad_set",
    "targeted_countries_for_campaign",
]


def relevant_country_codes_for_ad_set(db: Session, ad_set_id: str) -> set[str]:
    """Home country ∪ this ad set's single parsed targeted country."""
    ad_set = db.query(AdSet).filter(AdSet.id == ad_set_id).first()
    if ad_set is None:
        return set()
    codes: set[str] = set()
    home = home_country_for_account(db, ad_set.account_id)
    if home:
        codes.add(home)
    country = (ad_set.country or "").strip().upper()
    if country and country != "UNKNOWN":
        codes.add(country[:2])
    return codes
