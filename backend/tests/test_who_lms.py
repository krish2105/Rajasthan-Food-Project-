"""Proof that our LMS implementation reproduces WHO's own published numbers.

Section 6.5 sets the target for WHO z-score classification at "100% match
against reference WHO Anthro output ... this must be exact, it's math, not ML".
This module is that proof, and it is the reason the vendored CSVs keep WHO's
published SD cut-off columns alongside L/M/S: we never read those columns at
runtime, we regenerate them from LMS and assert we land on WHO's values.

Coverage is every row of every vendored table -- 10,624 rows across 14 tables --
not a hand-picked sample.
"""

from __future__ import annotations

import math

import pytest

from app.growth.lms import (
    Indicator,
    OutOfRangeError,
    Sex,
    load_table,
    raw_zscore,
    value_at_z,
    zscore,
    zscore_from_lms,
)

ALL_TABLES = [
    "wfa_boys_0_60m",
    "wfa_girls_0_60m",
    "hfa_boys_0_60m",
    "hfa_girls_0_60m",
    "wfl_boys_45_110cm",
    "wfl_girls_45_110cm",
    "wfh_boys_65_120cm",
    "wfh_girls_65_120cm",
    "hfa_boys_61_228m",
    "hfa_girls_61_228m",
    "wfa_boys_61_120m",
    "wfa_girls_61_120m",
    "bfa_boys_61_228m",
    "bfa_girls_61_228m",
]

# WHO publishes these cut-offs rounded to 3 decimal places. Our reconstruction
# must agree to that same precision -- i.e. identical once both are rounded the
# way WHO printed them.
PUBLISHED_DP = 3


@pytest.mark.parametrize("stem", ALL_TABLES)
def test_lms_reproduces_who_published_sd_cutoffs(stem: str) -> None:
    """value_at_z(+/-2, +/-3) from L/M/S == WHO's published SD columns."""
    table = load_table(stem)
    assert table.rows, f"{stem} loaded no rows"
    for row in table.rows.values():
        for z, published in (
            (-3.0, row.sd3neg),
            (-2.0, row.sd2neg),
            (2.0, row.sd2pos),
            (3.0, row.sd3pos),
        ):
            computed = value_at_z(z, row.l, row.m, row.s)
            assert round(computed, PUBLISHED_DP) == pytest.approx(published, abs=1e-9), (
                f"{stem} key={row.key} z={z}: computed {computed!r} but WHO published {published!r}"
            )


@pytest.mark.parametrize("stem", ALL_TABLES)
def test_zscore_inverts_published_cutoffs(stem: str) -> None:
    """Feeding WHO's published SD value back in returns that z-score.

    Tolerance is 5e-3 rather than 0 because WHO's published values are
    themselves rounded to 3 dp -- that rounding, not our arithmetic, is the only
    source of error here.
    """
    table = load_table(stem)
    flat_tail = not stem.startswith("hfa_")
    for row in table.rows.values():
        for expected_z, published in (
            (-3.0, row.sd3neg),
            (-2.0, row.sd2neg),
            (2.0, row.sd2pos),
            (3.0, row.sd3pos),
        ):
            got = zscore_from_lms(published, row.l, row.m, row.s, flat_tail=flat_tail)
            assert got == pytest.approx(expected_z, abs=5e-3), (
                f"{stem} key={row.key}: {published} should be z={expected_z}, got {got}"
            )


@pytest.mark.parametrize("stem", ALL_TABLES)
def test_median_is_exactly_zero(stem: str) -> None:
    table = load_table(stem)
    for row in table.rows.values():
        assert zscore_from_lms(row.m, row.l, row.m, row.s, flat_tail=True) == pytest.approx(
            0.0, abs=1e-12
        )


# --------------------------------------------------------------------------
# The flat-tail correction -- the bug that silently breaks SAM detection
# --------------------------------------------------------------------------


def test_flat_tail_diverges_from_raw_beyond_3sd() -> None:
    """Below -3SD the corrected and raw z-scores must genuinely differ.

    If they agree, the correction is not being applied and every severe case
    would be mis-scored. This test exists to fail loudly if someone "simplifies"
    zscore_from_lms.
    """
    row = load_table("wfa_boys_0_60m").rows[365.0]
    severe = value_at_z(-3.0, row.l, row.m, row.s) * 0.80
    corrected = zscore_from_lms(severe, row.l, row.m, row.s, flat_tail=True)
    raw = raw_zscore(severe, row.l, row.m, row.s)
    assert corrected < -3.0
    assert raw < -3.0
    assert abs(corrected - raw) > 0.05


def test_flat_tail_is_linear_below_minus_three() -> None:
    """Each further (SD2neg - SD3neg) below SD3neg is exactly one more z unit."""
    row = load_table("wfa_boys_0_60m").rows[365.0]
    sd3neg = value_at_z(-3.0, row.l, row.m, row.s)
    sd2neg = value_at_z(-2.0, row.l, row.m, row.s)
    gap = sd2neg - sd3neg
    for k in (1, 2, 3):
        z = zscore_from_lms(sd3neg - k * gap, row.l, row.m, row.s, flat_tail=True)
        assert z == pytest.approx(-3.0 - k, abs=1e-9)


