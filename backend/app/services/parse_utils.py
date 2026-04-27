"""Name parsing engine — extracts TA, funnel stage, and country from campaign/adset names."""

import logging
import re

logger = logging.getLogger(__name__)

TA_WHITELIST = ["Solo", "Couple", "Friend", "Group", "Business"]
FUNNEL_PATTERN = re.compile(r"\[(TOF|MOF|BOF)\]", re.IGNORECASE)


def parse_campaign_metadata(name: str) -> dict:
    """Parse TA and funnel stage from campaign name.

    TA: first match from whitelist (case-insensitive).
    Funnel stage: bracket pattern [TOF], [MOF], [BOF].
    """
    if not name:
        return {"ta": "Unknown", "funnel_stage": "Unknown"}

    ta = next((t for t in TA_WHITELIST if t.lower() in name.lower()), "Unknown")
    match = FUNNEL_PATTERN.search(name)
    funnel_stage = match.group(1).upper() if match else "Unknown"

    if ta == "Unknown":
        logger.warning("Unknown TA for campaign: %s", name)
    if funnel_stage == "Unknown":
        logger.warning("Unknown funnel stage for campaign: %s", name)

    return {"ta": ta, "funnel_stage": funnel_stage}


def parse_country(name: str) -> str:
    """Extract country code from the first underscore-segment of a name.

    - First segment "All" (case-insensitive) → "ALL" (multi-country marker).
    - Otherwise: first 2 chars of first segment, uppercased (ISO 3166-1 alpha-2).
    - Returns "Unknown" when no valid 2-char prefix can be extracted.

    Used for Meta adset names (which carry the ISO prefix as the first segment).
    """
    if not name:
        return "Unknown"

    first = name.split("_")[0].strip()
    if first.upper() == "ALL":
        return "ALL"

    country = first.upper()[:2] if first else "Unknown"
    if not country or len(country) < 2:
        logger.warning("Could not parse country from name: %s", name)
        return "Unknown"
    return country


# Allow-list of ISO codes we recognise — must mirror country_utils.COUNTRY_NAMES.
_GOOGLE_VALID_ISO = {
    "AU", "CA", "CN", "DE", "HK", "ID", "IN", "JP", "KR",
    "MY", "PH", "SG", "TH", "TW", "UK", "US", "VN",
}


def parse_google_country(name: str) -> str:
    """Extract ISO country code from the LAST 2 characters of a Google campaign name.

    Google campaigns at MEANDER follow the convention `..._XX` where XX is the
    ISO 3166-1 alpha-2 code. Returns "Unknown" if the trailing 2 chars aren't
    a recognised ISO code (e.g. campaign name ends in digits or unknown letters).
    """
    if not name:
        return "Unknown"
    tail = name.strip()[-2:].upper()
    if tail in _GOOGLE_VALID_ISO:
        return tail
    logger.warning("Could not parse Google country from name: %s", name)
    return "Unknown"


def parse_adset_metadata(name: str) -> dict:
    """Parse country from Meta adset name (ISO prefix convention)."""
    return {"country": parse_country(name)}
