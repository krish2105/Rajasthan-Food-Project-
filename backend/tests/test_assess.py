"""Age-aware routing between the two WHO references (deviation D1).

The bug this file guards against: applying the 0-60 month Child Growth
Standards to a school-age child, producing a clinically invalid number that
looks authoritative. Section 1 puts both Anganwadi (0-6y) and Ashram school
(6-14y) children in the same pilot, so both references are exercised in
production every day.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.growth.assess import (
    MAX_MONTHS_WFA_2007,
    STANDARD_2006,
    STANDARD_2007,
    assess,
)
from app.growth.lms import LENGTH_TO_HEIGHT_DAYS, MAX_DAYS_2006, Sex

REF = date(2026, 8, 28)


def at_age_days(days: int) -> date:
    return date.fromordinal(REF.toordinal() - days)


def test_under_five_uses_who_2006_and_reports_whz_not_baz() -> None:
    a = assess(dob=at_age_days(1095), recorded_at=REF, sex=Sex.MALE, height_cm=90.0, weight_kg=12.5)
    assert a.standard_used == STANDARD_2006
    assert a.whz is not None
    assert a.baz is None, "BMI-for-age must not be computed below 5 years"
    assert a.waz is not None and a.haz is not None


def test_school_age_uses_who_2007_and_reports_baz_not_whz() -> None:
    a = assess(
        dob=at_age_days(3287), recorded_at=REF, sex=Sex.FEMALE, height_cm=126.0, weight_kg=23.0
    )
    assert a.standard_used == STANDARD_2007
    assert a.whz is None, "weight-for-height does not exist in the WHO 2007 reference"
    assert a.baz is not None
    assert any("weight-for-height is undefined" in n for n in a.notes)


def test_the_switch_happens_exactly_at_the_end_of_the_2006_tables() -> None:
    kw = dict(recorded_at=REF, sex=Sex.MALE, height_cm=110.0, weight_kg=18.0)
    last_2006 = assess(dob=at_age_days(MAX_DAYS_2006), **kw)
    first_2007 = assess(dob=at_age_days(MAX_DAYS_2006 + 1), **kw)
    assert last_2006.standard_used == STANDARD_2006
    assert first_2007.standard_used == STANDARD_2007


def test_no_discontinuity_in_height_for_age_across_the_seam() -> None:
    """The two references are stitched to agree at the join; a large jump would
    mean we picked the wrong table or the wrong age unit."""
    kw = dict(recorded_at=REF, sex=Sex.MALE, height_cm=110.0, weight_kg=18.0)
    before = assess(dob=at_age_days(MAX_DAYS_2006), **kw)
    after = assess(dob=at_age_days(MAX_DAYS_2006 + 1), **kw)
    assert before.haz is not None and after.haz is not None
    assert abs(before.haz - after.haz) < 0.2


def test_weight_for_age_drops_out_above_ten_years_with_an_explanation() -> None:
    a = assess(
        dob=at_age_days(int((MAX_MONTHS_WFA_2007 + 12) * 30.4375)),
        recorded_at=REF,
        sex=Sex.MALE,
        height_cm=145.0,
        weight_kg=34.0,
    )
    assert a.waz is None
    assert a.haz is not None and a.baz is not None
    assert any("no weight-for-age reference beyond 120 months" in n for n in a.notes)


def test_recumbent_length_below_24_months_standing_height_above() -> None:
    """Different WHO tables with different LMS parameters, not a relabelling."""
    kw = dict(recorded_at=REF, sex=Sex.FEMALE, height_cm=85.0, weight_kg=10.5)
    younger = assess(dob=at_age_days(LENGTH_TO_HEIGHT_DAYS - 1), **kw)
    older = assess(dob=at_age_days(LENGTH_TO_HEIGHT_DAYS), **kw)
    assert younger.whz is not None and older.whz is not None
    assert younger.whz != older.whz


def test_bmi_is_reported_only_for_the_2007_band() -> None:
    under = assess(
        dob=at_age_days(1000), recorded_at=REF, sex=Sex.MALE, height_cm=80.0, weight_kg=11.0
    )
    over = assess(
        dob=at_age_days(3000), recorded_at=REF, sex=Sex.MALE, height_cm=120.0, weight_kg=22.0
    )
    assert under.bmi is None
    assert over.bmi == pytest.approx(22.0 / 1.2**2, abs=0.01)


def test_a_severely_wasted_toddler_is_classified_sam() -> None:
    a = assess(dob=at_age_days(900), recorded_at=REF, sex=Sex.MALE, height_cm=82.0, weight_kg=7.6)
    assert a.whz is not None and a.whz < -3.0
    assert a.classification == "SAM"
    assert a.classification_detail["wasting"] == "severe_acute_malnutrition"


def test_classification_detail_records_multiple_simultaneous_conditions() -> None:
    """The reason deviation D2 exists: one column cannot say 'stunted AND
    underweight', and both matter to a supervisor planning follow-up."""
    a = assess(
        dob=at_age_days(1460), recorded_at=REF, sex=Sex.FEMALE, height_cm=88.0, weight_kg=11.0
    )
    assert a.classification_detail["stunting"] in {"stunted", "severely_stunted"}
    assert a.classification_detail["underweight"] in {"underweight", "severely_underweight"}
    assert a.classification in {"SAM", "MAM", "stunted", "underweight"}