def test_flat_tail_is_linear_above_plus_three() -> None:
    row = load_table("wfa_boys_0_60m").rows[365.0]
    sd3pos = value_at_z(3.0, row.l, row.m, row.s)
    sd2pos = value_at_z(2.0, row.l, row.m, row.s)
    gap = sd3pos - sd2pos
    for k in (1, 2):
        z = zscore_from_lms(sd3pos + k * gap, row.l, row.m, row.s, flat_tail=True)
        assert z == pytest.approx(3.0 + k, abs=1e-9)


def test_flat_tail_is_continuous_at_the_boundary() -> None:
    """No jump discontinuity where the correction switches on."""
    row = load_table("wfa_boys_0_60m").rows[365.0]
    sd3neg = value_at_z(-3.0, row.l, row.m, row.s)
    inside = zscore_from_lms(sd3neg * 1.0000001, row.l, row.m, row.s, flat_tail=True)
    outside = zscore_from_lms(sd3neg * 0.9999999, row.l, row.m, row.s, flat_tail=True)
    assert abs(inside - outside) < 1e-4


def test_height_for_age_never_gets_flat_tail() -> None:
    """WHO applies the correction to weight-based indices only."""
    row = load_table("hfa_boys_0_60m").rows[365.0]
    stunted = value_at_z(-3.0, row.l, row.m, row.s) * 0.9
    assert zscore_from_lms(stunted, row.l, row.m, row.s, flat_tail=False) == pytest.approx(
        raw_zscore(stunted, row.l, row.m, row.s), abs=1e-12
    )


# --------------------------------------------------------------------------
# The L == 0 limiting case
# --------------------------------------------------------------------------


def test_l_zero_uses_lognormal_branch() -> None:
    assert raw_zscore(11.0, 0.0, 10.0, 0.1) == pytest.approx(math.log(11.0 / 10.0) / 0.1, abs=1e-12)
    assert value_at_z(1.5, 0.0, 10.0, 0.1) == pytest.approx(10.0 * math.exp(0.15), abs=1e-12)


def test_l_zero_is_the_limit_of_small_l() -> None:
    """The L==0 branch must be the continuous limit, not a special case."""
    limit = raw_zscore(11.0, 0.0, 10.0, 0.1)
    near = raw_zscore(11.0, 1e-9, 10.0, 0.1)
    assert near == pytest.approx(limit, abs=1e-5)


def test_who_2007_height_tables_actually_use_l_equals_one() -> None:
    """Sanity check on the vendored data: HFA 5-19 is published with L == 1."""
    row = load_table("hfa_boys_61_228m").rows[61.0]
    assert row.l == 1


# --------------------------------------------------------------------------
# Table boundaries -- we raise rather than extrapolate
# --------------------------------------------------------------------------


def test_2006_tables_cover_day_zero_to_1856() -> None:
    t = load_table("wfa_boys_0_60m")
    assert (t.key_min, t.key_max) == (0.0, 1856.0)


def test_weight_for_age_2007_stops_at_120_months() -> None:
    t = load_table("wfa_boys_61_120m")
    assert (t.key_min, t.key_max) == (61.0, 120.0)
    with pytest.raises(OutOfRangeError):
        # A 12-year-old: WHO defines no weight-for-age reference here.
        zscore(Indicator.WEIGHT_FOR_AGE, Sex.MALE, 38.0, age_days=144 * 30.4375)


def test_bmi_for_age_rejects_under_five() -> None:
    with pytest.raises(OutOfRangeError):
        zscore(Indicator.BMI_FOR_AGE, Sex.MALE, 16.0, age_days=800)


def test_weight_for_length_rejects_out_of_range_length() -> None:
    with pytest.raises(OutOfRangeError):
        zscore(Indicator.WEIGHT_FOR_LENGTH, Sex.FEMALE, 12.0, length_cm=130.0)


def test_zero_or_negative_measurement_rejected() -> None:
    with pytest.raises(OutOfRangeError):
        raw_zscore(0.0, 0.3, 3.3, 0.14)


# --------------------------------------------------------------------------
# Monotonicity -- a heavier child at the same age must never score lower
# --------------------------------------------------------------------------


@pytest.mark.parametrize("sex", [Sex.MALE, Sex.FEMALE])
def test_zscore_is_monotonic_in_weight(sex: Sex) -> None:
    previous = -math.inf
    for grams in range(6000, 20000, 100):
        z = zscore(Indicator.WEIGHT_FOR_AGE, sex, grams / 1000.0, age_days=730)
        assert z > previous
        previous = z


@pytest.mark.parametrize("sex", [Sex.MALE, Sex.FEMALE])
def test_zscore_is_monotonic_across_the_flat_tail_seam(sex: Sex) -> None:
    """Monotonicity must survive the piecewise switch at +/-3SD."""
    previous = -math.inf
    for grams in range(3000, 30000, 50):
        z = zscore(Indicator.WEIGHT_FOR_AGE, sex, grams / 1000.0, age_days=365)
        assert z > previous, f"non-monotonic at {grams}g"
        previous = z
