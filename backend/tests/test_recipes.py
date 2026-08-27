"""The cooked-to-raw recipe layer, and the closed PM POSHAN vocabulary.

This is Phase 2's correctness core, for the same reason `test_who_lms.py` was
Phase 1's: it is where a plausible-looking mistake would produce authoritative
wrong numbers.
"""

from __future__ import annotations

import pytest

from app.nutrition import compute, ifct, recipes
from app.nutrition.recipes import Calibration


def test_every_ingredient_resolves_to_a_real_ifct_code() -> None:
    """A typo'd code would raise at runtime on a live plate. Catch it here."""
    for dish in recipes.DISHES:
        for ingredient in dish.ingredients:
            food = ifct.get(ingredient.ifct_code)
            assert food.code == ingredient.ifct_code
            assert ingredient.raw_g > 0


def test_every_dish_documents_where_its_numbers_came_from() -> None:
    for dish in recipes.DISHES:
        assert dish.source, f"{dish.code} has no provenance note"
        assert dish.calibration in {
            Calibration.UNCALIBRATED,
            Calibration.MEASURED,
            Calibration.NOT_APPLICABLE,
        }


def test_cooked_dishes_are_marked_uncalibrated_until_plates_are_weighed() -> None:
    """Section 6.5 requires a calibration session before any accuracy claim.
    Until it happens, no cooked dish may claim a measured yield."""
    for dish in recipes.DISHES:
        if dish.code in {"banana", "egg", "milk"}:
            assert dish.calibration == Calibration.NOT_APPLICABLE
        else:
            assert dish.calibration == Calibration.UNCALIBRATED


@pytest.mark.parametrize(
    ("code", "low", "high"),
    [
        ("rice", 2.2, 3.2),  # absorbs water
        ("khichdi", 2.5, 3.5),  # absorbs heavily
        ("dal", 2.5, 6.0),  # served thin
        ("roti", 1.1, 1.6),  # gains water, loses some in cooking
        ("sabzi", 0.7, 1.0),  # loses water
    ],
)
def test_yield_factors_are_physically_sensible(code: str, low: float, high: float) -> None:
    """A yield factor outside these ranges means a serving weight or an
    ingredient quantity is wrong, and every calorie for that dish is wrong with
    it."""
    assert low <= recipes.get(code).yield_factor <= high


def test_uncooked_items_have_a_yield_of_one() -> None:
    for code in ("banana", "egg", "milk"):
        assert recipes.get(code).yield_factor == pytest.approx(1.0, abs=1e-9)


def test_pulse_quantities_match_the_pm_poshan_norm() -> None:
    """Dal carries the primary-stage 20 g pulse entitlement, so the recipe
    traces to a government norm rather than to a guess."""
    dal = recipes.get("dal")
    pulses = sum(i.raw_g for i in dal.ingredients if i.ifct_code.startswith("B"))
    assert pulses == pytest.approx(recipes.PM_POSHAN_NORMS["primary"]["pulses"], abs=0.1)


def test_a_standard_plate_reproduces_the_pm_poshan_target() -> None:
    """The strongest independent check available on this table.

    The recipes were anchored to PM POSHAN's raw entitlements; totalling a
    standard plate through IFCT should land back on PM POSHAN's own published
    outcome of 450 kcal / 12 g protein for the primary stage. If a serving
    weight or yield factor drifts, this catches it.
    """
    plate = [
        (recipes.get("rice"), 150.0),
        (recipes.get("dal"), 120.0),
        (recipes.get("sabzi"), 75.0),
        (recipes.get("banana"), 100.0),
    ]
    result = compute.for_plate(plate)
    assert result.energy_kcal == pytest.approx(450.0, rel=0.15)
    assert result.protein_g == pytest.approx(12.0, rel=0.20)


# --------------------------------------------------------------------------
# The closed vocabulary
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("dal", "dal"),
        ("daal", "dal"),
        ("toor dal", "dal"),
        ("chawal", "rice"),
        ("boiled rice", "rice"),
        ("bhaat", "rice"),
        ("kela", "banana"),
        ("ripe banana", "banana"),
        ("chapati", "roti"),
        ("phulka", "roti"),
        ("aloo sabzi", "sabzi"),
        ("mixed vegetable", "sabzi"),
        ("khichri", "khichdi"),
    ],
)
def test_common_names_map_to_the_right_dish(query: str, expected: str) -> None:
    dish, _ = recipes.match(query)
    assert dish.code == expected


@pytest.mark.parametrize("query", ["दाल", "चावल", "रोटी", "खिचड़ी", "केला", "सब्ज़ी"])
def test_devanagari_names_match(query: str) -> None:
    """The Field PWA is Hindi-first and a vision model may answer in Devanagari."""
    assert recipes.match(query)[0].code in recipes.vocabulary()


@pytest.mark.parametrize("query", ["dal", "kela", "aalu ki sabzi", "chawal"])
def test_the_terms_that_broke_free_text_ifct_matching_now_resolve(query: str) -> None:
    """Same inputs as tests/test_ifct.py's unsafe-matching test.

    Against 542 ambiguous IFCT names these returned Ragi, plantain and yam.
    Against ~76 curated aliases they return the right dish. That difference is
    the entire argument for the closed vocabulary.
    """
    assert recipes.match_or_none(query) is not None


@pytest.mark.parametrize("query", ["pizza", "biryani", "sushi", "cake", "chow mein"])
def test_foods_outside_the_pm_poshan_menu_are_refused(query: str) -> None:
    """Refused, not approximated. An unmatched item is reported to the officer
    as detected-but-not-costed, which is honest."""
    with pytest.raises(recipes.DishNotFound):
        recipes.match(query)


def test_empty_and_unknown_codes_raise() -> None:
    with pytest.raises(recipes.DishNotFound):
        recipes.match("")
    with pytest.raises(recipes.DishNotFound):
        recipes.get("nonexistent")


def test_vocabulary_matches_the_dish_table() -> None:
    """The vocabulary handed to the model must be exactly what we can cost."""
    assert set(recipes.vocabulary()) == set(recipes.DISHES_BY_CODE)


def test_every_dish_is_bilingual() -> None:
    for dish in recipes.DISHES:
        assert dish.name_en and dish.name_hi
        assert dish.aliases
