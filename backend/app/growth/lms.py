"""WHO growth reference z-scores via the LMS method.

Section 6.4 of the master prompt is unambiguous: a child's malnutrition
classification is a clinical/statistical fact, and no language model may sit in
this code path. Everything below is a pure function over vendored WHO reference
tables (`app/growth/who/*.csv`, see `scripts/fetch_who_tables.py`).

The LMS method
--------------
WHO publishes, for each indicator/sex/age (or length), a Box-Cox power (L), a
median (M) and a coefficient of variation (S). A measurement `x` converts to a
z-score as::

    z = ((x / M)^L - 1) / (L * S)        for L != 0
    z = ln(x / M) / S                    for L == 0   (limiting case)

The +/-3SD flat-tail correction
-------------------------------
For the *weight-based* indicators (weight-for-age, weight-for-length/height and
BMI-for-age) the raw LMS distribution has tails that are too skewed to be
trustworthy beyond +/-3SD, so WHO defines a linear extrapolation outside that
range::

    z > 3   ->  z = 3 + (x - SD3pos) / (SD3pos - SD2pos)
    z < -3  ->  z = -3 + (x - SD3neg) / (SD2neg - SD3neg)

This correction is deliberately NOT applied to height-for-age, which is close
enough to normal in its tails that WHO uses the raw LMS value throughout.

Getting this wrong is the single most common bug in home-grown implementations,
and it is wrong *precisely* in the severe-malnutrition range that matters most
for this system -- an uncorrected implementation disagrees with WHO Anthro on
exactly the SAM cases the pilot exists to find. `tests/test_who_lms.py` proves
our output reproduces WHO's own published SD cut-offs for all 10,624 vendored
rows.
"""

from __future__ import annotations

# ruff: noqa: E741
# `l` is flagged as an ambiguous name, and normally it would be. Here it is the
# name WHO itself publishes for the Box-Cox power parameter, and every formula
# below can be read straight against the WHO documentation because of it.
# Renaming it to `lam` would make this file harder to verify, not easier.
import csv
import math
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from pathlib import Path

WHO_DIR = Path(__file__).resolve().parent / "who"

#: Days per month used throughout, matching WHO Anthro / AnthroPlus.
DAYS_PER_MONTH = 30.4375

#: Highest age (days) covered by the WHO 2006 Child Growth Standards tables.
MAX_DAYS_2006 = 1856

#: Age (days) at which WHO switches from recumbent length to standing height.
LENGTH_TO_HEIGHT_DAYS = 731  # 24 months


class Sex(StrEnum):
    MALE = "M"
    FEMALE = "F"


class Indicator(StrEnum):
    """Growth indicators this module can compute."""

    WEIGHT_FOR_AGE = "wfa"
    HEIGHT_FOR_AGE = "hfa"
    WEIGHT_FOR_LENGTH = "wfl"
    WEIGHT_FOR_HEIGHT = "wfh"
    BMI_FOR_AGE = "bfa"


#: Indicators that receive WHO's +/-3SD flat-tail correction.
_FLAT_TAIL = frozenset(
    {
        Indicator.WEIGHT_FOR_AGE,
        Indicator.WEIGHT_FOR_LENGTH,
        Indicator.WEIGHT_FOR_HEIGHT,
        Indicator.BMI_FOR_AGE,
    }
)


class OutOfRangeError(ValueError):
    """The measurement falls outside the range WHO defines a reference for.

    Raised rather than silently clamped: a 14-year-old has no weight-for-age
    reference, and inventing one would be exactly the kind of authoritative-
    looking wrong number Section 6.4 forbids.
    """


@dataclass(frozen=True, slots=True)
class LMSRow:
    key: float
    l: float
    m: float
    s: float
    sd3neg: float
    sd2neg: float
    sd2pos: float
    sd3pos: float


@dataclass(frozen=True, slots=True)
class Table:
    stem: str
    rows: dict[float, LMSRow]
    key_min: float
    key_max: float
    step: float


@cache
def load_table(stem: str) -> Table:
    """Load and cache one vendored WHO table. `#` lines are provenance headers."""
    path = WHO_DIR / f"{stem}.csv"
    if not path.exists():  # pragma: no cover - configuration error
        raise FileNotFoundError(
            f"Missing WHO table {path}. Run: python scripts/fetch_who_tables.py"
        )
    rows: dict[float, LMSRow] = {}
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(line for line in fh if not line.startswith("#"))
        for rec in reader:
            key = round(float(rec["key"]), 1)
            rows[key] = LMSRow(
                key=key,
                l=float(rec["l"]),
                m=float(rec["m"]),
                s=float(rec["s"]),
                sd3neg=float(rec["sd3neg"]),
                sd2neg=float(rec["sd2neg"]),
                sd2pos=float(rec["sd2pos"]),
                sd3pos=float(rec["sd3pos"]),
            )
    keys = sorted(rows)
    step = round(keys[1] - keys[0], 4) if len(keys) > 1 else 1.0
    return Table(stem=stem, rows=rows, key_min=keys[0], key_max=keys[-1], step=step)


def value_at_z(z: float, l: float, m: float, s: float) -> float:
    """Inverse LMS: the measurement corresponding to z-score `z`."""
    if l == 0:
        return m * math.exp(s * z)
    return m * (1.0 + l * s * z) ** (1.0 / l)


