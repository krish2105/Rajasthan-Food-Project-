"""Deterministic nutrition arithmetic (Section 6.3).

The headline test is `test_the_three_times_bug_is_avoided`: it pins the exact
error that Section 6.3's formula produces if taken literally, so the fix cannot
be undone by someone "simplifying" the recipe layer away.
"""

from __future__ import annotations

import pytest

from app.nutrition import compute, ifct, recipes
from app.nutrition.recipes import Calibration


def test_the_three_times_bug_is_avoided() -> None:
    """IFCT is a RAW table; the camera sees COOKED food.

    Section 6.3 says `estimated_grams x (IFCT per-100g / 100)`. For 150 g of
    cooked rice that gives ~535 kcal, because it charges cooked weight at dry
    rice's density. The true figure is ~207. The error is always in the same
    direction -- it makes an underfed child look adequately fed.
    """
    naive = 150.0 * ifct.get("A015").energy_kcal / 100.0
    correct = compute.for_item(recipes.get("rice"), 150.0).energy_kcal
    assert naive == pytest.approx(535.0, abs=5.0)
    assert correct == pytest.approx(207.0, abs=5.0)
    assert naive / correct == pytest.approx(2.6, abs=0.2)


def test_energy_scales_linearly_with_the_observed_portion() -> None:
    single = compute.for_item(recipes.get("rice"), 150.0)
    double = compute.for_item(recipes.get("rice"), 300.0)
    assert double.energy_kcal == pytest.approx(single.energy_kcal * 2, rel=1e-6)
    assert double.servings == pytest.approx(single.servings * 2, rel=1e-6)


def test_a_zero_gram_portion_contributes_nothing() -> None:
    result = compute.for_item(recipes.get("dal"), 0.0)
    assert result.energy_kcal == 0.0 and result.protein_g == 0.0


def test_negative_portions_are_rejected() -> None:
    with pytest.raises(ValueError):
        compute.for_item(recipes.get("dal"), -10.0)


def test_ingredient_breakdown_makes_the_number_auditable() -> None:
    """Every plate figure must be walkable back to an ICMR-NIN value."""
    result = compute.for_item(recipes.get("khichdi"), 200.0)
    assert len(result.ingredients) == 3
    for ingredient in result.ingredients:
        assert ifct.get(ingredient.ifct_code)
        assert ingredient.raw_g > 0
    assert sum(i.energy_kcal for i in result.ingredients) == pytest.approx(
        result.energy_kcal, abs=0.2
    )


def test_oil_contributes_energy_despite_ifcts_published_zero() -> None:
    """Regression guard: if derived energy were dropped, every oil-cooked dish
    would silently lose ~9 kcal per gram of oil."""
    sabzi = compute.for_item(recipes.get("sabzi"), 75.0)
    oil = next(i for i in sabzi.ingredients if i.ifct_code == "T011")
    assert oil.energy_derived is True
    assert oil.energy_kcal > 20


# --------------------------------------------------------------------------
# Uncertainty
# --------------------------------------------------------------------------


def test_composition_errors_combine_in_quadrature_not_linearly() -> None:
    """Independent ingredients: summing errors linearly would overstate the
    spread of a mixed dish and make the estimate look less certain than it is."""
    result = compute.for_item(recipes.get("khichdi"), 200.0)
    linear = sum(
        ifct.get(i.ifct_code).energy_kcal_error * (i.raw_g / 100.0) for i in result.ingredients
    )
    assert 0 < result.energy_kcal_sd < linear


def test_plate_uncertainty_is_small_relative_to_the_estimate() -> None:
    """IFCT's regional variability is real but minor; portion estimation is what
    dominates. Reporting them separately keeps that visible."""
    plate = [(recipes.get("rice"), 150.0), (recipes.get("dal"), 120.0)]
    result = compute.for_plate(plate)
    assert result.energy_kcal_sd / result.energy_kcal < 0.05


# --------------------------------------------------------------------------
# Warnings and refusals
# --------------------------------------------------------------------------


def test_uncalibrated_dishes_warn_on_every_result() -> None:
    """Section 6.5's calibration session has not happened. Until it does, every
    cooked-dish figure must say so rather than passing as measured."""
    result = compute.for_item(recipes.get("dal"), 120.0)
    assert result.calibration == Calibration.UNCALIBRATED
    assert any("calibration pending" in w for w in result.warnings)


def test_uncooked_items_carry_no_calibration_warning() -> None:
    result = compute.for_item(recipes.get("banana"), 100.0)
    assert result.warnings == ()


def test_implausible_portions_are_flagged() -> None:
    """A child's plate does not hold a kilogram of dal. Same reasoning as the
    WHO implausible-value bounds in app/growth/assess.py."""
    result = compute.for_item(recipes.get("dal"), 1500.0)
    assert any("plausibility bound" in w for w in result.warnings)


def test_plausible_portions_are_not_flagged() -> None:
    result = compute.for_item(recipes.get("dal"), 130.0)
    assert not any("plausibility bound" in w for w in result.warnings)


def test_uncosted_items_are_reported_on_the_plate_total() -> None:
    result = compute.for_plate([(recipes.get("rice"), 150.0)], uncosted=["pizza", "biryani"])
    assert result.uncosted_items == ("pizza", "biryani")
    assert any("not in the PM POSHAN vocabulary" in w for w in result.warnings)


def test_an_empty_plate_totals_to_zero_without_error() -> None:
    result = compute.for_plate([])
    assert result.energy_kcal == 0.0 and result.items == ()


def test_totals_equal_the_sum_of_items() -> None:
    plate = [
        (recipes.get(c), g)
        for c, g in (("rice", 150.0), ("dal", 120.0), ("sabzi", 75.0), ("roti", 80.0))
    ]
    result = compute.for_plate(plate)
    assert result.energy_kcal == pytest.approx(sum(i.energy_kcal for i in result.items), abs=0.2)
    assert result.protein_g == pytest.approx(sum(i.protein_g for i in result.items), abs=0.05)


def test_computation_is_deterministic() -> None:
    """The property that makes an estimate auditable rather than merely produced."""
    plate = [(recipes.get("rice"), 147.3), (recipes.get("dal"), 118.6)]
    assert compute.for_plate(plate) == compute.for_plate(plate)
