"""IFCT 2017 lookup: exact by code, fuzzy by name.

Section 4 names the Indian Food Composition Tables (ICMR-NIN, 2017) as the
authoritative nutrition source for this system. This module is the only way the
rest of the codebase reads them.

Two things it is careful about:

**Units.** IFCT publishes energy in kilojoules. The vendored CSV keeps it that
way and the conversion happens here, unit-tested, rather than being silently
baked into the data file -- the same discipline the WHO tables get in
`app/growth/lms.py`. IFCT also publishes `energy_kj = 0` for the 14 edible oils
and fats, which is a real gap in the source rather than a real zero, so energy
for those is derived from macronutrients using Atwater factors and flagged.

**Everything here is per 100 g of RAW edible portion.** A camera photographs
cooked food. Converting between the two is `app/nutrition/recipes.py`'s job, and
skipping it overstates a plate of rice by roughly three times.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

IFCT_PATH = Path(__file__).resolve().parent / "ifct" / "ifct2017.csv"

#: Thermochemical conversion, exact by definition.
KJ_PER_KCAL = 4.184

#: Atwater general factors (kcal/g), used only to fill IFCT's published zeros
#: for pure fats and oils. Not used anywhere a real IFCT energy value exists.
ATWATER = {"protein": 4.0, "carbohydrate": 4.0, "fat": 9.0}

#: Below this, a fuzzy name match is refused. Chosen so that a near-miss on a
#: real food still matches ("chawal" -> "Rice, raw, milled") but an unrelated
#: word does not silently resolve to whatever scored highest. A wrong match here
#: is worse than no match: it produces a confident calorie figure for a food
#: that was never on the plate.
MIN_MATCH_SCORE = 78.0


@dataclass(frozen=True, slots=True)
class FoodValue:
    """Per-100 g values with IFCT's own national variability."""

    value: float
    error: float = 0.0

    def scaled(self, grams: float) -> tuple[float, float]:
        factor = grams / 100.0
        return self.value * factor, self.error * factor


@dataclass(frozen=True, slots=True)
class Food:
    code: str
    name: str
    hindi_name: str
    food_group: str
    scientific_name: str
    local_names: str
    energy_kj: FoodValue
    protein_g: FoodValue
    carbohydrate_g: FoodValue
    fat_g: FoodValue
    fibre_g: float
    water_g: float
    #: True when IFCT published no energy and it was derived from macros.
    energy_derived: bool

    @property
    def energy_kcal(self) -> float:
        return self.energy_kj.value / KJ_PER_KCAL

    @property
    def energy_kcal_error(self) -> float:
        return self.energy_kj.error / KJ_PER_KCAL

    def display_name(self, lang: str = "en") -> str:
        if lang == "hi" and self.hindi_name:
            return self.hindi_name
        return self.name


class FoodNotFound(LookupError):
    """No IFCT entry matched, and we decline to guess.

    Raised rather than falling back to a default food. Section 6.3 makes the
    nutrition lookup deterministic precisely so it cannot invent numbers; a
    silent fallback would reintroduce exactly that.
    """


def _num(raw: str) -> float:
    raw = (raw or "").strip()
    if not raw:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _derive_energy_kj(protein: float, carbs: float, fat: float) -> float:
    kcal = protein * ATWATER["protein"] + carbs * ATWATER["carbohydrate"] + fat * ATWATER["fat"]
    return kcal * KJ_PER_KCAL


