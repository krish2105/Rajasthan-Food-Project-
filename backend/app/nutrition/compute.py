"""Deterministic macronutrient calculation. No model touches this path.

Section 6.3 is emphatic about the split, and it is the most important
accuracy-versus-hype decision in the system: **the AI's job is portion
estimation from a photo; the nutrition arithmetic is a lookup table.** A
language model asked for calories will happily produce plausible wrong numbers,
so it is never asked.

The chain is fully traceable:

    observed cooked grams
      -> servings           (cooked grams / dish's standard cooked serving)
      -> raw ingredient g   (recipe, anchored to PM POSHAN norms)
      -> IFCT lookup        (by exact code, never fuzzy)
      -> energy and macros

Every number in a result can be walked back to either an ICMR-NIN published
value or a documented PM POSHAN norm.

On uncertainty
--------------
Two independent sources, reported separately because they behave differently
and because collapsing them into one figure would overstate what we know:

* **Composition variability** -- IFCT's own `_e` spread across the six regions
  it sampled. Small, and it shrinks in relative terms as items are summed.
* **Portion uncertainty** -- the vision model's gram estimate. Large, and it
  dominates. Section 6.5 targets MAE <= 25 g per item, and until the calibration
  session happens that target is a goal rather than a measurement.

Composition errors are combined in quadrature across independent ingredients.
Portion uncertainty is applied by the caller, which knows the model's confidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.nutrition import ifct
from app.nutrition.recipes import Calibration, Dish

#: A single item beyond this is treated as an implausible portion. A child's
#: plate does not hold a kilogram of one dish, and a vision model that says so
#: has misjudged scale -- the same reasoning as the WHO implausible-value bounds
#: in app/growth/assess.py.
MAX_PLAUSIBLE_ITEM_G = 1000.0


@dataclass(frozen=True, slots=True)
class IngredientBreakdown:
    ifct_code: str
    ifct_name: str
    raw_g: float
    energy_kcal: float
    protein_g: float
    carbohydrate_g: float
    fat_g: float
    energy_derived: bool


@dataclass(frozen=True, slots=True)
class ItemNutrition:
    dish_code: str
    dish_name_en: str
    dish_name_hi: str
    cooked_g: float
    servings: float
    energy_kcal: float
    protein_g: float
    carbohydrate_g: float
    fat_g: float
    #: One-sigma composition uncertainty from IFCT's regional variability.
    energy_kcal_sd: float
    protein_g_sd: float
    calibration: str
    ingredients: tuple[IngredientBreakdown, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlateNutrition:
    items: tuple[ItemNutrition, ...]
    energy_kcal: float
    protein_g: float
    carbohydrate_g: float
    fat_g: float
    energy_kcal_sd: float
    protein_g_sd: float
    #: Dish codes detected but absent from the PM POSHAN vocabulary. Reported,
    #: never silently costed.
    uncosted_items: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def any_uncalibrated(self) -> bool:
        return any(i.calibration == Calibration.UNCALIBRATED for i in self.items)


def for_item(dish: Dish, cooked_g: float) -> ItemNutrition:
    """Macros for one dish at an observed cooked weight."""
    if cooked_g < 0:
        raise ValueError("cooked_g must not be negative")

    warnings: list[str] = []
    if cooked_g > MAX_PLAUSIBLE_ITEM_G:
        warnings.append(
            f"{cooked_g:.0f} g of {dish.code} exceeds the {MAX_PLAUSIBLE_ITEM_G:.0f} g "
            "plausibility bound for a single item; the portion estimate is "
            "probably a scale error"
        )
    if dish.calibration == Calibration.UNCALIBRATED:
        warnings.append(
            f"{dish.code}: cooked-serving weight and yield factor are standard "
            "kitchen values, not measured. Section 6.5 calibration pending."
        )

    servings = cooked_g / dish.cooked_serving_g if dish.cooked_serving_g else 0.0

    breakdown: list[IngredientBreakdown] = []
    energy = protein = carbs = fat = 0.0
    energy_var = protein_var = 0.0

    for ingredient in dish.ingredients:
        food = ifct.get(ingredient.ifct_code)
        raw_g = ingredient.raw_g * servings

        e_val, e_err = food.energy_kj.scaled(raw_g)
        p_val, p_err = food.protein_g.scaled(raw_g)
        c_val, _ = food.carbohydrate_g.scaled(raw_g)
        f_val, _ = food.fat_g.scaled(raw_g)

        e_kcal = e_val / ifct.KJ_PER_KCAL
        energy += e_kcal
        protein += p_val
        carbs += c_val
        fat += f_val
        # Ingredients are independent samples, so their errors add in quadrature
        # rather than linearly -- summing them linearly would overstate the
        # spread of a mixed dish.
        energy_var += (e_err / ifct.KJ_PER_KCAL) ** 2
        protein_var += p_err**2

        breakdown.append(
            IngredientBreakdown(
                ifct_code=food.code,
                ifct_name=food.name,
                raw_g=round(raw_g, 2),
                energy_kcal=round(e_kcal, 1),
                protein_g=round(p_val, 2),
                carbohydrate_g=round(c_val, 2),
                fat_g=round(f_val, 2),
                energy_derived=food.energy_derived,
            )
        )

    return ItemNutrition(
        dish_code=dish.code,
        dish_name_en=dish.name_en,
        dish_name_hi=dish.name_hi,
        cooked_g=round(cooked_g, 1),
        servings=round(servings, 3),
        energy_kcal=round(energy, 1),
        protein_g=round(protein, 2),
        carbohydrate_g=round(carbs, 2),
        fat_g=round(fat, 2),
        energy_kcal_sd=round(math.sqrt(energy_var), 2),
        protein_g_sd=round(math.sqrt(protein_var), 3),
        calibration=dish.calibration,
        ingredients=tuple(breakdown),
        warnings=tuple(warnings),
    )


def for_plate(
    items: list[tuple[Dish, float]], *, uncosted: list[str] | None = None
) -> PlateNutrition:
    """Total a plate from (dish, cooked_grams) pairs."""
    computed = [for_item(dish, grams) for dish, grams in items]
    warnings = [w for item in computed for w in item.warnings]

    if uncosted:
        warnings.append(
            f"{len(uncosted)} detected item(s) are not in the PM POSHAN "
            f"vocabulary and are excluded from the totals: {', '.join(uncosted)}"
        )

    return PlateNutrition(
        items=tuple(computed),
        energy_kcal=round(sum(i.energy_kcal for i in computed), 1),
        protein_g=round(sum(i.protein_g for i in computed), 2),
        carbohydrate_g=round(sum(i.carbohydrate_g for i in computed), 2),
        fat_g=round(sum(i.fat_g for i in computed), 2),
        energy_kcal_sd=round(math.sqrt(sum(i.energy_kcal_sd**2 for i in computed)), 2),
        protein_g_sd=round(math.sqrt(sum(i.protein_g_sd**2 for i in computed)), 3),
        uncosted_items=tuple(uncosted or ()),
        warnings=tuple(warnings),
    )
