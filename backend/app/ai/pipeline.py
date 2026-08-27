"""The Section 6.1 pipeline, end to end.

    plate photo
      -> Gemini vision call            -> dish list + estimated COOKED grams
      -> validate against the closed PM POSHAN vocabulary
      -> recipe + yield conversion     -> raw ingredient grams
      -> IFCT 2017 lookup by code      -> energy / protein / carbohydrate
      -> Groq structured pass          -> plausibility notes (advisory only)

The division of labour is Section 6.3's, and it is deliberate at every step:
the model estimates *portions*, which is genuinely hard and genuinely useful;
arithmetic does the *nutrition*, which is a lookup table. The model is never
asked for a calorie figure, and if it volunteered one it would be discarded.

Everything after the vision call is deterministic. Given the same
`VisionResult`, this module produces the same nutrition every time -- which is
what makes an estimate auditable rather than merely produced.

Failure is never fatal (Section 7). A rate limit, an outage, an unparseable
reply, an unusable photograph: each produces a `PipelineResult` with `ok=False`
and a reason, so the caller can leave the capture queued for reprocessing. The
photograph is already stored before any of this runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.ai import client, prompts
from app.ai.schema import PLATE_QUALITY_FLAGS, DetectedItem, VisionResult, response_schema
from app.nutrition import compute, recipes
from app.nutrition.compute import PlateNutrition

logger = logging.getLogger("poshannetra.ai.pipeline")

#: Detections below this confidence are recorded but excluded from the totals.
#: A low-confidence item is information for a reviewer; it is not a basis for
#: telling a district officer how many calories a child received.
MIN_ITEM_CONFIDENCE = 0.35


@dataclass(frozen=True, slots=True)
class PipelineResult:
    ok: bool
    model_version: str
    #: Items that were costed, as stored in `plate_captures.ai_food_items`.
    food_items: list[dict] = field(default_factory=list)
    nutrition: PlateNutrition | None = None
    quality_flags: tuple[str, ...] = ()
    #: Detected names that are not in the PM POSHAN vocabulary.
    uncosted_items: tuple[str, ...] = ()
    #: Items dropped for low confidence, kept visible rather than silently gone.
    low_confidence_items: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    error: str | None = None
    #: True when produced by the offline mock. The eval harness refuses to
    #: report accuracy metrics for these, and it must stay visible downstream.
    is_mock: bool = False

    @property
    def energy_kcal(self) -> float | None:
        return self.nutrition.energy_kcal if self.nutrition else None

    @property
    def protein_g(self) -> float | None:
        return self.nutrition.protein_g if self.nutrition else None

    @property
    def carbs_g(self) -> float | None:
        return self.nutrition.carbohydrate_g if self.nutrition else None


def parse_vision_reply(raw: str) -> VisionResult:
    """Validate a model reply into the structured contract.

    Re-validates even though the model was handed a JSON schema, because a model
    given a schema can still return prose, a fenced block, or a dish that is not
    on the list. Section 6.2 asks for constrained output; this is where the
    constraint is actually enforced.
    """
    payload = client.extract_json(raw)
    items: list[DetectedItem] = []
    for entry in payload.get("items") or []:
        if not isinstance(entry, dict):
            continue
        try:
            items.append(DetectedItem.model_validate(entry))
        except Exception as exc:  # noqa: BLE001 - one bad item must not lose the plate
            logger.warning("discarding malformed detected item %r: %s", entry, exc)
    flags = [
        f
        for f in (payload.get("plate_quality_flags") or [])
        if isinstance(f, str) and f in PLATE_QUALITY_FLAGS
    ]
    return VisionResult(
        items=items,
        plate_quality_flags=flags,
        unusable_reason=payload.get("unusable_reason") or None,
    )


def cost_vision_result(result: VisionResult) -> tuple[PlateNutrition, dict]:
    """Turn detected dishes into nutrition. Pure and deterministic.

    Separated from the model call so the arithmetic can be tested exhaustively
    without any provider, and so an eval run can re-cost a stored vision result
    without re-spending quota.
    """
    plate: list[tuple[recipes.Dish, float]] = []
    food_items: list[dict] = []
    uncosted: list[str] = []
    low_confidence: list[str] = []

    for item in result.items:
        matched = recipes.match_or_none(item.food_name)
        if matched is None:
            uncosted.append(item.food_name)
            food_items.append(
                {
                    "detected_name": item.food_name,
                    "dish_code": None,
                    "cooked_grams": item.detected_grams,
                    "confidence": item.confidence,
                    "costed": False,
                    "reason": "not in PM POSHAN vocabulary",
                }
            )
            continue

        dish, score = matched
        costed = item.confidence >= MIN_ITEM_CONFIDENCE
        if costed:
            plate.append((dish, item.detected_grams))
        else:
            low_confidence.append(dish.code)

        food_items.append(
            {
                "detected_name": item.food_name,
                "dish_code": dish.code,
                "dish_name_en": dish.name_en,
                "dish_name_hi": dish.name_hi,
                "cooked_grams": item.detected_grams,
                "confidence": item.confidence,
                "match_score": round(score, 1),
                "count": item.count,
                "costed": costed,
                "reason": None if costed else "confidence below threshold",
            }
        )

    nutrition = compute.for_plate(plate, uncosted=uncosted)
    return nutrition, {
        "food_items": food_items,
        "uncosted": tuple(uncosted),
        "low_confidence": tuple(low_confidence),
    }


async def analyse_plate(
    *,
    image_bytes: bytes,
    content_type: str = "image/jpeg",
    meal_type: str = "lunch",
    prescribed: list[str] | None = None,
    run_anomaly_pass: bool = True,
) -> PipelineResult:
    """Full pipeline for one plate photograph. Never raises."""
    model_version = client.version_tag(
        client.MOCK_MODEL if client.provider() == "mock" else client.vision_model()
    )
    is_mock = client.provider() == "mock"

    try:
        reply = await client.complete_vision(
            image_bytes=image_bytes,
            content_type=content_type,
            system=prompts.VISION_SYSTEM_PROMPT,
            user=prompts.vision_user_prompt(meal_type, prescribed),
            schema=response_schema(recipes.vocabulary()),
        )
    except client.AIUnavailable as exc:
        return PipelineResult(
            ok=False, model_version=model_version, error=str(exc), is_mock=is_mock
        )

    try:
        vision = parse_vision_reply(reply.content)
    except client.AIResponseInvalid as exc:
        return PipelineResult(
            ok=False, model_version=reply.version_tag, error=str(exc), is_mock=is_mock
        )

    if vision.unusable_reason:
        # A model that says "I cannot see the plate" is giving a correct and
        # useful answer. Treat it as a real outcome, not an error to retry
        # forever -- reprocessing a dark photograph will not make it lighter.
        return PipelineResult(
            ok=False,
            model_version=reply.version_tag,
            quality_flags=tuple(vision.plate_quality_flags),
            error=f"image unusable: {vision.unusable_reason}",
            is_mock=is_mock,
        )

    nutrition, extras = cost_vision_result(vision)

    notes: list[str] = list(nutrition.warnings)
    if run_anomaly_pass and vision.items:
        notes.extend(await _anomaly_notes(vision))

    return PipelineResult(
        ok=True,
        model_version=reply.version_tag,
        food_items=extras["food_items"],
        nutrition=nutrition,
        quality_flags=tuple(vision.plate_quality_flags),
        uncosted_items=extras["uncosted"],
        low_confidence_items=extras["low_confidence"],
        notes=tuple(notes),
        is_mock=is_mock,
    )


async def _anomaly_notes(vision: VisionResult) -> list[str]:
    """Section 6.1's structured second pass. Advisory only.

    It may add notes. It cannot change a gram estimate, add or remove an item,
    or touch the nutrition -- those are already computed by then, from a
    lookup table. A failure here is logged and dropped, because a plate with no
    plausibility note is still a perfectly good plate.
    """
    summary = "; ".join(
        f"{i.food_name} detected_grams={i.detected_grams} confidence={i.confidence}"
        for i in vision.items
    )
    try:
        reply = await client.complete_text(
            system=prompts.ANOMALY_SYSTEM_PROMPT, user=f"Detected items: {summary}"
        )
        payload = client.extract_json(reply.content)
    except (client.AIUnavailable, client.AIResponseInvalid) as exc:
        logger.info("anomaly pass unavailable, continuing without it: %s", exc)
        return []
    return [str(n) for n in (payload.get("notes") or []) if str(n).strip()]
