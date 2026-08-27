"""The structured contract between the vision model and the rest of the system.

Section 6.2 requires structured output rather than free text, and constrains
`food_name` to a known vocabulary. Both are enforced here rather than hoped for:
the JSON schema is handed to the model as a response format, and anything that
comes back is still re-validated, because a model that is asked for JSON can
still return prose, a fenced code block, or a plausible dish that is not on the
list.

`detected_grams` is the *cooked* weight on the plate. That is the one quantity
the model is genuinely good at estimating and the one thing we want from it.
It is never asked for calories -- see app/nutrition/compute.py.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: Quality observations the model may report. A closed list, because free-text
#: flags cannot be aggregated into the district-level trend Section 9.2 needs.
#: Drawn from the Gadchiroli precedent in Section 1: the failures that are
#: invisible in a paper register but visible in a photograph.
PLATE_QUALITY_FLAGS = (
    "watery_appearance",
    "portion_below_prescribed",
    "portion_above_prescribed",
    "item_appears_undercooked",
    "fruit_unripe_or_overripe",
    "plate_mostly_empty",
    "image_too_dark",
    "image_blurred",
    "plate_not_visible",
)


class DetectedItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    food_name: str = Field(description="Dish name from the supplied vocabulary")
    detected_grams: float = Field(
        ge=0, le=2000, description="Estimated COOKED weight on the plate, in grams"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    count: int | None = Field(
        default=None, description="Countable items only, e.g. number of rotis"
    )


class VisionResult(BaseModel):
    """Exactly what the vision model is asked to return."""

    model_config = ConfigDict(extra="ignore")

    items: list[DetectedItem] = Field(default_factory=list)
    plate_quality_flags: list[str] = Field(default_factory=list)
    #: Set when the image cannot be assessed at all. A model that says so is far
    #: more useful than one that invents a plate, so it is given the option.
    unusable_reason: str | None = None


#: JSON Schema handed to the provider as a response format. Written out rather
#: than generated from the Pydantic model so the vocabulary enum can be injected
#: at call time -- the model should be told the valid dish names, not left to
#: guess and be corrected afterwards.
def response_schema(vocabulary: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "food_name": {"type": "string", "enum": list(vocabulary)},
                        "detected_grams": {"type": "number"},
                        "confidence": {"type": "number"},
                        "count": {"type": ["integer", "null"]},
                    },
                    "required": ["food_name", "detected_grams", "confidence"],
                },
            },
            "plate_quality_flags": {
                "type": "array",
                "items": {"type": "string", "enum": list(PLATE_QUALITY_FLAGS)},
            },
            "unusable_reason": {"type": ["string", "null"]},
        },
        "required": ["items", "plate_quality_flags"],
    }
