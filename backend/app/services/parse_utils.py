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
    ISO 3166-1 alpha-2 code. A trailing "All" token (after space or underscore)
    means the campaign targets multiple countries → return the "ALL" marker.

    When a campaign name carries no recognisable country suffix (the suffix was
    simply forgotten), we treat it as multi-country and return "ALL" rather than
    "Unknown". This keeps its spend/revenue in the dashboard totals — the
    country KPI summary (routers/country.py) drops "Unknown"/NULL rows but keeps
    "ALL", so an un-suffixed campaign would otherwise silently vanish from the
    branch totals. Only a truly empty/missing name stays "Unknown".
    """
    if not name:
        return "Unknown"
    stripped = name.strip()
    if not stripped:
        return "Unknown"

    last_token = re.split(r"[\s_]+", stripped)[-1] if stripped else ""
    if last_token.upper() == "ALL":
        return "ALL"

    tail = stripped[-2:].upper()
    if tail in _GOOGLE_VALID_ISO:
        return tail
    # No ISO suffix → assume the campaign targets all countries. Still log so we
    # can spot names that drifted from the `..._XX` convention.
    logger.warning("No Google country suffix in name, defaulting to ALL: %s", name)
    return "ALL"


def parse_adset_metadata(name: str) -> dict:
    """Parse country from Meta adset name (ISO prefix convention)."""
    return {"country": parse_country(name)}
