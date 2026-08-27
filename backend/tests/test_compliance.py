"""Menu compliance -- the Gadchiroli-precedent feature (Section 1).

The thresholds are the whole design. Too strict and every normal day is flagged,
the officer stops reading the alerts, and the system is worse than nothing. Too
loose and a kitchen that served four of five items passes. Each test below pins
one side of that balance.
"""

from __future__ import annotations

from app.ai.compliance import PlateObservation, evaluate

MENU = ["dal", "roti", "sabzi", "banana"]


def plates(codes, n=10, flags=()):
    return [PlateObservation(tuple(codes), tuple(flags)) for _ in range(n)]


def test_a_fully_served_menu_is_compliant() -> None:
    result = evaluate(prescribed=MENU, plates=plates(MENU))
    assert result.compliance_pct == 100.0
    assert result.flagged is False
    assert result.missing_items == ()


def test_a_missing_item_is_flagged_with_an_actionable_reason() -> None:
    """Section 15: this system flags and documents; a human acts. So the flag
    has to tell the officer what to act on."""
    result = evaluate(prescribed=MENU, plates=plates(["dal", "roti", "sabzi"]))
    assert result.flagged is True
    assert result.missing_items == ("banana",)
    assert result.compliance_pct == 75.0
    assert "Banana" in result.flag_reason_en
    assert "केला" in result.flag_reason_hi
    assert " | " in result.flag_reason


def test_a_few_children_refusing_an_item_is_not_a_kitchen_failure() -> None:
    """The reason aggregation is per-centre-per-day rather than per-plate. Two
    children who skipped the banana is not a menu that was not served."""
    observations = plates(MENU, 8) + plates(["dal", "roti", "sabzi"], 2)
    result = evaluate(prescribed=MENU, plates=observations)
    assert result.flagged is False
    assert result.item_presence["banana"] == 0.8


def test_an_item_on_a_minority_of_plates_counts_as_not_served() -> None:
    """A token serving to a few children must not mask a shortfall."""
    observations = plates(MENU, 2) + plates(["dal", "roti", "sabzi"], 8)
    result = evaluate(prescribed=MENU, plates=observations)
    assert result.flagged is True
    assert "banana" in result.missing_items


def test_presence_shares_are_reported_so_borderline_calls_are_visible() -> None:
    observations = plates(MENU, 6) + plates(["dal", "roti", "sabzi"], 4)
    result = evaluate(prescribed=MENU, plates=observations)
    assert result.item_presence["banana"] == 0.6
    assert result.flagged is False  # exactly at the threshold, inclusive


def test_food_quality_problems_flag_even_when_the_menu_is_complete() -> None:
    """The second Gadchiroli failure mode: everything served, but the dal is
    watery. Invisible in a register, visible in a photograph."""
    result = evaluate(prescribed=MENU, plates=plates(MENU, flags=["watery_appearance"]))
    assert result.compliance_pct == 100.0
    assert result.flagged is True
    assert result.quality_findings == ("watery_appearance",)
    assert "पतली" in result.flag_reason_hi


def test_one_odd_plate_does_not_make_a_quality_finding() -> None:
    observations = plates(MENU, 9) + plates(MENU, 1, flags=["watery_appearance"])
    result = evaluate(prescribed=MENU, plates=observations)
    assert result.flagged is False


def test_camera_problems_are_never_reported_as_kitchen_problems() -> None:
    """A blurred photograph says the camera failed, not the cook. Telling an
    officer otherwise sends them to a school that did nothing wrong."""
    for flag in ("image_blurred", "image_too_dark", "plate_not_visible"):
        result = evaluate(prescribed=MENU, plates=plates(MENU, flags=[flag]))
        assert result.flagged is False, f"{flag} must not flag a centre"
        assert result.quality_findings == ()


def test_a_day_with_no_captures_is_neither_pass_nor_fail() -> None:
    """Reporting 0% would read as a kitchen failure when it is a missing upload."""
    result = evaluate(prescribed=MENU, plates=[])
    assert result.plates_analysed == 0
    assert result.flagged is False


def test_extra_items_are_recorded_but_do_not_flag() -> None:
    """Serving more than prescribed is not a compliance failure."""
    result = evaluate(prescribed=MENU, plates=plates([*MENU, "milk"]))
    assert result.unexpected_items == ("milk",)
    assert result.flagged is False


def test_items_outside_the_vocabulary_are_ignored_in_the_prescription() -> None:
    result = evaluate(prescribed=[*MENU, "unknown_dish"], plates=plates(MENU))
    assert "unknown_dish" not in result.prescribed_items
    assert result.flagged is False


def test_a_completely_missed_menu_reports_zero_percent() -> None:
    result = evaluate(prescribed=MENU, plates=plates(["milk"]))
    assert result.compliance_pct == 0.0
    assert result.flagged is True
    assert set(result.missing_items) == set(MENU)


def test_a_flagged_day_always_carries_a_reason() -> None:
    """The database CHECK constraint enforces this too; both matter."""
    for observations in (plates(["dal"]), plates(MENU, flags=["watery_appearance"])):
        result = evaluate(prescribed=MENU, plates=observations)
        assert result.flagged and result.flag_reason
