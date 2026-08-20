"""Fit platform-supplied names to the width of the columns that store them.

Every name column in the schema is VARCHAR(500) — ads.name, campaigns.name,
ad_sets.name, ad_combos.ad_name, ad_daily_metrics.{campaign,adset,ad}_name.
Postgres does not truncate on overflow, it raises StringDataRightTruncation,
and that error aborts the whole transaction: on 2026-08-20 a single TikTok
Smart+ ad — whose auto-generated ad_name is the entire caption, ~750 chars —
stopped an entire advertiser from syncing, so a live campaign never reached
the database at all.

Widening one column is not an option: ad_name is the identity key the creative
library joins on (see services/creative_sync.apply_ad_renames), so ads.name and
ad_combos.ad_name must hold the *identical* string. Fitting at the model layer
keeps every table in agreement no matter which write path produced the value.

The tail matters as much as the head — TikTok's generated names end in a
timestamp, and two ads from the same caption differ only there — so a plain
head-cut would collide distinct ads into one combo. The 8-char digest of the
full name restores uniqueness and is deterministic, so re-syncing an unchanged
ad produces the same fitted name and never looks like a rename.
"""
import hashlib
import logging

logger = logging.getLogger(__name__)

NAME_MAX = 500
_ELLIPSIS = "\u2026"


def fit_name(value, limit: int = NAME_MAX):
    """Return `value` unchanged when it fits, else a deterministic short form."""
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    if len(text) <= limit:
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    fitted = text[: limit - len(_ELLIPSIS) - len(digest)] + _ELLIPSIS + digest
    logger.warning(
        "Name exceeds %d chars (%d), storing fitted form ending %s: %.80s...",
        limit, len(text), digest, text,
    )
    return fitted
