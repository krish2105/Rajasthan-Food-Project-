"""Cooked dishes -> raw ingredients, so IFCT can be used the way IFCT works.

The problem this module exists to solve
---------------------------------------
Section 6.3 specifies `estimated_grams x (IFCT per-100g value / 100)`. Applied
literally that is wrong by roughly a factor of three, because IFCT 2017 is a
table of **raw** foods -- 534 of its 542 entries -- while a camera photographs
**cooked** food:

    IFCT "Rice, raw, milled"  = 356 kcal/100 g
    cooked rice               = ~130 kcal/100 g   (it absorbed ~2.6x its weight in water)

A pipeline that skipped this step would report a plate of rice at three times its
real energy. The direction of that error matters: it would systematically make
undernourished children look adequately fed, which is the worst possible
direction for this system to be wrong in.

The other problem: a closed vocabulary
--------------------------------------
Section 6.2 says `food_name` values must be constrained to the IFCT vocabulary
or the lookup fails silently. Testing showed the danger is worse than silence.
Fuzzy-matching free text across all 542 IFCT foods returns confident nonsense --
"dal" scores 90 against *Ragi*, and "kela" and "aalu" score a perfect 100
against *Plantain, green* and *Yam, ordinary*, because those are genuinely
IFCT's own listed synonyms for other cultivars. No fuzzy scorer fixes it; the
ambiguity is real.

So the vision model is constrained to the small vocabulary below, and every
dish names its IFCT codes **explicitly**. IFCT is only ever read by exact code
(`ifct.get`). Fuzzy matching happens against dish aliases -- a set of roughly
thirty strings -- never against the full food table.

Provenance of the numbers
-------------------------
Raw grain, pulse, vegetable and oil quantities are anchored to the **PM POSHAN**
per-child norms, which are the governing Indian standard and numbers a district
officer already knows:

    Primary (Classes I-V):        100 g grains, 20 g pulses, 50 g vegetables, 5.0 g oil
    Upper primary (VI-VIII):      150 g grains, 30 g pulses, 75 g vegetables, 7.5 g oil

ICDS supplementary nutrition at Anganwadi centres targets 500 kcal / 12-15 g
protein per child per day (800 kcal / 20-25 g for a severely malnourished child).

Cooked serving weights and yield factors are standard kitchen values, and they
are the **least certain numbers in this system**. Section 6.5 calls for a
calibration session with dietitian-weighed reference plates before any accuracy
figure is quoted; every dish below therefore carries a `calibration` marker, and
`app/eval/` reports the uncalibrated ones explicitly rather than letting them
pass as measured. They are a documented, adjustable prior -- not a measurement.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from rapidfuzz import fuzz, process

#: PM POSHAN per-child raw entitlements (grams), by school stage.
PM_POSHAN_NORMS = {
    "primary": {"grains": 100.0, "pulses": 20.0, "vegetables": 50.0, "oil": 5.0},
    "upper_primary": {"grains": 150.0, "pulses": 30.0, "vegetables": 75.0, "oil": 7.5},
}

#: ICDS supplementary nutrition daily targets (kcal, grams protein).
ICDS_TARGETS = {
    "child_6m_3y": (500.0, 12.0),
    "child_3y_6y": (500.0, 12.0),
    "severely_malnourished": (800.0, 20.0),
}


class Calibration:
    """How much to trust a dish's cooked-serving weight and yield."""

    #: Standard kitchen value; not yet checked against a weighed plate.
    UNCALIBRATED = "uncalibrated"
    #: Confirmed against dietitian-weighed reference plates (Section 6.5).
    MEASURED = "measured"
    #: No cooking transformation at all -- raw fruit, milk, a boiled egg.
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class Ingredient:
    """One raw ingredient, in grams, for a single standard cooked serving."""

    ifct_code: str
    raw_g: float
    note: str = ""


@dataclass(frozen=True, slots=True)
class Dish:
    code: str
    name_en: str
    name_hi: str
    #: Everything a vision model might plausibly return for this dish, in
    #: English, romanised Hindi and Devanagari. This is the closed vocabulary.
    aliases: tuple[str, ...]
    #: Weight of one standard serving as it appears on the plate.
    cooked_serving_g: float
    ingredients: tuple[Ingredient, ...]
    calibration: str
    #: Where the numbers came from, so a reviewer can check them.
    source: str

    @property
    def raw_total_g(self) -> float:
        return sum(i.raw_g for i in self.ingredients)

    @property
    def yield_factor(self) -> float:
        """Cooked grams produced per gram of raw ingredient.

        Above 1 means water was absorbed (rice, dal); below 1 means water was
        driven off (sabzi). Reported so the assumption is inspectable rather
        than buried inside a serving weight.
        """
        return self.cooked_serving_g / self.raw_total_g if self.raw_total_g else 1.0


