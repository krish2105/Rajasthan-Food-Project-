"""Interactive labelling tool for the golden set.

    python -m app.eval.label app/eval/golden/images/plate_001.jpg

Built for a field supervisor during pilot week 1, not for an engineer: it offers
the closed PM POSHAN dish list by number, asks for grams, and asks explicitly
whether the plate was weighed -- because Section 6.5's portion target is only
meaningful for weighed plates and the harness reports the two subsets apart.

It writes JSONL that a person can read in a diff, and refuses a dish code that
is not in the vocabulary.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from app.eval import golden
from app.nutrition.recipes import DISHES


def prompt_items() -> list[golden.LabelledItem]:
    print("\nDishes on the plate (blank line when done):")
    for index, dish in enumerate(DISHES, 1):
        print(f"  {index:2d}. {dish.code:9s} {dish.name_en} / {dish.name_hi}")

    items: list[golden.LabelledItem] = []
    while True:
        raw = input("\n  dish number (or blank to finish): ").strip()
        if not raw:
            break
        try:
            dish = DISHES[int(raw) - 1]
        except (ValueError, IndexError):
            print("  -- not a valid number")
            continue
        grams_raw = input(f"  cooked grams of {dish.name_en}: ").strip()
        try:
            grams = float(grams_raw)
        except ValueError:
            print("  -- not a number, skipping")
            continue
        if grams <= 0:
            print("  -- must be positive, skipping")
            continue
        items.append(golden.LabelledItem(dish.code, grams))
        print(f"  recorded: {dish.code} {grams} g")
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description="Label one plate photograph")
    parser.add_argument("image", help="path to the photograph")
    parser.add_argument("--meal-type", default="lunch", choices=["breakfast", "lunch", "thr"])
    parser.add_argument("--by", default="", help="who is labelling")
    args = parser.parse_args()

    path = Path(args.image)
    if not path.exists():
        raise SystemExit(f"no such image: {path}")

    print(f"Labelling {path.name}")
    print("Reminder (Section 12): plates only. If a child is visible in this")
    print("photograph, delete it rather than cropping it, and do not label it.")

    items = prompt_items()
    if not items:
        raise SystemExit("no dishes recorded; nothing written")

    weighed = input("\n  were these grams WEIGHED on a scale? [y/N]: ").strip().lower() == "y"
    prescribed = [
        c.strip()
        for c in input("  prescribed menu codes, comma-separated: ").split(",")
        if c.strip()
    ]
    notes = input("  notes (optional): ").strip()

    try:
        images_dir = path.resolve().relative_to(golden.IMAGES_DIR.resolve())
        stored = str(images_dir)
    except ValueError:
        stored = str(path.resolve())

    golden.append_plate(
        golden.LabelledPlate(
            image=stored,
            meal_type=args.meal_type,
            items=tuple(items),
            prescribed=tuple(prescribed),
            labelled_by=args.by,
            labelled_at=date.today().isoformat(),
            weighed=weighed,
            notes=notes,
        )
    )
    print(f"\n  written to {golden.PLATES_FILE}")
    print(f"  golden set now holds {len(golden.load().plates)} plate(s)")
    if not weighed:
        print("  note: recorded as NOT weighed -- excluded from the weighed-only")
        print("  portion-accuracy subset (Section 6.5).")


if __name__ == "__main__":
    main()
