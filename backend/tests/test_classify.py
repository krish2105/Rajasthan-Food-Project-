"""Threshold boundaries for nutritional status classification.

Every WHO cut-off is a strict inequality on one side and inclusive on the other.
Getting that backwards mislabels children sitting exactly on a cut-off, which is
where the largest number of them sit. Each boundary is asserted from both sides.
"""

from __future__ import annotations

import pytest

from app.growth import classify


@pytest.mark.parametrize(
    ("whz", "expected"),
    [
        (-4.00, "severe_acute_malnutrition"),
        (-3.01, "severe_acute_malnutrition"),
        (-3.00, "moderate_acute_malnutrition"),  # exactly -3 is MAM, not SAM
        (-2.01, "moderate_acute_malnutrition"),
        (-2.00, "normal"),  # exactly -2 is normal
        (0.00, "normal"),
        (2.00, "normal"),
        (2.01, "overweight"),
        (3.00, "overweight"),
        (3.01, "obese"),
    ],
)
def test_wasting_boundaries(whz: float, expected: str) -> None:
    assert classify.classify_wasting(whz) == expected


@pytest.mark.parametrize(
    ("baz", "expected"),
    [
        (-3.01, "severe_thinness"),
        (-3.00, "thinness"),
        (-2.01, "thinness"),
        (-2.00, "normal"),
        (1.00, "normal"),
        (1.01, "overweight"),  # WHO 2007 overweight starts at >+1SD for 5-19y
        (2.00, "overweight"),
        (2.01, "obesity"),
    ],
)
def test_thinness_boundaries(baz: float, expected: str) -> None:
    assert classify.classify_thinness(baz) == expected


def test_positive_cutoffs_differ_between_the_two_age_bands() -> None:
    """A +1.5 z-score is normal under 5 but overweight from 5 years.

    This asymmetry is real and easy to flatten by accident when the two
    classifiers get "unified".
    """
    assert classify.classify_wasting(1.5) == "normal"
    assert classify.classify_thinness(1.5) == "overweight"


@pytest.mark.parametrize(
    ("haz", "expected"),
    [(-3.01, "severely_stunted"), (-3.00, "stunted"), (-2.01, "stunted"), (-2.00, "normal")],
)
def test_stunting_boundaries(haz: float, expected: str) -> None:
    assert classify.classify_stunting(haz) == expected


@pytest.mark.parametrize(
    ("waz", "expected"),
    [
        (-3.01, "severely_underweight"),
        (-3.00, "underweight"),
        (-2.01, "underweight"),
        (-2.00, "normal"),
    ],
)
def test_underweight_boundaries(waz: float, expected: str) -> None:
    assert classify.classify_underweight(waz) == expected


def test_none_propagates_as_none() -> None:
    """An index WHO does not define must stay NULL, never default to normal."""
    assert classify.classify_wasting(None) is None
    assert classify.classify_thinness(None) is None
    assert classify.classify_stunting(None) is None
    assert classify.classify_underweight(None) is None


# --------------------------------------------------------------------------
# Rolling detail up to the coarse Poshan Tracker vocabulary
# --------------------------------------------------------------------------


def test_acute_malnutrition_outranks_chronic() -> None:
    """SAM is a referral today; stunting is a months-long trend."""
    detail = {
        "wasting": "severe_acute_malnutrition",
        "thinness": None,
        "stunting": "severely_stunted",
        "underweight": "severely_underweight",
    }
    assert classify.primary_classification(detail) == classify.SAM


def test_stunting_outranks_underweight() -> None:
    detail = {
        "wasting": "normal",
        "thinness": None,
        "stunting": "stunted",
        "underweight": "underweight",
    }
    assert classify.primary_classification(detail) == classify.STUNTED


def test_thinness_maps_into_the_mam_vocabulary() -> None:
    """School-age thinness has no cell of its own in Section 5's vocabulary."""
    detail = {
        "wasting": None,
        "thinness": "thinness",
        "stunting": "normal",
        "underweight": "normal",
    }
    assert classify.primary_classification(detail) == classify.MAM


def test_overweight_does_not_roll_up_as_malnutrition() -> None:
    """Section 5's vocabulary has no cell for overweight, and reporting an
    overweight child as malnourished would be worse than reporting nothing.
    The precise label survives in classification_detail regardless."""
    detail = {"wasting": "obese", "thinness": None, "stunting": "normal", "underweight": "normal"}
    assert classify.primary_classification(detail) == classify.NORMAL


def test_all_normal_is_normal() -> None:
    detail = {"wasting": "normal", "thinness": None, "stunting": "normal", "underweight": "normal"}
    assert classify.primary_classification(detail) == classify.NORMAL


def test_every_detail_label_maps_or_is_deliberately_ignored() -> None:
    """Guard against a new label being added to classify.py and silently
    disappearing from the roll-up."""
    produced = set()
    for fn, values in (
        (classify.classify_wasting, [-4, -2.5, 0, 2.5, 4]),
        (classify.classify_thinness, [-4, -2.5, 0, 1.5, 3]),
        (classify.classify_stunting, [-4, -2.5, 0]),
        (classify.classify_underweight, [-4, -2.5, 0]),
    ):
        produced.update(fn(v) for v in values)
    known = set(classify._TO_COARSE) | {"normal", "overweight", "obese", "obesity"}
    assert produced <= known, f"unmapped labels: {produced - known}"


def test_coarse_vocabulary_matches_the_schema_check_constraint() -> None:
    """Section 5 declares CHECK (classification IN (...)). Keep them in sync."""
    assert set(classify.SEVERITY_ORDER) == {
        classify.NORMAL,
        classify.MAM,
        classify.SAM,
        classify.STUNTED,
        classify.UNDERWEIGHT,
    }