_PM = "PM POSHAN per-child norm"
_KITCHEN = "standard serving weight; pending Section 6.5 calibration"

DISHES: tuple[Dish, ...] = (
    Dish(
        code="dal",
        name_en="Dal (lentils)",
        name_hi="दाल",
        aliases=(
            "dal",
            "daal",
            "dhal",
            "lentils",
            "lentil curry",
            "toor dal",
            "arhar dal",
            "tur dal",
            "दाल",
            "अरहर दाल",
        ),
        cooked_serving_g=120.0,
        ingredients=(
            Ingredient("B021", 20.0, "red gram (toor) dal - PM POSHAN pulse norm, primary"),
            Ingredient("T011", 2.5, "cooking oil, half the primary oil norm"),
            Ingredient("G017", 8.0, "onion"),
            Ingredient("D076", 8.0, "tomato"),
        ),
        calibration=Calibration.UNCALIBRATED,
        source=f"{_PM} (20 g pulses); {_KITCHEN}. Dal is served thin, so the "
        "yield factor is high and is the single most calibration-sensitive "
        "number in this table.",
    ),
    Dish(
        code="rice",
        name_en="Rice",
        name_hi="चावल",
        aliases=(
            "rice",
            "boiled rice",
            "steamed rice",
            "plain rice",
            "bhaat",
            "chawal",
            "chaval",
            "चावल",
            "भात",
        ),
        cooked_serving_g=150.0,
        ingredients=(Ingredient("A015", 58.0, "raw milled rice"),),
        calibration=Calibration.UNCALIBRATED,
        source=f"Rice absorbs roughly 2.6x its weight in water. {_KITCHEN}",
    ),
    Dish(
        code="roti",
        name_en="Roti",
        name_hi="रोटी",
        aliases=(
            "roti",
            "chapati",
            "chapatti",
            "phulka",
            "flatbread",
            "wheat roti",
            "रोटी",
            "चपाती",
        ),
        cooked_serving_g=40.0,
        ingredients=(Ingredient("A019", 30.0, "wheat atta, one roti"),),
        calibration=Calibration.UNCALIBRATED,
        source="One roti from ~30 g atta; dough gains water, then loses some in "
        f"cooking. {_KITCHEN}",
    ),
    Dish(
        code="khichdi",
        name_en="Khichdi",
        name_hi="खिचड़ी",
        aliases=("khichdi", "khichadi", "khichri", "kichadi", "rice and lentil porridge", "खिचड़ी"),
        cooked_serving_g=200.0,
        ingredients=(
            Ingredient("A015", 45.0, "raw milled rice"),
            Ingredient("B010", 18.0, "green gram (moong) dal"),
            Ingredient("T011", 3.0, "cooking oil"),
        ),
        calibration=Calibration.UNCALIBRATED,
        source=f"{_PM} pulses; khichdi is cooked soft and absorbs heavily. {_KITCHEN}",
    ),
    Dish(
        code="sabzi",
        name_en="Seasonal vegetable",
        name_hi="मौसमी सब्ज़ी",
        aliases=(
            "sabzi",
            "sabji",
            "subzi",
            "vegetable",
            "vegetables",
            "mixed vegetable",
            "curry",
            "aloo sabzi",
            "potato curry",
            "सब्ज़ी",
            "सब्जी",
            "आलू की सब्ज़ी",
        ),
        cooked_serving_g=75.0,
        ingredients=(
            Ingredient("F006", 45.0, "potato"),
            Ingredient("D036", 25.0, "cauliflower"),
            Ingredient("G017", 10.0, "onion"),
            Ingredient("T011", 3.0, "cooking oil"),
        ),
        calibration=Calibration.UNCALIBRATED,
        source=f"{_PM} (50 g vegetables, primary); vegetables lose water in "
        f"cooking so the yield factor is below 1. {_KITCHEN}",
    ),
    Dish(
        code="banana",
        name_en="Banana",
        name_hi="केला",
        aliases=("banana", "ripe banana", "kela", "केला"),
        cooked_serving_g=100.0,
        ingredients=(Ingredient("E012", 100.0, "banana, ripe, robusta - edible portion"),),
        calibration=Calibration.NOT_APPLICABLE,
        source="Raw fruit; no cooking transformation. One medium banana, edible portion.",
    ),
    Dish(
        code="egg",
        name_en="Boiled egg",
        name_hi="उबला अंडा",
        aliases=("egg", "boiled egg", "anda", "hard boiled egg", "अंडा", "उबला अंडा"),
        cooked_serving_g=50.0,
        ingredients=(Ingredient("M001", 50.0, "one poultry egg, edible portion"),),
        calibration=Calibration.NOT_APPLICABLE,
        source="Boiling does not change an egg's mass materially.",
    ),
    Dish(
        code="milk",
        name_en="Milk",
        name_hi="दूध",
        aliases=("milk", "doodh", "dudh", "cow milk", "दूध"),
        cooked_serving_g=150.0,
        ingredients=(Ingredient("L002", 150.0, "whole cow milk"),),
        calibration=Calibration.NOT_APPLICABLE,
        source="Liquid, served as-is.",
    ),
    Dish(
        code="sprouts",
        name_en="Sprouted pulses",
        name_hi="अंकुरित दाल",
        aliases=(
            "sprouts",
            "sprouted pulses",
            "sprouted moong",
            "ankurit dal",
            "अंकुरित दाल",
            "अंकुरित मूंग",
        ),
        cooked_serving_g=60.0,
        ingredients=(Ingredient("B010", 25.0, "green gram, sprouted"),),
        calibration=Calibration.UNCALIBRATED,
        source=f"Sprouting hydrates the pulse without cooking it. {_KITCHEN}",
    ),
    Dish(
        code="halwa",
        name_en="Sweet halwa",
        name_hi="हलवा",
        aliases=("halwa", "halva", "sooji halwa", "suji halwa", "sweet dish", "हलवा", "सूजी हलवा"),
        cooked_serving_g=80.0,
        ingredients=(
            Ingredient("A019", 25.0, "wheat flour"),
            Ingredient("I001", 18.0, "jaggery"),
            Ingredient("T013", 6.0, "ghee"),
        ),
        calibration=Calibration.UNCALIBRATED,
        source=f"{_KITCHEN}. Jaggery rather than refined sugar, matching what "
        "PM POSHAN kitchens in this belt actually use.",
    ),
)

