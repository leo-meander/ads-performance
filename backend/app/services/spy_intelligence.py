"""AI layer over the competitor ledger: per-ad breakdown, then patterns.

Two passes, deliberately separate:

1. `breakdown_ads` reads one ad at a time and fills in hook / angle / offer /
   USP / format / CTA / target. Cheap model, runs on the long-running ads the
   crawl surfaces, and the result is cached on the row so it is paid for once.

2. `build_pattern_digest` never re-reads the ads. It counts the structured
   angles from pass 1 and only then asks a stronger model to interpret the
   tally. Counting in SQL rather than in the prompt is what makes the
   percentages trustworthy - an LLM asked to both read 40 ads and tally them
   will approximate the tally.

Angles come from a fixed taxonomy. Free-text angles cannot be counted across
ads, and an uncountable angle is useless to the digest.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone

from anthropic import Anthropic
from sqlalchemy.orm import Session

from app.config import settings
from app.models.spy_analysis_report import SpyAnalysisReport
from app.models.spy_competitor_ad import SpyCompetitorAd

logger = logging.getLogger(__name__)

BREAKDOWN_MODEL = "claude-haiku-4-5-20251001"
DIGEST_MODEL = "claude-sonnet-5"

# Fixed so the digest can count. Add to this list rather than letting the
# model invent labels, or the tally fragments into synonyms.
ANGLE_TAXONOMY = [
    "location_convenience",
    "transit_proximity",
    "price_discount",
    "room_experience",
    "design_aesthetic",
    "food_beverage",
    "social_atmosphere",
    "family_friendly",
    "couple_romance",
    "business_work",
    "loyalty_direct_booking",
    "urgency_scarcity",
    "seasonal_event",
    "social_proof_reviews",
    "amenity_facility",
]

ANGLE_LABELS = {
    "location_convenience": "Location / convenience",
    "transit_proximity": "Transit / MRT proximity",
    "price_discount": "Price / discount",
    "room_experience": "Room experience",
    "design_aesthetic": "Design / aesthetic",
    "food_beverage": "Food & beverage",
    "social_atmosphere": "Social atmosphere",
    "family_friendly": "Family friendly",
    "couple_romance": "Couple / romance",
    "business_work": "Business / work",
    "loyalty_direct_booking": "Direct booking perk",
    "urgency_scarcity": "Urgency / scarcity",
    "seasonal_event": "Seasonal / event",
    "social_proof_reviews": "Social proof / reviews",
    "amenity_facility": "Amenity / facility",
}

BREAKDOWN_SYSTEM = f"""You break down competitor hotel ads from the Meta Ad Library for MEANDER Group (hotels in Saigon, Taipei, Osaka; plus Oani in Taipei).

Return ONLY a JSON object, no prose, with exactly these keys:
{{
  "hook": "the opening line or visual promise, quoted or paraphrased in <=90 chars",
  "primary_angle": "one id from the list below",
  "secondary_angle": "another id from the list, or null",
  "offer": "the concrete offer (e.g. '10% OFF', 'free breakfast'), or null if none",
  "usp": "the single differentiator claimed, <=80 chars",
  "cta": "the call to action wording, or null",
  "target": "who this is aimed at, <=60 chars",
  "language": "ISO 639-1 code of the ad copy",
  "notes": "anything unusual worth a human's attention, <=120 chars, or null"
}}

Allowed angle ids: {", ".join(ANGLE_TAXONOMY)}

Pick the angle that the copy actually leads with, not the one you would
recommend. If the copy is too thin to judge, use the angle the imagery and CTA
imply and say so in notes."""

DIGEST_SYSTEM = """You are a paid-media strategist for MEANDER Group, a hospitality company with hotels in Saigon, Taipei and Osaka (plus Oani, a premium Taipei hotel).

You are given a TALLY that has already been computed from competitor ads that
survived a long time in market. The counts are facts - do not recompute,
re-estimate or contradict them.

Your job is interpretation:
- what the durable patterns say about what works in these markets,
- which patterns MEANDER is not currently exploiting,
- one concrete creative test per high-confidence pattern.

