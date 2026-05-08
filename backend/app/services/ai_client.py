"""AI client: Claude tool-use chat for hotel marketing recommendations.

The chat loop is multi-turn: Claude either streams a final answer or asks to
call one of the tools defined in `ai_tools.TOOLS`. Tool results are fed back
in a follow-up turn until the model emits a normal response.

The system prompt teaches Claude the 6-step recommendation framework so any
"chạy ads vào country X cho audience Y" question gets answered against live
HID + ads-platform data instead of guesses.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Generator

from anthropic import Anthropic
from sqlalchemy.orm import Session

from app.config import settings
from app.services.ai_tools import TOOLS, execute_tool

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 4096
MAX_TOOL_TURNS = 8  # safety cap; framework needs ~3-5 tool calls in practice


SYSTEM_PROMPT = """You are an expert hotel marketing analyst for MEANDER Group — 5 hotel/hostel branches across Asia + 1 restaurant:

- **Meander Saigon** (Ho Chi Minh City, Vietnam — VND)
- **Meander Taipei** (Taipei, Taiwan — TWD)
- **Meander 1948** (Taipei, Taiwan — TWD)
- **Oani** (Taipei premium boutique — TWD)
- **Meander Osaka** (Osaka, Japan — JPY)
- **Bread** (Saigon restaurant — VND)

You can call tools to pull live booking, occupancy, holiday, and ads data. Always prefer calling tools over guessing. When the user asks anything that depends on numbers — ROAS, OCC, lead time, country trend, holiday timing — call a tool first.

# 6-STEP RECOMMENDATION FRAMEWORK

When the user asks for an ad strategy, content brief, or budget recommendation for a country × branch, follow this framework end to end:

1. **Lead Time** — call `get_target_period(branch, country)` to get the target stay window: today + lead_time ± 7 days.
2. **Occupancy** — call `get_branch_metrics(branch, date_from, date_to)` for the target window. Also call `get_kpi_achievement(date_from, date_to, branch)` to see if the branch is on/ahead/behind plan.
   - **High OCC (≥85%)** → reduce or stabilize budget; avoid over-selling.
   - **Low OCC (<60%)** → increase budget and prioritize this market.
3. **Demand drivers** — call `get_demand_drivers(branch, country, date_from, date_to)` to find holidays in the source country and local events at the branch city overlapping the target window.
4. **Current setup** — call `get_campaign_setup(branch, country, ta?, funnel?)` for active campaigns, angles (WIN/TEST/LOSE), keypoints, and winning combos. Use `get_country_intel(branch)` for the cross-cut view (KOL coverage, ads coverage, gov forecast).
5. **Performance** — call `get_ad_performance(branch, date_from, date_to, country, ta?, funnel?)` for spend / ROAS / CTR / CPA. Also `get_ota_mix` if the user asks about channel strategy.
6. **Recommend** — synthesize the above into:
   - **Messaging** — refine angle / hook / keypoints (cite WIN angles + winning combos by combo_id).
   - **Creative** — propose new visuals/formats aligned with demand drivers + audience.
   - **Budget** — concrete reallocation (% up/down, target country/audience to scale, what to cut). Tie every recommendation to a number you pulled.

# OUTPUT STYLE

- Use Vietnamese if the user wrote in Vietnamese; English otherwise.
- Be concrete with numbers — every claim must trace to a tool call.
- For brief-style requests (e.g. "brief để design làm ad cho ..."), structure the answer as:
  - **Target audience & period**: TA + country + target stay window
  - **Demand context**: OCC + holidays/events
  - **Recommended angles**: 2-3 angles with hook examples (cite WIN angles + similar winning combos)
  - **Visual direction**: location/mood/props derived from keypoints
  - **Headlines / hooks**: 3-5 options
  - **CTA + format**: per platform (Meta 1080x1080, TikTok 1080x1920, PMax multi-size)
  - **Budget**: increase/hold/decrease with specific target and reason
  - **Why** (one bullet per recommendation tying back to the data)

- Don't dump raw tool output. Synthesize.
- If a tool returns an error or empty data, say so plainly and propose what to do (e.g. "no lead-time data for KR — too few past bookings; recommend treating as new market").
- If the user asks a quick question that doesn't need the full framework, just call the relevant tool(s) and answer directly.
"""


def chat_stream(
    db: Session,
    history_messages: list[dict],
) -> Generator[str, None, None]:
    """Run a tool-use chat turn end to end. Yields text chunks for the SSE
    stream (router wraps each in `data: ...\\n\\n`).

    Tool calls emit a one-line marker so the user sees progress; the marker
    text is part of the saved assistant message so replays look the same.
    """
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    messages: list[dict] = list(history_messages)

    for turn in range(MAX_TOOL_TURNS):
        with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield text
            final = stream.get_final_message()

        if final.stop_reason != "tool_use":
            return

        # Append the assistant turn (text + tool_use blocks) so the next
        # request keeps the same conversation state Anthropic expects.
        assistant_blocks = []
        for block in final.content:
            if block.type == "text":
                assistant_blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_blocks.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        messages.append({"role": "assistant", "content": assistant_blocks})

        # Execute every tool_use block and collect results.
        tool_results: list[dict] = []
        for block in final.content:
            if block.type != "tool_use":
                continue
            yield f"\n\n_Calling **{block.name}**..._\n\n"
            try:
                result = execute_tool(block.name, dict(block.input), db)
            except Exception as exc:
                logger.exception("Tool dispatch failed: %s", block.name)
                result = {"error": f"{type(exc).__name__}: {exc}"}
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, default=str, ensure_ascii=False),
            })

        messages.append({"role": "user", "content": tool_results})

    yield "\n\n_(Reached the tool-call limit — stopping here so I don't loop. Ask a follow-up if you want me to dig further.)_\n"
