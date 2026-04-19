"""Country-scope helpers for SEASONALITY_* and LOW_SEASON_* detectors.

A seasonality event should only fire for a campaign whose branch's home country
or targeted geo set includes the event's country_code:

    Saigon       → home country VN
    Osaka        → home country JP
    Taipei, 1948, Oani, Bread → home country TW

"Targeted countries" for a campaign come from the ISO-2 codes parsed into
ad_sets.country at sync time (adset_name.split('_')[0].upper()[:2] per the
parsing SOP). PMax campaigns without ad_sets fall back to home-country only —
PMax geo targeting lives in Google Ads raw_data and is not yet synced into a
typed column.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.account import AdAccount
from app.models.ad_set import AdSet
from app.models.campaign import Campaign
from app.services.booking_match_service import normalize_branch

# Branch canonical key → ISO-2 home country
BRANCH_COUNTRY_MAP: dict[str, str] = {
    "Saigon": "VN",
    "Osaka": "JP",
    "Taipei": "TW",
    "1948": "TW",
    "Oani": "TW",
    "Bread": "TW",
}


def home_country_for_account(db: Session, account_id: str) -> str | None:
    """Resolve an ad account to the home country of its branch.

    Returns the ISO-2 code, or None if the account_name cannot be mapped to a
    known branch (e.g. a test account). Detectors should treat None as
    "no seasonal filter" — safer to under-fire than to fire Tet on Osaka.
    """
    account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
    if not account:
        return None
    branch = normalize_branch(account.account_name)
    if not branch:
        return None
    return BRANCH_COUNTRY_MAP.get(branch)


def targeted_countries_for_campaign(db: Session, campaign_id: str) -> set[str]:
    """Distinct ISO-2 countries targeted by a campaign's active ad sets.

    Reads from the parsed AdSet.country column. Unknown / missing values are
    skipped. Returns an empty set if the campaign has no synced ad sets
    (e.g. PMax — targeting is captured only in raw_data today).
    """
    rows = (
        db.query(AdSet.country)
        .filter(AdSet.campaign_id == campaign_id)
        .filter(AdSet.country.isnot(None))
        .filter(AdSet.country != "")
        .filter(AdSet.country != "Unknown")
        .distinct()
        .all()
    )
    return {row[0].upper() for row in rows if row[0]}


def relevant_country_codes_for_campaign(
    db: Session, campaign: Campaign,
) -> set[str]:
    """Home country ∪ targeted countries for a single campaign."""
    codes: set[str] = set()
    home = home_country_for_account(db, campaign.account_id)
    if home:
        codes.add(home)
    codes |= targeted_countries_for_campaign(db, campaign.id)
    return codes


def relevant_country_codes_for_account(
    db: Session, account_id: str,
) -> set[str]:
    """Home country ∪ all countries targeted across the account's active campaigns.

    Used by account-level detectors (LOW_SEASON_SHIFT_TO_DEMANDGEN).
    """
    codes: set[str] = set()
    home = home_country_for_account(db, account_id)
    if home:
        codes.add(home)

    rows = (
        db.query(AdSet.country)
        .join(Campaign, Campaign.id == AdSet.campaign_id)
        .filter(Campaign.account_id == account_id)
        .filter(Campaign.status == "ACTIVE")
        .filter(AdSet.country.isnot(None))
        .filter(AdSet.country != "")
        .filter(AdSet.country != "Unknown")
        .distinct()
        .all()
    )
    codes |= {row[0].upper() for row in rows if row[0]}
    return codes
