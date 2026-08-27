"""Deterministic generation of plausible pilot data.

The important idea here is that growth measurements are produced by *inverting*
the WHO tables, not by making numbers up. Each child is assigned a target
height-for-age z-score and a target wasting z-score, and the height and weight
are then derived from the same L/M/S parameters that `assess()` will later use
to score them.

Two things follow from that, and both matter for a pitch:

  * every z-score stored in the database is reproducible -- run `assess()` on
    the stored height and weight and you get the stored z-score back, so a
    reviewer can audit any row rather than taking it on trust;
  * the prevalence of stunting, wasting and underweight in the seed is a
    consequence of the targets, not a hand-written fiction, so it is honest to
    describe how it was produced.

Targets are tuned toward NFHS-5 figures for the Rajasthan tribal belt. The
achieved prevalence is printed at the end of every seed run rather than
asserted, because the achieved number is the one that would go in a deck.

Weight-for-age is deliberately *not* a free parameter. It is a consequence of
height and weight, so underweight prevalence falls out of the other two -- which
is how it works in a real population.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.growth.assess import GrowthAssessment, assess
from app.growth.lms import (
    DAYS_PER_MONTH,
    LENGTH_TO_HEIGHT_DAYS,
    MAX_DAYS_2006,
    Indicator,
    Sex,
    lms_row,
    value_at_z,
)
from app.seed import reference

# Distribution targets. sd is wider than 1.0 because a real population is more
# dispersed than the WHO reference population it is scored against.
HAZ_MEAN, HAZ_SD = -1.58, 1.10  # -> ~35% stunted
WHZ_MEAN, WHZ_SD = -1.00, 1.15  # -> ~18% wasted, ~4% severe
BAZ_MEAN, BAZ_SD = -0.95, 1.05  # school-age equivalent

#: Month-to-month measurement noise: real anthropometry is not a smooth curve,
#: but a child does not swing two z-scores between visits either.
DRIFT_SD = 0.10
NOISE_SD = 0.06

MEAL_BY_CENTRE = {
    "anganwadi": ["breakfast", "lunch", "thr"],
    "ashram_school": ["breakfast", "lunch"],
}


@dataclass(slots=True)
class Child:
    index: int
    awc_code: str
    district: str
    block: str
    name: str
    dob: date
    gender: str
    poshan_tracker_id: str
    target_haz: float
    target_wasting: float

    @property
    def sex(self) -> Sex:
        return Sex.MALE if self.gender == "M" else Sex.FEMALE


def make_children(rng: random.Random, today: date) -> list[Child]:
    children: list[Child] = []
    index = 0
    for awc in reference.AWCS:
        lo, hi = awc["age_band_months"]
        for _ in range(awc["child_count"]):
            index += 1
            gender = rng.choice(["M", "F"])
            age_months = rng.uniform(lo, hi)
            dob = today - timedelta(days=int(age_months * DAYS_PER_MONTH))
            first = rng.choice(reference.BOY_NAMES if gender == "M" else reference.GIRL_NAMES)
            name = f"{first} {rng.choice(reference.SURNAMES)}"
            children.append(
                Child(
                    index=index,
                    awc_code=awc["awc_code"],
                    district=awc["district"],
                    block=awc["block"],
                    name=name,
                    dob=dob,
                    gender=gender,
                    # Section 12: reuse an external identifier rather than
                    # minting a parallel PII store. Synthetic here, but shaped
                    # like the real thing so integration is a swap, not a change.
                    poshan_tracker_id=f"PT{awc['awc_code'][3:10].replace('-', '')}{index:05d}",
                    target_haz=rng.gauss(HAZ_MEAN, HAZ_SD),
                    target_wasting=rng.gauss(WHZ_MEAN, WHZ_SD),
                )
            )
    return children


def measurement_for(
    child: Child, on: date, rng: random.Random, visit: int
) -> tuple[float, float] | None:
    """Invert the WHO tables to a (height_cm, weight_kg) hitting the targets.

    Returns None when the child falls outside every usable reference on this
    date -- rather than fabricating a measurement we could not score.
    """
    age_days = (on - child.dob).days
    if age_days < 0:
        return None

    # A slow drift plus per-visit noise: a child's z-score trends, it does not
    # resample from scratch each month.
    drift = rng.gauss(0.0, DRIFT_SD) * visit / 6.0
    haz_t = child.target_haz + drift + rng.gauss(0.0, NOISE_SD)

    try:
        hfa = lms_row(Indicator.HEIGHT_FOR_AGE, child.sex, age_days=age_days)
    except Exception:
        return None
    height = round(value_at_z(haz_t, hfa.l, hfa.m, hfa.s), 1)

    wasting_t = child.target_wasting + drift + rng.gauss(0.0, NOISE_SD)
    if age_days <= MAX_DAYS_2006:
        indicator = (
            Indicator.WEIGHT_FOR_LENGTH
            if age_days < LENGTH_TO_HEIGHT_DAYS
            else Indicator.WEIGHT_FOR_HEIGHT
        )
        try:
            row = lms_row(indicator, child.sex, length_cm=height)
        except Exception:
            return None
        weight = round(value_at_z(wasting_t, row.l, row.m, row.s), 1)
    else:
        try:
            row = lms_row(Indicator.BMI_FOR_AGE, child.sex, age_days=age_days)
        except Exception:
            return None
        bmi = value_at_z(wasting_t, row.l, row.m, row.s)
        weight = round(bmi * (height / 100.0) ** 2, 1)

    if height <= 0 or weight <= 0:
        return None
    return height, weight


def growth_visits(today: date, months: int = 6) -> list[date]:
    """Monthly measurement dates, ICDS practice, oldest first."""
    return [today - timedelta(days=int(m * DAYS_PER_MONTH)) for m in range(months, 0, -1)]


def assess_measurement(
    child: Child, on: date, height: float, weight: float
) -> GrowthAssessment | None:
    try:
        return assess(
            dob=child.dob,
            recorded_at=on,
            sex=child.sex,
            height_cm=height,
            weight_kg=weight,
        )
    except ValueError:
        return None


def serving_days(today: date, days: int = 60) -> list[date]:
    """Working days in the window. Sunday is not a PM POSHAN serving day."""
    window = [today - timedelta(days=d) for d in range(days, 0, -1)]
    return [d for d in window if d.weekday() != 6]


def capture_times(day: date, meal: str, rng: random.Random) -> datetime:
    hour = {"breakfast": 8, "lunch": 12, "thr": 15}[meal]
    return datetime.combine(
        day, time(hour=hour, minute=rng.randrange(0, 55), second=rng.randrange(0, 59))
    )


def compliance_for_day(awc: dict, day: date, rng: random.Random) -> dict:
    """One menu-compliance row: the Gadchiroli-precedent feature.

    Roughly one day in six is non-compliant, which is deliberately visible
    rather than rare -- an all-green demo dashboard demonstrates nothing, and
    the point of the feature is that it catches the bad days.
    """
    prescribed = reference.MENU_CYCLE[day.weekday()]
    detected = list(prescribed)
    flagged = False
    reason_en = reason_hi = None

    roll = rng.random()
    if roll < 0.16 and len(prescribed) > 2:
        # A genuine menu shortfall: one or two prescribed items never served.
        missing = rng.randint(1, 2)
        detected = rng.sample(prescribed, len(prescribed) - missing)
        flagged = True
        tmpl_en, tmpl_hi = reference.FLAG_REASONS[0]
        reason_en = tmpl_en.format(n=len(prescribed), m=len(detected))
        reason_hi = tmpl_hi.format(n=len(prescribed), m=len(detected))
    elif roll < 0.22:
        # A quality issue: every item present, but one of them is not right.
        flagged = True
        reason_en, reason_hi = reference.FLAG_REASONS[rng.randrange(1, len(reference.FLAG_REASONS))]

    compliance_pct = round(100.0 * len(detected) / len(prescribed), 2)
    return {
        "awc_code": awc["awc_code"],
        "district": awc["district"],
        "date": day,
        "prescribed_items": prescribed,
        "detected_items": detected,
        "compliance_pct": compliance_pct,
        "flagged": flagged,
        # The schema refuses a flagged row without a reason, so both are set
        # together or neither is.
        "flag_reason": f"{reason_en} | {reason_hi}" if flagged else None,
    }
