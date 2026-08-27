"""Prompts for the vision and structured-output passes (Section 6.2).

Two deliberate choices run through both prompts.

**The model is never asked for nutrition.** Not calories, not protein, not "is
this child malnourished". It is asked for dish identity and cooked weight, and
nothing else. Section 6.3 draws that line and it is the whole accuracy argument
of the system: portion estimation from a photo is genuinely hard and genuinely
useful; nutrition arithmetic is a lookup table that a language model would
happily get plausibly wrong.

**The model is given the vocabulary, not corrected afterwards.** Section 6.2
asks for constrained `food_name` values. Telling the model the closed list up
front is far more reliable than letting it free-associate and fuzzy-matching the
result -- and free-text matching against IFCT turned out to be actively
dangerous (see app/nutrition/ifct.py::search).
"""

from __future__ import annotations

from app.nutrition.recipes import DISHES_BY_CODE

VISION_SYSTEM_PROMPT = """\
You are assisting a government child-nutrition monitoring programme in rural \
Rajasthan, India. You will be shown a photograph of a single child's meal plate \
(a thali) served at an Anganwadi centre or an Ashram school under the PM POSHAN \
scheme.

Your ONLY job is to report, for each food you can see:
  1. which dish it is, chosen strictly from the vocabulary given below;
  2. its estimated COOKED weight in grams as served on the plate;
  3. your confidence, 0.0 to 1.0.

Rules you must follow:
- Use ONLY dish names from the supplied vocabulary. If you see a food that is \
not in the vocabulary, omit it rather than substituting the closest name.
- Estimate the weight of the food AS COOKED AND SERVED, not the dry ingredient \
weight. A typical serving on a child's plate is 40-200 g per item.
- If you cannot see the plate clearly, set "unusable_reason" and return an empty \
items list. Reporting that an image is unusable is a correct and useful answer; \
guessing is not.
- Do NOT report calories, protein, carbohydrate, or any nutritional value. Those \
are computed separately from an official food-composition table. Any nutrition \
number you produced would be discarded.
- Do NOT comment on the child, their health, or their nutritional status. The \
photograph is of a plate only.

Reference portions for scale: a standard PM POSHAN primary-stage serving is \
about 100 g of grains, 20 g of pulses and 50 g of vegetables in raw weight, \
which cooks to roughly 150 g rice, 120 g dal and 75 g vegetable on the plate.

Return JSON only, matching the supplied schema.
"""


def vocabulary_block() -> str:
    """The closed dish list, with both names, as the model sees it."""
    lines = []
    for dish in DISHES_BY_CODE.values():
        aliases = ", ".join(dish.aliases[:4])
        lines.append(
            f'  - "{dish.code}" = {dish.name_en} / {dish.name_hi}  (also called: {aliases})'
        )
    return "\n".join(lines)


def vision_user_prompt(meal_type: str, prescribed: list[str] | None = None) -> str:
    parts = [
        f"Meal type: {meal_type}.",
        "",
        "Dish vocabulary (use these exact codes in food_name):",
        vocabulary_block(),
    ]
    if prescribed:
        known = [c for c in prescribed if c in DISHES_BY_CODE]
        if known:
            parts += [
                "",
                "Today's prescribed menu at this centre is: " + ", ".join(known) + ".",
                # Stated as context, with an explicit instruction not to let it
                # bias the answer. The whole point of the compliance feature is
                # to catch days where the served plate differs from the menu, so
                # a model that reports the menu back to us would defeat it.
                "Report only what you can actually SEE on the plate. Do not add a "
                "prescribed item you cannot see, and do not omit an item you can "
                "see just because it is not on the menu. Detecting a mismatch is "
                "the purpose of this task.",
            ]
    parts += ["", "Analyse the attached photograph and return JSON only."]
    return "\n".join(parts)


#: Second pass (Section 6.1). Runs on the vision output as text -- no image, no
#: nutrition -- to sanity-check the estimates. Kept deliberately narrow: it may
#: lower confidence and add notes, never invent or reweight items.
ANOMALY_SYSTEM_PROMPT = """\
You are reviewing the output of a food-recognition model for a child-nutrition \
monitoring programme.

You will be given a list of detected dishes with estimated cooked weights in \
grams. Assess whether the estimates are internally plausible for a single \
child's meal plate, and flag anything odd.

Consider: portions far outside 40-200 g per item; a total plate weight that is \
implausible for one child; duplicate dishes; a dish whose weight is impossible \
given the others.

You MUST NOT:
- add dishes that were not detected, or remove dishes that were;
- change any detected_grams value;
- estimate calories or any nutritional value;
- comment on the child or their health.

Return JSON only: {"notes": [string], "suspect_items": [dish_code], \
"overall_plausible": boolean}.
"""