def raw_zscore(x: float, l: float, m: float, s: float) -> float:
    """Uncorrected LMS z-score."""
    if x <= 0:
        raise OutOfRangeError("measurement must be positive")
    if l == 0:
        return math.log(x / m) / s
    return ((x / m) ** l - 1.0) / (l * s)


def zscore_from_lms(x: float, l: float, m: float, s: float, *, flat_tail: bool) -> float:
    """LMS z-score, with WHO's +/-3SD flat-tail correction when `flat_tail`."""
    z = raw_zscore(x, l, m, s)
    if not flat_tail or -3.0 <= z <= 3.0:
        return z
    if z > 3.0:
        sd2pos = value_at_z(2.0, l, m, s)
        sd3pos = value_at_z(3.0, l, m, s)
        return 3.0 + (x - sd3pos) / (sd3pos - sd2pos)
    sd2neg = value_at_z(-2.0, l, m, s)
    sd3neg = value_at_z(-3.0, l, m, s)
    return -3.0 + (x - sd3neg) / (sd2neg - sd3neg)


def _table_stem(indicator: Indicator, sex: Sex, *, age_days: float | None) -> str:
    male = sex is Sex.MALE
    sx = "boys" if male else "girls"
    if indicator is Indicator.WEIGHT_FOR_LENGTH:
        return f"wfl_{sx}_45_110cm"
    if indicator is Indicator.WEIGHT_FOR_HEIGHT:
        return f"wfh_{sx}_65_120cm"
    if age_days is None:  # pragma: no cover - guarded by callers
        raise ValueError(f"{indicator} requires age_days")
    under_five = age_days <= MAX_DAYS_2006
    if indicator is Indicator.WEIGHT_FOR_AGE:
        return f"wfa_{sx}_0_60m" if under_five else f"wfa_{sx}_61_120m"
    if indicator is Indicator.HEIGHT_FOR_AGE:
        return f"hfa_{sx}_0_60m" if under_five else f"hfa_{sx}_61_228m"
    if indicator is Indicator.BMI_FOR_AGE:
        if under_five:
            raise OutOfRangeError(
                "BMI-for-age is not used below 61 months; use weight-for-length/height"
            )
        return f"bfa_{sx}_61_228m"
    raise ValueError(indicator)  # pragma: no cover


def _lookup(table: Table, key: float) -> LMSRow:
    """Exact-key lookup, snapping to the table's own granularity.

    WHO's tables are dense (per day, or per 0.1 cm), so WHO Anthro snaps to the
    nearest tabulated key rather than interpolating LMS parameters. We do the
    same. Keys outside the published range raise rather than clamp.
    """
    if key < table.key_min or key > table.key_max:
        raise OutOfRangeError(
            f"{key} is outside the WHO reference range "
            f"{table.key_min}-{table.key_max} for table {table.stem}"
        )
    snapped = round(round(key / table.step) * table.step, 1)
    row = table.rows.get(snapped)
    if row is None:  # pragma: no cover - dense tables make this unreachable
        raise OutOfRangeError(f"no WHO row for key {snapped} in {table.stem}")
    return row


def zscore(
    indicator: Indicator,
    sex: Sex,
    value: float,
    *,
    age_days: float | None = None,
    length_cm: float | None = None,
) -> float:
    """Compute a WHO z-score.

    `age_days` keys the age-based indicators; `length_cm` keys weight-for-
    length/height. Raises `OutOfRangeError` when WHO publishes no reference for
    the given age or length -- we never extrapolate past the tables.
    """
    stem = _table_stem(indicator, sex, age_days=age_days)
    table = load_table(stem)
    if indicator in (Indicator.WEIGHT_FOR_LENGTH, Indicator.WEIGHT_FOR_HEIGHT):
        if length_cm is None:
            raise ValueError(f"{indicator} requires length_cm")
        key = round(length_cm, 1)
    else:
        assert age_days is not None
        key = (
            float(int(age_days))
            if age_days <= MAX_DAYS_2006
            else float(round(age_days / DAYS_PER_MONTH))
        )
    row = _lookup(table, key)
    return zscore_from_lms(value, row.l, row.m, row.s, flat_tail=indicator in _FLAT_TAIL)


def lms_row(
    indicator: Indicator,
    sex: Sex,
    *,
    age_days: float | None = None,
    length_cm: float | None = None,
) -> LMSRow:
    """The WHO L/M/S parameters for one indicator/sex/key.

    Exposed so the seed generator can work *backwards* -- picking a target
    z-score and inverting it to a plausible height and weight. Generating
    measurements from the same tables that later score them is what makes the
    seeded z-scores reproducible by `assess()` rather than decorative numbers
    typed into a fixture.
    """
    stem = _table_stem(indicator, sex, age_days=age_days)
    table = load_table(stem)
    if indicator in (Indicator.WEIGHT_FOR_LENGTH, Indicator.WEIGHT_FOR_HEIGHT):
        if length_cm is None:
            raise ValueError(f"{indicator} requires length_cm")
        key = round(length_cm, 1)
    else:
        assert age_days is not None
        key = (
            float(int(age_days))
            if age_days <= MAX_DAYS_2006
            else float(round(age_days / DAYS_PER_MONTH))
        )
    return _lookup(table, key)