DISHES_BY_CODE: dict[str, Dish] = {d.code: d for d in DISHES}


class DishNotFound(LookupError):
    """The detected food is not in the PM POSHAN vocabulary.

    Raised rather than guessed at. An unmatched item is reported to the district
    officer as "detected but not costed", which is honest, instead of being
    silently mapped to whatever scored highest -- the failure mode that made
    free-text IFCT matching unusable.
    """


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\sऀ-ॿ]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for dish in DISHES:
        for alias in (dish.code, dish.name_en, dish.name_hi, *dish.aliases):
            key = _normalise(alias)
            if key:
                index.setdefault(key, dish.code)
    return index


#: Higher than a general-purpose fuzzy threshold, and it can afford to be:
#: matching happens against ~90 curated aliases rather than 542 ambiguous food
#: names, so a real dish name lands near 100 and anything else is genuinely
#: unknown.
MIN_ALIAS_SCORE = 85.0


def get(code: str) -> Dish:
    try:
        return DISHES_BY_CODE[code.strip().lower()]
    except KeyError as exc:
        raise DishNotFound(f"no dish with code {code!r}") from exc


def match(name: str, *, min_score: float = MIN_ALIAS_SCORE) -> tuple[Dish, float]:
    """Map a detected food name onto the PM POSHAN vocabulary."""
    key = _normalise(name)
    if not key:
        raise DishNotFound("empty food name")
    index = _alias_index()
    if key in index:
        return get(index[key]), 100.0
    result = process.extractOne(key, index.keys(), scorer=fuzz.WRatio)
    if result is None or result[1] < min_score:
        best = f" (closest: {result[0]!r} at {result[1]:.0f})" if result else ""
        raise DishNotFound(f"{name!r} is not in the PM POSHAN menu vocabulary{best}")
    return get(index[result[0]]), float(result[1])


def match_or_none(name: str, *, min_score: float = MIN_ALIAS_SCORE):
    try:
        return match(name, min_score=min_score)
    except DishNotFound:
        return None


def vocabulary() -> list[str]:
    """The closed list handed to the vision model in its prompt (Section 6.2)."""
    return [d.code for d in DISHES]
