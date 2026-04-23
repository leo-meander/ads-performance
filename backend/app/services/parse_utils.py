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


def parse_adset_metadata(name: str) -> dict:
    """Parse country from adset name.

    - First segment "All" (case-insensitive) → "ALL" (multi-country adset).
    - Otherwise: first 2 chars of first segment, uppercased (ISO code).
    """
    if not name:
        return {"country": "Unknown"}

    first = name.split("_")[0].strip() if name else ""
    if first.upper() == "ALL":
        return {"country": "ALL"}

    country = first.upper()[:2] if first else "Unknown"
    if not country or len(country) < 2:
        logger.warning("Could not parse country from adset: %s", name)
        country = "Unknown"

    return {"country": country}
