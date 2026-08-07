"""Sale / Lead / Engagement classification for the dashboard's campaign toggle.

The toggle splits every campaign three ways and the buckets are mutually
exclusive, so the same predicate has to back every endpoint it touches (KPI
cards, daily spend, funnel, breakdowns, country comparison, campaign table).
Keeping the clauses in one place stops those endpoints from drifting apart —
they used to carry four hand-copied `ilike("%Lea%")` pairs.

Rules, in priority order:

1. Lead       — campaign name carries the "Lea" token. Oldest convention here,
                predates objective sync; campaign names are under the ops team's
                control so it stays authoritative over the platform objective.
2. Engagement — the platform's own objective says so: TikTok reports
                ENGAGEMENT / REACH / VIDEO_VIEWS, Meta OUTCOME_ENGAGEMENT /
                OUTCOME_AWARENESS / POST_ENGAGEMENT / VIDEO_VIEWS. The name
                fallback catches campaigns whose objective didn't survive sync
                (TikTok campaigns created before objective_type was mapped).
3. Sale       — the remainder.

Note this moves campaigns *out* of Sale: an awareness or video-view campaign
that used to be counted as Sale (Sale was "not Lead") now lands in Engagement.
That is the point of the three-way split, but it does shift historical Sale
totals on the dashboard.
"""

from sqlalchemy import func, or_

from app.models.campaign import Campaign

# Matched as substrings against the platform objective, uppercased. Substring
# (not equality) because Meta prefixes the modern objectives with OUTCOME_ and
# still returns the legacy names on older campaigns.
ENGAGEMENT_OBJECTIVE_TOKENS = (
    "ENGAGEMENT",
    "VIDEO_VIEW",
    "REACH",
    "AWARENESS",
    "LIKES",
)

CAMPAIGN_TYPES = ("sale", "lead", "engagement")


def lead_clause():
    return Campaign.name.ilike("%Lea%")


def engagement_clause():
    """Objective-first, name as fallback. COALESCE keeps NULL objectives out of
    three-valued-logic territory so `~engagement_clause()` stays usable.

    The name fallback matches the "Engag" stem, not the full word: live campaign
    names include "Engagment Store 1" and "Engagment Store 2" (missing an 'e'),
    and a full-word match would silently drop them if their objective were ever
    missing."""
    objective = func.upper(func.coalesce(Campaign.objective, ""))
    return or_(
        *[objective.contains(token) for token in ENGAGEMENT_OBJECTIVE_TOKENS],
        Campaign.name.ilike("%engag%"),
    )


def apply_campaign_type(q, campaign_type: str | None):
    """Scope a query joined against Campaign to one bucket. Unknown values and
    None are treated as 'all' — the toggle's default."""
    if campaign_type == "lead":
        return q.filter(lead_clause())
    if campaign_type == "engagement":
        return q.filter(~lead_clause(), engagement_clause())
    if campaign_type == "sale":
        return q.filter(~lead_clause(), ~engagement_clause())
    return q
