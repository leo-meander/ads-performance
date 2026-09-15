"""Tests for how a reservation's rate plan is resolved.

The PMS sends `rate_plan_name` as its own field. The sync used to ignore it and
re-derive the plan from a bracketed group anchored to the END of `room_type`,
which resolved for under 8% of reservations on every branch -- so a plan like
"EARLY26 2 NIGHTS" never reached Booking from Ads and an early-bird campaign
appeared to drive no early-bird stays.

These lock in both halves of the fix: the real field wins, and the room_type
fallback no longer drops plans that aren't last in the string.
"""
from __future__ import annotations

from app.services.reservation_sync import (
    _extract_rate_plan,
    extract_rate_plan_from_room_type,
)


# --- the authoritative PMS field -------------------------------------------

def test_pms_field_is_preferred_over_room_type():
    raw = {
        "rate_plan_name": "EARLY26 2 NIGHTS",
        "room_type": "Standard Double (KOL_someone)",
    }
    assert _extract_rate_plan(raw) == "EARLY26 2 NIGHTS"


def test_falls_back_to_room_type_when_field_absent():
    raw = {"room_type": "Standard Twin (KOL_whatweieats)"}
    assert _extract_rate_plan(raw) == "KOL_whatweieats"


def test_blank_pms_field_falls_back_rather_than_winning():
    raw = {"rate_plan_name": "   ", "room_type": "Standard Twin (KOL_x)"}
    assert _extract_rate_plan(raw) == "KOL_x"


def test_no_plan_anywhere_is_none():
    assert _extract_rate_plan({"room_type": "Standard Double"}) is None
    assert _extract_rate_plan({}) is None


def test_pms_field_is_trimmed():
    assert _extract_rate_plan({"rate_plan_name": "  EARLY26 3+ NIGHTS  "}) == "EARLY26 3+ NIGHTS"


# --- the room_type fallback -------------------------------------------------

def test_nested_parentheses_take_the_outer_group():
    """The dominant production shape. Plan names carry their own qualifier, so
    the group is nested — and both previous implementations got it wrong:
    the end-anchored regex returned None, and an "every bracketed group"
    regex returned ">2 night", the qualifier stripped of the plan it
    qualifies, which reads like real data."""
    assert extract_rate_plan_from_room_type(
        "8 Beds Mixed Dorm Shared Bathroom (Extension Promotion (>2 night))"
    ) == "Extension Promotion (>2 night)"


def test_nested_group_with_trailing_text():
    assert extract_rate_plan_from_room_type(
        "Double Room (Early Bird (3+ nights)) x1"
    ) == "Early Bird (3+ nights)"


def test_unclosed_group_is_dropped_not_raised():
    """room_type is free text typed by staff and this runs inside the sync
    loop — a stray bracket must never break a sync."""
    assert extract_rate_plan_from_room_type("Double Room (Extension Promotion") is None
    assert extract_rate_plan_from_room_type("Double Room )oops(") is None


def test_inner_bracket_of_another_kind_stays_content():
    assert extract_rate_plan_from_room_type(
        "Double Room (Promo [winter])"
    ) == "Promo [winter]"


def test_plain_trailing_group_still_works():
    """The shape that already worked must keep working."""
    assert extract_rate_plan_from_room_type("Standard Double (EARLY26 2 NIGHTS)") == "EARLY26 2 NIGHTS"


def test_group_followed_by_trailing_text():
    assert extract_rate_plan_from_room_type("Standard Double (EARLY26 2 NIGHTS) x1") == "EARLY26 2 NIGHTS"
    assert extract_rate_plan_from_room_type(
        "Standard Double (EARLY26 3+ NIGHTS) - Non refundable"
    ) == "EARLY26 3+ NIGHTS"


def test_multi_room_keeps_every_plan_in_order():
    """The old regex returned only 'FLEX' and silently lost the plan on the
    first room — reporting another room's plan rather than showing blank."""
    assert extract_rate_plan_from_room_type(
        "Standard Double (EARLY26 2 NIGHTS), Family Quadruple (FLEX)"
    ) == "EARLY26 2 NIGHTS, FLEX"


def test_multi_room_with_nested_groups():
    assert extract_rate_plan_from_room_type(
        "Dorm (Extension Promotion (>2 night)), Double (Flexible)"
    ) == "Extension Promotion (>2 night), Flexible"


def test_repeated_plan_is_deduped():
    assert extract_rate_plan_from_room_type(
        "Standard Double (EARLY26 2 NIGHTS), Standard Twin (EARLY26 2 NIGHTS)"
    ) == "EARLY26 2 NIGHTS"


def test_full_width_parentheses():
    """CJK keyboards produce these; the old pattern saw no bracket at all."""
    assert extract_rate_plan_from_room_type("Standard Double\uff08EARLY26 2 NIGHTS\uff09") == "EARLY26 2 NIGHTS"


def test_square_brackets():
    assert extract_rate_plan_from_room_type("Standard Double [EARLY26 2 NIGHTS]") == "EARLY26 2 NIGHTS"


def test_no_bracket_is_none():
    assert extract_rate_plan_from_room_type("Standard Double") is None
    assert extract_rate_plan_from_room_type("Standard Double - EARLY26 2 NIGHTS") is None


def test_empty_group_is_none():
    assert extract_rate_plan_from_room_type("Standard Double ()") is None


def test_none_and_blank_input():
    assert extract_rate_plan_from_room_type(None) is None
    assert extract_rate_plan_from_room_type("") is None
