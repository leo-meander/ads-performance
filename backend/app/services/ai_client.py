"""AI client: Claude API integration with hotel marketing context."""

import logging
from collections.abc import Generator
from datetime import date, timedelta

from anthropic import Anthropic
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.account import AdAccount
from app.models.ad_angle import AdAngle
from app.models.campaign import Campaign
from app.models.keypoint import BranchKeypoint
from app.models.metrics import MetricsCache

logger = logging.getLogger(__name__)

FX_TO_VND = {"VND": 1, "TWD": 800, "JPY": 170, "USD": 25500}

SYSTEM_PROMPT = """You are an expert hotel marketing analyst for MEANDER Group — a hospitality company with 5 hotel branches across Asia:

- **MEANDER Saigon** (Ho Chi Minh City, Vietnam — VND)
- **Oani** (Taipei, Taiwan — TWD, premium boutique hotel)
- **MEANDER Taipei** (Taipei, Taiwan — TWD)
- **MEANDER 1948** (Taipei, Taiwan — TWD)
- **MEANDER Osaka** (Osaka, Japan — JPY)

You deeply understand:
- **Target Audiences (TA):** Solo travelers, Couples, Families, Groups — each has different booking behavior and ad performance
- **Ad Angles:** Marketing angles classified as WIN (ROAS above benchmark), TEST (insufficient data or borderline), LOSE (ROAS below 0.6x benchmark)
- **Branch Keypoints:** Unique selling points per property (location, amenities, experiences, value propositions)
- **Booking Funnel:** Impression → Click → Search → Add to Cart → Checkout → Booking
- **Key Metrics:** ROAS, CPC, CTR, Cost per Booking, ADR (Average Daily Rate), OCC (Occupancy Rate)
- **Creative Library:** Ad copies (CPY), materials (MAT), combos (CMB) with WIN/TEST/LOSE verdicts

When analyzing data:
- Always consider currency differences (VND vs TWD vs JPY) — cross-branch comparisons should use VND equivalent
- Be specific with numbers and percentages
- Provide actionable recommendations, not just observations
- When suggesting ad angles or creative strategies, reference the branch's keypoints and winning angles
- Use Vietnamese or English based on the user's language

Below is the current data context:
"""


def build_context(db: Session) -> str:
    """Build real-time data context for Claude from the database."""
    parts = []
    d7 = date.today() - timedelta(days=7)

    # 1. Branch summary with KPIs
    accounts = db.query(AdAccount).filter(AdAccount.is_active.is_(True)).all()
    parts.append("## Branch Performance (Last 7 Days)")
    for acc in accounts:
        fx = FX_TO_VND.get(acc.currency, 1)
        row = db.query(
            func.sum(MetricsCache.spend).label("spend"),
            func.sum(MetricsCache.impressions).label("impressions"),
            func.sum(MetricsCache.clicks).label("clicks"),
            func.sum(MetricsCache.conversions).label("conversions"),
            func.sum(MetricsCache.revenue).label("revenue"),
        ).join(Campaign, MetricsCache.campaign_id == Campaign.id).filter(
            Campaign.account_id == acc.id, MetricsCache.date >= d7,
        ).one()

        spend = float(row.spend or 0)
        revenue = float(row.revenue or 0)
        clicks = int(row.clicks or 0)
        conversions = int(row.conversions or 0)
        impressions = int(row.impressions or 0)
        roas = revenue / spend if spend > 0 else 0

        parts.append(f"**{acc.account_name}** ({acc.currency})")
        parts.append(f"  Spend: {spend:,.0f} {acc.currency} ({spend * fx:,.0f} VND) | Revenue: {revenue:,.0f} {acc.currency}")
        parts.append(f"  ROAS: {roas:.2f} | Clicks: {clicks:,} | Conversions: {conversions} | Impressions: {impressions:,}")
        if clicks > 0:
            parts.append(f"  CPC: {spend / clicks:,.0f} {acc.currency} | CTR: {clicks / impressions * 100:.2f}%")
        parts.append("")

    # 2. Active campaigns count
    active_count = db.query(Campaign).filter(Campaign.status == "ACTIVE").count()
    total_count = db.query(Campaign).count()
    parts.append(f"## Campaigns: {active_count} active / {total_count} total\n")

    # 3. Branch Keypoints
    keypoints = db.query(BranchKeypoint).filter(BranchKeypoint.is_active.is_(True)).all()
    if keypoints:
        parts.append("## Branch Keypoints")
        kp_map: dict[str, list] = {}
        for kp in keypoints:
            acc = db.query(AdAccount).filter(AdAccount.id == kp.branch_id).first()
            name = acc.account_name if acc else "Unknown"
            kp_map.setdefault(name, []).append(f"  - [{kp.category}] {kp.title}: {kp.description or ''}")
        for name, items in kp_map.items():
            parts.append(f"**{name}**")
            parts.extend(items)
        parts.append("")

    # 4. Ad Angles summary
    angles = db.query(AdAngle).all()
    if angles:
        parts.append("## Ad Angles")
        for status in ["WIN", "TEST", "LOSE"]:
            filtered = [a for a in angles if a.status == status]
            if filtered:
                parts.append(f"**{status}** ({len(filtered)} angles):")
                for a in filtered[:5]:
                    parts.append(f"  - {a.angle_id} [{a.target_audience}]: {a.angle_text[:80]}")
        parts.append("")

    return "\n".join(parts)


def chat_stream(db: Session, messages: list[dict], context: str) -> Generator[str, None, None]:
    """Stream a chat response from Claude with hotel marketing context."""
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    system = SYSTEM_PROMPT + "\n" + context

    with client.messages.stream(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text
