# Golden set

**This directory is intentionally empty of data.**

Section 15 of the master prompt states plainly that no labelled dataset exists
for tribal-Rajasthan dishes, and that one must be built during the pilot rather
than assumed beforehand. Section 6.5 sets the accuracy targets that will be
measured against it.

Until photographs are labelled here, `python -m app.eval` reports
`n=0, unvalidated` for every metric. It will not emit an accuracy number, and it
cannot be made to.

## Adding labels

1. Put photographs in `images/`.
2. Label them: `python -m app.eval.label images/plate_001.jpg`
3. Re-run `python -m app.eval`.

## `plates.jsonl` — one plate per line

```json
{"image": "plate_001.jpg", "meal_type": "lunch",
 "items": [{"dish_code": "dal", "cooked_grams": 118.0},
           {"dish_code": "rice", "cooked_grams": 152.0}],
 "prescribed": ["dal", "rice", "sabzi", "banana"],
 "quality_flags": [], "weighed": true,
 "labelled_by": "field supervisor name", "labelled_at": "2026-09-04"}
```

`dish_code` must come from `app/nutrition/recipes.py`. A label using any other
vocabulary is rejected at load, because it would be compared against something
the pipeline can never produce.

`weighed` matters. Section 6.5's portion target (MAE <= 25 g per item) is only
meaningful against plates weighed on a scale during the calibration session
described in Section 14 step 3. Eyeballed grams are still useful for recognition
accuracy, so the harness reports weighed and estimated subsets separately rather
than mixing them.

## `compliance_days.jsonl` — one centre-day per line

```json
{"awc_code": "RJ-BSW-GTL-001", "day": "2026-09-04",
 "prescribed": ["dal", "roti", "sabzi", "banana"],
 "should_flag": true,
 "register_note": "kitchen register shows no fruit issued"}
```

`should_flag` is what the **kitchen register** says, not what the model said.
Section 6.5 measures precision and recall by cross-checking flagged days against
the register for two weeks.

## Child privacy

Section 12 is absolute: no photograph of a child, ever. These are photographs of
plates. Any image here showing a child's face must be deleted, not cropped.