def test_age_in_months_is_derived_with_whos_own_constant() -> None:
    a = assess(dob=at_age_days(365), recorded_at=REF, sex=Sex.MALE, height_cm=75.0, weight_kg=9.5)
    assert a.age_days == 365
    assert a.age_months == 12


def test_measurement_in_the_future_is_rejected() -> None:
    with pytest.raises(ValueError):
        assess(
            dob=date(2026, 9, 1),
            recorded_at=REF,
            sex=Sex.MALE,
            height_cm=80.0,
            weight_kg=10.0,
        )


@pytest.mark.parametrize(("h", "w"), [(0.0, 10.0), (80.0, 0.0), (-5.0, 10.0)])
def test_nonpositive_measurements_are_rejected(h: float, w: float) -> None:
    with pytest.raises(ValueError):
        assess(dob=at_age_days(900), recorded_at=REF, sex=Sex.MALE, height_cm=h, weight_kg=w)


def test_assessment_is_deterministic() -> None:
    """Same input, same output -- the property that makes the stored z-scores
    reproducible and the whole path auditable (Section 6.4)."""
    kw = dict(dob=at_age_days(1200), recorded_at=REF, sex=Sex.MALE, height_cm=91.5, weight_kg=12.9)
    assert assess(**kw).as_dict() == assess(**kw).as_dict()


# --------------------------------------------------------------------------
# WHO implausible-value flagging
# --------------------------------------------------------------------------


def test_a_data_entry_typo_is_flagged_not_trusted() -> None:
    """88 cm for a six-month-old is a typo, not a very tall baby.

    Section 7 names data-entry burden as this system's most likely real-world
    failure point. Without flagging, a transposed digit becomes a permanent,
    authoritative-looking growth record.
    """
    a = assess(
        dob=at_age_days(180),
        recorded_at=REF,
        sex=Sex.FEMALE,
        height_cm=88.0,
        weight_kg=10.4,
    )
    assert "haz" in a.data_quality_flags
    assert a.haz is not None, "the raw z-score is retained for audit"
    assert a.haz > 6.0
    assert any("outside WHO's plausible range" in n for n in a.notes)


def test_a_flagged_index_cannot_drive_the_classification() -> None:
    """The point of flagging: a typo must not manufacture or mask a case."""
    a = assess(
        dob=at_age_days(180),
        recorded_at=REF,
        sex=Sex.FEMALE,
        height_cm=88.0,
        weight_kg=10.4,
    )
    assert a.classification_detail["stunting"] is None
    assert a.classification != "stunted"


def test_a_plausible_measurement_carries_no_flags() -> None:
    a = assess(
        dob=at_age_days(1100),
        recorded_at=REF,
        sex=Sex.FEMALE,
        height_cm=88.0,
        weight_kg=10.4,
    )
    assert a.data_quality_flags == []
    assert a.classification_detail["stunting"] is not None


def test_a_genuinely_severe_case_is_not_flagged_away() -> None:
    """The failure mode to avoid in the other direction: a real SAM child sits
    well below -3 SD, and must still be classified, not dismissed as a typo."""
    a = assess(
        dob=at_age_days(900),
        recorded_at=REF,
        sex=Sex.MALE,
        height_cm=82.0,
        weight_kg=7.6,
    )
    assert a.data_quality_flags == []
    assert a.classification == "SAM"


@pytest.mark.parametrize("index", ["waz", "haz", "whz", "baz"])
def test_every_index_has_plausibility_bounds(index: str) -> None:
    """Guards against a new index being added without a bound, which would
    silently exempt it from flagging."""
    from app.growth.assess import IMPLAUSIBLE_BOUNDS

    lo, hi = IMPLAUSIBLE_BOUNDS[index]
    assert lo < -3.0 < 3.0 < hi, "bounds must sit outside the SAM/MAM cut-offs"


def test_bounds_never_clip_a_real_classification_boundary() -> None:
    """A child at exactly -3 SD is SAM, not a data error. The bounds must sit
    far enough out that no genuine cut-off is ever swallowed."""
    from app.growth.assess import IMPLAUSIBLE_BOUNDS

    for lo, hi in IMPLAUSIBLE_BOUNDS.values():
        assert lo <= -5.0 and hi >= 5.0