Ground every claim in the tally or in a quoted hook. Say plainly when the
sample is too small to conclude anything - a pattern seen in 2 ads is a hint,
not a finding. Be specific and short. Write in English."""


def _client() -> Anthropic:
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not configured.")
    return Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ad_context(ad: SpyCompetitorAd) -> str:
    bodies = ad.ad_creative_bodies or []
    titles = ad.ad_creative_link_titles or []
    captions = ad.ad_creative_link_captions or []
    return "\n".join([
        f"Advertiser: {ad.page_name or 'Unknown'}",
        f"Country: {ad.country or 'Unknown'}",
        f"Format: {ad.media_type or 'unknown'}",
        f"Platforms: {', '.join(ad.publisher_platforms or []) or 'unknown'}",
        f"Days running: {ad.days_running or 0}",
        f"CTA button: {ad.cta_text or 'n/a'}",
        f"Landing page: {ad.link_url or 'n/a'}",
        f"Body: {' | '.join(bodies[:3]) if bodies else 'n/a'}",
        f"Headline: {' | '.join(titles[:3]) if titles else 'n/a'}",
        f"Caption: {' | '.join(captions[:2]) if captions else 'n/a'}",
    ])


def _parse_json_block(text: str) -> dict | None:
    """Claude occasionally wraps JSON in a fence despite instructions."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None


def breakdown_ads(
    db: Session,
    limit: int = 20,
    min_days_running: int | None = None,
    force: bool = False,
) -> dict:
    """Fill `ai_breakdown` on the longest-running ads that lack one.

    Long-running first because that is where the signal is: an ad a competitor
    has funded for 40 days is worth a model call, a 3-day test is not.
    """
    min_days = (
        settings.SPY_LONG_RUNNING_DAYS if min_days_running is None else min_days_running
    )
    q = db.query(SpyCompetitorAd).filter(
        SpyCompetitorAd.is_active.is_(True),
        SpyCompetitorAd.days_running >= min_days,
    )
    if not force:
        q = q.filter(SpyCompetitorAd.ai_breakdown.is_(None))
    ads = q.order_by(SpyCompetitorAd.days_running.desc()).limit(limit).all()

    if not ads:
        return {"analyzed": 0, "failed": 0, "skipped": 0}

    client = _client()
    analyzed = failed = skipped = 0

    for ad in ads:
        if not (ad.ad_creative_bodies or ad.ad_creative_link_titles):
            # Nothing to read; a breakdown would be invention.
            skipped += 1
            continue
        try:
            resp = client.messages.create(
                model=BREAKDOWN_MODEL,
                max_tokens=700,
                system=BREAKDOWN_SYSTEM,
                messages=[{"role": "user", "content": _ad_context(ad)}],
            )
            parsed = _parse_json_block(resp.content[0].text)
            if not parsed:
                failed += 1
                continue
            if parsed.get("primary_angle") not in ANGLE_TAXONOMY:
                parsed["primary_angle"] = None
            if parsed.get("secondary_angle") not in ANGLE_TAXONOMY:
                parsed["secondary_angle"] = None
            ad.ai_breakdown = parsed
            ad.ai_analyzed_at = _now()
            analyzed += 1
        except Exception:  # noqa: BLE001 - one bad ad must not stop the batch
            logger.exception("[spy-breakdown] ad %s failed", ad.ad_archive_id)
            failed += 1

    db.commit()
    logger.info(
        "[spy-breakdown] analyzed=%d failed=%d skipped=%d", analyzed, failed, skipped
    )
    return {"analyzed": analyzed, "failed": failed, "skipped": skipped}