def _normalise(text: str) -> str:
    """Fold a food name to a comparable form.

    Strips accents and punctuation and collapses whitespace, so that "Rice,
    raw, milled", "rice raw milled" and "RICE RAW MILLED" are one key. Also
    handles the Devanagari a vision model may return, which normalises to
    itself but must not be mangled by the ASCII fold.
    """
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\sऀ-ॿ]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=1)
def load_foods() -> dict[str, Food]:
    """Load and cache the vendored table, keyed by IFCT code."""
    if not IFCT_PATH.exists():  # pragma: no cover - configuration error
        raise FileNotFoundError(f"Missing {IFCT_PATH}. Run: python scripts/fetch_ifct_table.py")
    foods: dict[str, Food] = {}
    with IFCT_PATH.open(encoding="utf-8") as fh:
        reader = csv.DictReader(line for line in fh if not line.startswith("#"))
        for row in reader:
            protein = _num(row["protein_g"])
            carbs = _num(row["carbohydrate_g"])
            fat = _num(row["fat_g"])
            energy = _num(row["energy_kj"])
            derived = energy == 0.0
            if derived:
                energy = _derive_energy_kj(protein, carbs, fat)
            foods[row["code"]] = Food(
                code=row["code"],
                name=row["name"],
                hindi_name=row["hindi_name"],
                food_group=row["food_group"],
                scientific_name=row["scientific_name"],
                local_names=row["local_names"],
                energy_kj=FoodValue(energy, _num(row["energy_kj_e"])),
                protein_g=FoodValue(protein, _num(row["protein_g_e"])),
                carbohydrate_g=FoodValue(carbs, _num(row["carbohydrate_g_e"])),
                fat_g=FoodValue(fat, _num(row["fat_g_e"])),
                fibre_g=_num(row["fibre_g"]),
                water_g=_num(row["water_g"]),
                energy_derived=derived,
            )
    return foods


def get(code: str) -> Food:
    """Exact lookup by IFCT code. The path every recipe uses."""
    try:
        return load_foods()[code.strip().upper()]
    except KeyError as exc:
        raise FoodNotFound(f"no IFCT 2017 entry with code {code!r}") from exc


@lru_cache(maxsize=1)
def _search_index() -> dict[str, str]:
    """Normalised searchable string -> IFCT code.

    Every food contributes its English name, its Hindi name where IFCT has one,
    and each of its other local names. A vision model shown an Indian plate is
    at least as likely to answer "chawal" or "masoor dal" as "Rice, raw, milled",
    and IFCT already carries those synonyms -- there is no need to invent a
    vocabulary alongside it.
    """
    index: dict[str, str] = {}
    for food in load_foods().values():
        candidates = [food.name]
        if food.hindi_name:
            candidates.append(food.hindi_name)
        for part in food.local_names.split(";"):
            # "H. Ramdana" -> "Ramdana"
            cleaned = re.sub(r"^\s*[A-Za-z.]{1,6}\.\s*", "", part).strip()
            if cleaned:
                candidates.append(cleaned)
        for candidate in candidates:
            key = _normalise(candidate)
            # First writer wins: IFCT is ordered by code, so a generic entry
            # earlier in a group beats a later cultivar for an ambiguous name.
            if key and key not in index:
                index[key] = food.code
    return index


@dataclass(frozen=True, slots=True)
class Match:
    food: Food
    score: float
    matched_on: str


def search(name: str, *, limit: int = 5, min_score: float = MIN_MATCH_SCORE) -> list[Match]:
    """Rank IFCT entries against a free-text food name. Returns candidates.

    **This must never drive a nutrition calculation.** It returns a ranked list,
    not an answer, because for this dataset a single answer cannot be trusted.

    Section 6.2 anticipated that unconstrained `food_name` values would fail the
    lookup silently and asked for a fuzzy fallback. Testing showed the real
    failure is louder and worse than silence: free text matches confident
    nonsense across IFCT's 542 entries. "dal" scores 90 against *Ragi*; "kela"
    and "aalu" score a perfect 100 against *Plantain, green* and *Yam,
    ordinary*. Those are not scorer artefacts -- they are IFCT's own listed
    local-name synonyms for other cultivars, so the ambiguity is real and no
    threshold or scorer separates them. (Verified across WRatio, QRatio,
    token_sort_ratio and ratio.)

    The pipeline therefore matches against the curated PM POSHAN vocabulary in
    `app/nutrition/recipes.py`, which names its IFCT codes explicitly, and reads
    this table only through `get()`. This function exists for the eval labelling
    CLI and for a human exploring the data, where a person picks from the
    candidates.
    """
    key = _normalise(name)
    if not key:
        raise FoodNotFound("empty food name")

    index = _search_index()
    ranked = process.extract(key, index.keys(), scorer=fuzz.WRatio, limit=limit)
    matches = [
        Match(get(index[matched]), float(score), matched)
        for matched, score, _ in ranked
        if score >= min_score
    ]
    if not matches:
        raise FoodNotFound(f"no IFCT 2017 candidate for {name!r} at score >= {min_score:.0f}")
    return matches


def search_or_empty(name: str, *, limit: int = 5) -> list[Match]:
    try:
        return search(name, limit=limit)
    except FoodNotFound:
        return []
