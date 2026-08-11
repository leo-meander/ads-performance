"""The chat system prompt never told Claude what today's date was, so any
relative date range ("60 ngày gần đây", "this month") was a guess — observed
computing a 2025 window against an August 2026 system clock, so every
get_ad_performance call returned zero rows. _date_context_block() anchors the
model to the real system date.
"""
from __future__ import annotations

from datetime import date

from app.services.ai_client import _date_context_block


def test_date_context_block_states_real_today(monkeypatch):
    fixed_today = date(2026, 8, 10)

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return fixed_today

    monkeypatch.setattr("app.services.ai_client.date", _FixedDate)
    block = _date_context_block()
    assert block["type"] == "text"
    assert "2026-08-10" in block["text"]
    assert "Monday" in block["text"]
    assert "cache_control" not in block


def test_date_context_block_not_marked_for_prompt_caching():
    """Must stay a plain block, not cache_control — it changes every day, and
    marking it ephemeral would invalidate the cache daily instead of once."""
    assert "cache_control" not in _date_context_block()
