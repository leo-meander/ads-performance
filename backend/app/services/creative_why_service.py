"""AI "why did this combo win/lose" analyst.

Read-only narrative companion to the rule-based insight in
creative_intelligence._heuristic_insight. The heuristic gives instant signed
reasons; this asks Claude Sonnet to weave the same grounded facts (metrics vs
branch averages, copy, visual tags, angle) into a short diagnosis + one
actionable takeaway. It never invents numbers — every figure is passed in.

Graceful by design: returns {"error": ...} when the model/key is unavailable so
the caller can fall back to the heuristic panel alone.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from anthropic import Anthropic
from sqlalchemy.orm import Session

from app.config import settings
from app.models.account import AdAccount
from app.models.ad_angle import AdAngle
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.creative_visual_tag import CreativeVisualTag

logger = logging.getLogger(__name__)

WHY_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 700

SYSTEM_PROMPT = """You are a senior performance-marketing analyst for MEANDER Group hotels.

You are given ONE Meta ad combo's metrics alongside its branch averages, plus its copy, creative format, and visual tags. Explain — in plain, confident language — WHY this ad earned its verdict (WIN / TEST / LOSE).

Rules:
- Ground every claim in the numbers provided. NEVER invent metrics, prices, or amenities.
- Lead with the single biggest driver of the verdict, then 1-2 supporting factors.
- If it's a video, weigh hook rate (does the opener stop the scroll?) and thruplay.
- Tie the creative/copy/visual-tags to the performance when the link is plausible, but don't overreach.
- End with ONE concrete, actionable next step (scale, iterate the hook, swap the angle, kill it, etc.).

Output format — GitHub-flavored markdown, no headings:
- A 2-3 sentence diagnosis paragraph.
- Then a line "**Next step:** ..." with the single recommendation.

Keep it under 130 words. Write in English."""


def _fmt_pct(v: Optional[float]) -> str:
    return f"{v * 100:.1f}%" if v is not None else "n/a"


def _fmt(v: Optional[float]) -> str:
    return f"{v:.2f}" if v is not None else "n/a"


def _branch_averages(db: Session, branch_id: str) -> dict[str, Any]:
    from sqlalchemy import func

    agg = (
        db.query(
            func.sum(AdCombo.spend).label("spend"),
            func.sum(AdCombo.revenue).label("revenue"),
            func.avg(AdCombo.ctr).label("ctr"),
            func.avg(AdCombo.cost_per_purchase).label("cpp"),
            func.avg(AdCombo.hook_rate).label("hook"),
            func.avg(AdCombo.thruplay_rate).label("thru"),
        )
        .filter(AdCombo.branch_id == branch_id)
        .first()
    )
    s = float(agg.spend or 0)
    r = float(agg.revenue or 0)
    return {
        "benchmark_roas": (r / s) if s > 0 else None,
        "ctr": float(agg.ctr) if agg.ctr is not None else None,
        "cpp": float(agg.cpp) if agg.cpp is not None else None,
        "hook": float(agg.hook) if agg.hook is not None else None,
        "thru": float(agg.thru) if agg.thru is not None else None,
    }


def analyze_why(
    db: Session, *, combo: AdCombo, client: Optional[Anthropic] = None
) -> dict[str, Any]:
    """Return {"analysis": markdown} or {"error": str}."""
    if client is None:
        if not settings.ANTHROPIC_API_KEY:
            return {"error": "ANTHROPIC_API_KEY not configured"}
        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    branch = db.query(AdAccount).filter(AdAccount.id == combo.branch_id).first()
    copy = db.query(AdCopy).filter(AdCopy.copy_id == combo.copy_id).first() if combo.copy_id else None
    material = (
        db.query(AdMaterial).filter(AdMaterial.material_id == combo.material_id).first()
        if combo.material_id else None
    )
    angle = db.query(AdAngle).filter(AdAngle.angle_id == combo.angle_id).first() if combo.angle_id else None
    avgs = _branch_averages(db, combo.branch_id)

    tags = []
    if material:
        tags = [
            f"{t.tag_category}={t.tag_value}"
            for t in db.query(CreativeVisualTag)
            .filter(CreativeVisualTag.material_id == material.material_id)
            .all()
        ]

    roas = float(combo.roas) if combo.roas is not None else None
    ctr = float(combo.ctr) if combo.ctr is not None else None
    hook = float(combo.hook_rate) if combo.hook_rate is not None else None
    thru = float(combo.thruplay_rate) if combo.thruplay_rate is not None else None
    cpp = float(combo.cost_per_purchase) if combo.cost_per_purchase is not None else None

    lines = [
        f"Branch: {branch.account_name if branch else combo.branch_id}",
        f"Ad name: {combo.ad_name or combo.combo_id}",
        f"Verdict: {combo.verdict}",
        f"Format: {material.material_type if material else 'unknown'}",
        f"Target audience: {combo.target_audience or 'n/a'} | Country: {combo.country or 'n/a'}",
        "",
        "METRICS (this combo vs branch average):",
        f"- ROAS: {_fmt(roas)}x vs benchmark {_fmt(avgs['benchmark_roas'])}x",
        f"- Bookings: {combo.conversions if combo.conversions is not None else 0}",
        f"- Cost per booking: {_fmt(cpp)} vs avg {_fmt(avgs['cpp'])}",
        f"- CTR: {_fmt_pct(ctr)} vs avg {_fmt_pct(avgs['ctr'])}",
    ]
    if material and material.material_type == "video":
        lines += [
            f"- Hook rate (3s): {_fmt_pct(hook)} vs avg {_fmt_pct(avgs['hook'])}",
            f"- Thruplay: {_fmt_pct(thru)} vs avg {_fmt_pct(avgs['thru'])}",
        ]
    lines.append("")
    if angle:
        lines.append(f"Angle: {angle.angle_type or angle.hook or angle.angle_id}")
    if copy:
        lines.append(f"Headline: {copy.headline}")
        if copy.body_text:
            lines.append(f"Body: {copy.body_text[:280]}")
        if copy.cta:
            lines.append(f"CTA: {copy.cta}")
    if tags:
        lines.append("Visual tags: " + ", ".join(tags[:12]))

    user_message = "\n".join(lines)

    try:
        resp = client.messages.create(
            model=WHY_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        logger.exception("Combo why-analysis model call failed")
        return {"error": f"model_error: {e!r}"[:300]}

    text_blocks = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    analysis = (text_blocks[0] if text_blocks else "").strip()
    if not analysis:
        return {"error": "Model returned no analysis"}

    return {"combo_id": combo.combo_id, "analysis": analysis, "model": WHY_MODEL}
