"""Age-aware router from a raw measurement to a full WHO growth assessment.

This is deviation D1 from the master prompt made concrete. Section 5's schema
assumed weight-for-height for every child, but WHO publishes two disjoint
references:

  * **WHO Child Growth Standards (2006)**, 0-60 months -- weight-for-age,
    length/height-for-age, and weight-for-length (<24m) / weight-for-height
    (24-60m).
  * **WHO Growth Reference (2007)**, 5-19 years -- height-for-age (5-19y),
    weight-for-age (5-**10**y only), and BMI-for-age (5-19y). Weight-for-height
    does not exist in this reference at all; BMI-for-age replaces it.

The Banswara pilot covers both Anganwadi centres (0-6y) and Ashram schools
(6-14y), so both references are needed. Applying the 0-60m tables to a 9-year-
old would produce a clinically invalid number that looks authoritative -- the
exact failure mode Section 6.4 exists to prevent. Indices WHO does not define
for a given age come back as `None`, and `standard_used` records which reference
was applied so the decision is auditable from the database row alone.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

from app.growth import classify
from app.growth.lms import (
    DAYS_PER_MONTH,
    LENGTH_TO_HEIGHT_DAYS,
    MAX_DAYS_2006,
    Indicator,
    OutOfRangeError,
    Sex,
    zscore,
)

STANDARD_2006 = "who_2006_0_60m"
STANDARD_2007 = "who_2007_5_19y"

#: WHO publishes no weight-for-age reference beyond 10 years.
MAX_MONTHS_WFA_2007 = 120

#: WHO Anthro's biologically-implausible-value bounds. A z-score outside these
#: is almost always a data-entry error -- a transposed digit, centimetres typed
#: as metres, a weight recorded against the wrong child -- rather than a real
#: measurement. Section 7 names data-entry burden on frontline workers as this
#: system's most likely real-world failure point, so silently accepting a
#: +9 SD height would mean inventing malnutrition cases (or hiding them) from
#: typos.
#:
#: We follow WHO's own handling: keep the raw measurement and the computed
#: z-score for audit, flag it, and exclude the flagged index from the
#: classification so a typo cannot manufacture a SAM case. We do not reject the
#: measurement -- a genuinely extreme child exists, and refusing to record them
#: would be the worse failure.
IMPLAUSIBLE_BOUNDS: dict[str, tuple[float, float]] = {
    "waz": (-6.0, 5.0),
    "haz": (-6.0, 6.0),
    "whz": (-5.0, 5.0),
    "baz": (-5.0, 5.0),
}
#: WHO 2007 height-for-age and BMI-for-age stop at 19 years.
MAX_MONTHS_2007 = 228


@dataclass(frozen=True, slots=True)
class GrowthAssessment:
    age_days: int
    age_months: int
    standard_used: str
    waz: float | None = None
    haz: float | None = None
    whz: float | None = None
    baz: float | None = None
    bmi: float | None = None
    classification: str = classify.NORMAL
    classification_detail: dict[str, str | None] = field(default_factory=dict)
    #: Indices whose z-score falls outside WHO's plausible range. Present in the
    #: stored row so a flagged measurement stays identifiable after the fact.
    data_quality_flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def age_in_days(dob: date, on: date) -> int:
    return (on - dob).days


def _round2(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def assess(
    *,
    dob: date,
    recorded_at: date,
    sex: Sex,
    height_cm: float,
    weight_kg: float,
) -> GrowthAssessment:
    """Classify one measurement against the correct WHO reference for its age."""
    days = age_in_days(dob, recorded_at)
    if days < 0:
        raise ValueError("recorded_at is before date of birth")
    months = round(days / DAYS_PER_MONTH)
    if height_cm <= 0 or weight_kg <= 0:
        raise ValueError("height_cm and weight_kg must be positive")

    notes: list[str] = []
    waz = haz = whz = baz = bmi = None

    def attempt(label: str, fn):
        """Run one index, downgrading an out-of-range reference to a note.

        A 12-year-old legitimately has no weight-for-age reference. That is a
        fact about WHO's tables, not an error in the input, so it becomes a
        NULL column plus an explanatory note rather than a failed request.
        """
        try:
            return fn()
        except OutOfRangeError as exc:
            notes.append(f"{label}: {exc}")
            return None

    if days <= MAX_DAYS_2006:
        standard = STANDARD_2006
        waz = attempt(
            "waz",
            lambda: zscore(Indicator.WEIGHT_FOR_AGE, sex, weight_kg, age_days=days),
        )
        haz = attempt(
            "haz",
            lambda: zscore(Indicator.HEIGHT_FOR_AGE, sex, height_cm, age_days=days),
        )
        # WHO measures recumbent length below 24 months and standing height at
        # or above it; the two tables have different key ranges and different
        # LMS parameters, so the switch is not cosmetic.
        indicator = (
            Indicator.WEIGHT_FOR_LENGTH
            if days < LENGTH_TO_HEIGHT_DAYS
            else Indicator.WEIGHT_FOR_HEIGHT
        )
        whz = attempt(
            "whz",
            lambda: zscore(indicator, sex, weight_kg, length_cm=height_cm),
        )
    else:
        standard = STANDARD_2007
        bmi = weight_kg / (height_cm / 100.0) ** 2
        if months <= MAX_MONTHS_WFA_2007:
            waz = attempt(
                "waz",
                lambda: zscore(Indicator.WEIGHT_FOR_AGE, sex, weight_kg, age_days=days),
            )
        else:
            notes.append(
                "waz: WHO publishes no weight-for-age reference beyond 120 months; "
                "BMI-for-age is the correct index at this age"
            )
        haz = attempt(
            "haz",
            lambda: zscore(Indicator.HEIGHT_FOR_AGE, sex, height_cm, age_days=days),
        )
        baz = attempt("baz", lambda: zscore(Indicator.BMI_FOR_AGE, sex, bmi, age_days=days))
        notes.append(
            "whz: weight-for-height is undefined above 60 months in the WHO 2007 "
            "reference; BMI-for-age (baz) replaces it"
        )

    # Flag before classifying, so an implausible index cannot drive the label.
    scores = {"waz": waz, "haz": haz, "whz": whz, "baz": baz}
    flags: list[str] = []
    usable: dict[str, float | None] = {}
    for key, value in scores.items():
        lo, hi = IMPLAUSIBLE_BOUNDS[key]
        if value is not None and not (lo <= value <= hi):
            flags.append(key)
            notes.append(
                f"{key}: z-score {value:+.2f} is outside WHO's plausible range "
                f"[{lo:+.0f}, {hi:+.0f}] and is almost certainly a measurement or "
                f"data-entry error. Recorded and retained, but excluded from the "
                f"classification -- please re-measure."
            )
            usable[key] = None
        else:
            usable[key] = value

    detail: dict[str, str | None] = {
        "wasting": classify.classify_wasting(usable["whz"]),
        "thinness": classify.classify_thinness(usable["baz"]),
        "stunting": classify.classify_stunting(usable["haz"]),
        "underweight": classify.classify_underweight(usable["waz"]),
    }

    return GrowthAssessment(
        age_days=days,
        age_months=months,
        standard_used=standard,
        waz=_round2(waz),
        haz=_round2(haz),
        whz=_round2(whz),
        baz=_round2(baz),
        bmi=_round2(bmi),
        classification=classify.primary_classification(detail),
        classification_detail=detail,
        data_quality_flags=flags,
        notes=notes,
    )
