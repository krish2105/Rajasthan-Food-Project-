"""The golden set: hand-labelled plate photographs and their ground truth.

Section 6.5 requires this harness to exist *before* the pilot, and Section 15 is
equally clear that no labelled dataset for tribal-Rajasthan dishes exists yet --
it has to be bootstrapped during pilot week 1 from ~200-300 photographs.

So the harness ships with an empty golden set and says so. It runs today,
reports `n=0, unvalidated`, and cannot be made to emit an accuracy figure it does
not have. Photographs are dropped in during the pilot and the numbers become
real. That ordering is the point: a harness built afterwards gets built to match
whatever the model already scored.

Format is JSONL -- one labelled plate per line -- because it is appended to by
hand, reviewed in a diff, and must stay legible to a field supervisor rather
than only to a program.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.nutrition.recipes import DISHES_BY_CODE

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
PLATES_FILE = GOLDEN_DIR / "plates.jsonl"
COMPLIANCE_FILE = GOLDEN_DIR / "compliance_days.jsonl"
IMAGES_DIR = GOLDEN_DIR / "images"


class GoldenSetError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LabelledItem:
    dish_code: str
    #: Weighed or carefully estimated COOKED grams on the plate.
    cooked_grams: float


@dataclass(frozen=True, slots=True)
class LabelledPlate:
    """One photograph with its ground truth."""

    image: str
    meal_type: str
    items: tuple[LabelledItem, ...]
    prescribed: tuple[str, ...] = ()
    quality_flags: tuple[str, ...] = ()
    labelled_by: str = ""
    labelled_at: str = ""
    #: True when the grams came from a scale rather than an eye. Section 6.5's
    #: portion-MAE target is only meaningful against weighed plates, so the
    #: harness reports weighed and estimated subsets separately.
    weighed: bool = False
    notes: str = ""

    @property
    def image_path(self) -> Path:
        p = Path(self.image)
        return p if p.is_absolute() else IMAGES_DIR / p

    @property
    def dish_codes(self) -> set[str]:
        return {i.dish_code for i in self.items}

    def grams_for(self, dish_code: str) -> float | None:
        for item in self.items:
            if item.dish_code == dish_code:
                return item.cooked_grams
        return None


@dataclass(frozen=True, slots=True)
class LabelledComplianceDay:
    """Ground truth for one centre-day, from the kitchen register.

    Section 6.5 measures compliance precision and recall by cross-checking
    flagged days against the actual register for two weeks. `should_flag` is
    what the register says, not what the model said.
    """

    awc_code: str
    day: str
    prescribed: tuple[str, ...]
    should_flag: bool
    images: tuple[str, ...] = ()
    register_note: str = ""


@dataclass
class GoldenSet:
    plates: list[LabelledPlate] = field(default_factory=list)
    compliance_days: list[LabelledComplianceDay] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.plates and not self.compliance_days

    @property
    def weighed_plates(self) -> list[LabelledPlate]:
        return [p for p in self.plates if p.weighed]

    def missing_images(self) -> list[str]:
        return [p.image for p in self.plates if not p.image_path.exists()]


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise GoldenSetError(f"{path.name} line {lineno}: {exc}") from exc
    return records


def load() -> GoldenSet:
    plates = []
    for raw in _read_jsonl(PLATES_FILE):
        items = []
        for item in raw.get("items", []):
            code = item["dish_code"]
            if code not in DISHES_BY_CODE:
                raise GoldenSetError(
                    f"{raw.get('image')}: dish_code {code!r} is not in the PM POSHAN "
                    f"vocabulary. Labels must use app/nutrition/recipes.py codes, "
                    f"or the metrics compare against something the pipeline can "
                    f"never produce."
                )
            items.append(LabelledItem(code, float(item["cooked_grams"])))
        plates.append(
            LabelledPlate(
                image=raw["image"],
                meal_type=raw.get("meal_type", "lunch"),
                items=tuple(items),
                prescribed=tuple(raw.get("prescribed", ())),
                quality_flags=tuple(raw.get("quality_flags", ())),
                labelled_by=raw.get("labelled_by", ""),
                labelled_at=raw.get("labelled_at", ""),
                weighed=bool(raw.get("weighed", False)),
                notes=raw.get("notes", ""),
            )
        )

    days = [
        LabelledComplianceDay(
            awc_code=raw["awc_code"],
            day=raw["day"],
            prescribed=tuple(raw["prescribed"]),
            should_flag=bool(raw["should_flag"]),
            images=tuple(raw.get("images", ())),
            register_note=raw.get("register_note", ""),
        )
        for raw in _read_jsonl(COMPLIANCE_FILE)
    ]
    return GoldenSet(plates=plates, compliance_days=days)


def append_plate(plate: LabelledPlate) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "image": plate.image,
        "meal_type": plate.meal_type,
        "items": [{"dish_code": i.dish_code, "cooked_grams": i.cooked_grams} for i in plate.items],
        "prescribed": list(plate.prescribed),
        "quality_flags": list(plate.quality_flags),
        "labelled_by": plate.labelled_by,
        "labelled_at": plate.labelled_at or date.today().isoformat(),
        "weighed": plate.weighed,
        "notes": plate.notes,
    }
    with PLATES_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