def compute_tally(db: Session, min_days_running: int | None = None) -> dict:
    """Count angles, formats and CTAs across broken-down long-running ads.

    Pure SQL-side arithmetic. The numbers the UI charts and the numbers the
    digest reasons over are this one function's output, so they can never
    drift apart.
    """
    min_days = (
        settings.SPY_LONG_RUNNING_DAYS if min_days_running is None else min_days_running
    )
    ads = (
        db.query(SpyCompetitorAd)
        .filter(
            SpyCompetitorAd.is_active.is_(True),
            SpyCompetitorAd.days_running >= min_days,
            SpyCompetitorAd.ai_breakdown.isnot(None),
        )
        .all()
    )
    total = len(ads)
    if not total:
        return {
            "total_ads": 0,
            "min_days_running": min_days,
            "patterns": [],
            "formats": [],
            "ctas": [],
            "competitors": [],
            "sample_hooks": [],
        }

    angle_ads: dict[str, list[SpyCompetitorAd]] = {}
    for ad in ads:
        b = ad.ai_breakdown or {}
        for key in ("primary_angle", "secondary_angle"):
            angle = b.get(key)
            if angle in ANGLE_TAXONOMY:
                angle_ads.setdefault(angle, []).append(ad)

    patterns = []
    for angle, members in angle_ads.items():
        pages = {m.page_name for m in members if m.page_name}
        days = [m.days_running or 0 for m in members]
        avg_days = round(sum(days) / len(days)) if days else 0
        # Confidence is about evidence, not enthusiasm: several independent
        # advertisers sustaining an angle for weeks is the bar.
        if len(pages) >= 3 and len(members) >= 5 and avg_days >= 30:
            confidence = "HIGH"
        elif len(pages) >= 2 and len(members) >= 3:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"
        patterns.append({
            "angle": angle,
            "label": ANGLE_LABELS.get(angle, angle),
            "ad_count": len(members),
            "share": round(len(members) / total, 3),
            "competitor_count": len(pages),
            "competitors": sorted(pages),
            "avg_days_running": avg_days,
            "max_days_running": max(days) if days else 0,
            "confidence": confidence,
        })
    patterns.sort(key=lambda p: (-p["ad_count"], -p["avg_days_running"]))

    fmt = Counter(ad.media_type or "unknown" for ad in ads)
    cta = Counter(
        (ad.ai_breakdown or {}).get("cta") or ad.cta_text or "unknown" for ad in ads
    )
    comp = Counter(ad.page_name or "Unknown" for ad in ads)

    sample_hooks = [
        {
            "hook": (ad.ai_breakdown or {}).get("hook"),
            "advertiser": ad.page_name,
            "days_running": ad.days_running,
            "angle": ANGLE_LABELS.get((ad.ai_breakdown or {}).get("primary_angle"), ""),
        }
        for ad in sorted(ads, key=lambda a: -(a.days_running or 0))[:12]
        if (ad.ai_breakdown or {}).get("hook")
    ]

    return {
        "total_ads": total,
        "min_days_running": min_days,
        "patterns": patterns,
        "formats": [{"name": k, "count": v} for k, v in fmt.most_common()],
        "ctas": [{"name": k, "count": v} for k, v in cta.most_common(8)],
        "competitors": [{"name": k, "count": v} for k, v in comp.most_common()],
        "sample_hooks": sample_hooks,
    }


def build_pattern_digest(db: Session, min_days_running: int | None = None) -> dict:
    """Tally, interpret, and store the result as a report row."""
    tally = compute_tally(db, min_days_running=min_days_running)
    if not tally["total_ads"]:
        raise ValueError(
            "No long-running competitor ads have an AI breakdown yet. Run a "
            "crawl, then the breakdown pass, before building the digest."
        )

    prompt = (
        "TALLY (already computed, treat as fact):\n"
        + json.dumps(tally, ensure_ascii=False, indent=2)
        + "\n\nWrite the digest as markdown with these sections:\n"
        "## What competitors keep running\n"
        "## What the tally does NOT support\n"
        "## Gaps MEANDER can take\n"
        "## Tests to run next (one per HIGH/MEDIUM pattern)\n"
    )

    client = _client()
    resp = client.messages.create(
        model=DIGEST_MODEL,
        max_tokens=3000,
        system=DIGEST_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    markdown = resp.content[0].text

    report = SpyAnalysisReport(
        title=(
            f"Competitor pattern digest — {tally['total_ads']} ads running "
            f"{tally['min_days_running']}+ days"
        ),
        analysis_type="pattern_digest",
        input_ad_ids=[],
        input_params={"min_days_running": tally["min_days_running"]},
        result_markdown=markdown,
        result_json=tally,
        model_used=DIGEST_MODEL,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return {"report_id": report.id, "tally": tally, "markdown": markdown}
