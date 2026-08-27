"""Threshold lookup from WHO z-scores to nutritional status labels.

Pure functions over numbers. No model, no I/O, no database -- same reasoning as
`lms.py` (Section 6.4).

Two vocabularies, deliberately
------------------------------
`GrowthAssessment.classification` uses the five-value vocabulary the Section 5
schema declares and Poshan Tracker already displays -- normal / MAM / SAM /
stunted / underweight -- so a district officer reads a category they already
know.

`GrowthAssessment.classification_detail` carries the precise WHO label for each
index separately (deviation D2), because a child can be stunted *and*
underweight at once and a single column cannot say so. It also preserves the
distinction the coarse vocabulary loses: below 5 years acute malnutrition is
"severe/moderate acute malnutrition" measured by weight-for-height, while from 5
years it is "severe thinness / thinness" measured by BMI-for-age. Those are
different WHO terms for different measurements, and the detail field keeps them
honest even though both roll up to SAM/MAM for display.
"""

from __future__ import annotations

# Coarse vocabulary, matching Section 5's CHECK constraint and Poshan Tracker.
NORMAL = "normal"
MAM = "MAM"
SAM = "SAM"
STUNTED = "stunted"
UNDERWEIGHT = "underweight"

#: Most-urgent-first. Acute malnutrition outranks chronic: SAM is a referral
#: today, stunting is a months-long trend.
SEVERITY_ORDER = (SAM, MAM, STUNTED, UNDERWEIGHT, NORMAL)


def classify_wasting(whz: float | None) -> str | None:
    """Weight-for-height/length, under 5 years. WHO acute malnutrition cut-offs."""
    if whz is None:
        return None
    if whz < -3.0:
        return "severe_acute_malnutrition"
    if whz < -2.0:
        return "moderate_acute_malnutrition"
    if whz > 3.0:
        return "obese"
    if whz > 2.0:
        return "overweight"
    return "normal"


def classify_thinness(baz: float | None) -> str | None:
    """BMI-for-age, 5-19 years. Note the asymmetric positive cut-offs: WHO 2007
    puts overweight at >+1SD for this age band, not >+2SD as under 5."""
    if baz is None:
        return None
    if baz < -3.0:
        return "severe_thinness"
    if baz < -2.0:
        return "thinness"
    if baz > 2.0:
        return "obesity"
    if baz > 1.0:
        return "overweight"
    return "normal"


def classify_stunting(haz: float | None) -> str | None:
    if haz is None:
        return None
    if haz < -3.0:
        return "severely_stunted"
    if haz < -2.0:
        return "stunted"
    return "normal"


def classify_underweight(waz: float | None) -> str | None:
    if waz is None:
        return None
    if waz < -3.0:
        return "severely_underweight"
    if waz < -2.0:
        return "underweight"
    return "normal"


#: Detailed WHO label -> coarse Poshan Tracker category.
_TO_COARSE: dict[str, str] = {
    "severe_acute_malnutrition": SAM,
    "severe_thinness": SAM,
    "moderate_acute_malnutrition": MAM,
    "thinness": MAM,
    "severely_stunted": STUNTED,
    "stunted": STUNTED,
    "severely_underweight": UNDERWEIGHT,
    "underweight": UNDERWEIGHT,
}


def primary_classification(detail: dict[str, str | None]) -> str:
    """Roll the per-index detail up to the single most severe coarse category.

    Overweight/obesity intentionally roll up to `normal`: Section 5's vocabulary
    has no cell for them, and silently reporting an overweight child as
    malnourished would be worse than reporting the detail field alone. The
    precise label is preserved in `classification_detail` either way.
    """
    found = {_TO_COARSE[v] for v in detail.values() if v in _TO_COARSE}
    for category in SEVERITY_ORDER:
        if category in found:
            return category
    return NORMAL
