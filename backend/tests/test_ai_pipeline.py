"""The AI pipeline: parsing, validation, costing, and failing safely.

Everything here runs on the deterministic offline provider or on hand-written
replies. No test in this suite touches a network or spends free-tier quota --
Section 4's constraint applies to CI as much as to production, and a suite that
depends on a rate-limited endpoint fails for reasons unrelated to the code.
"""

from __future__ import annotations

import json

import pytest

from app.ai import client, pipeline, prompts
from app.ai.schema import DetectedItem, VisionResult, response_schema
from app.nutrition import recipes

# --------------------------------------------------------------------------
# Parsing what a model actually returns
# --------------------------------------------------------------------------


def test_parses_a_clean_json_reply() -> None:
    raw = json.dumps(
        {
            "items": [{"food_name": "dal", "detected_grams": 120, "confidence": 0.9}],
            "plate_quality_flags": ["watery_appearance"],
        }
    )
    result = pipeline.parse_vision_reply(raw)
    assert result.items[0].food_name == "dal"
    assert result.plate_quality_flags == ["watery_appearance"]


def test_parses_a_fenced_code_block() -> None:
    """Models asked for JSON return fenced blocks constantly."""
    raw = '```json\n{"items": [], "plate_quality_flags": []}\n```'
    assert pipeline.parse_vision_reply(raw).items == []


def test_parses_json_buried_after_prose() -> None:
    raw = 'Here is my analysis:\n{"items": [], "plate_quality_flags": []}\nHope that helps!'
    assert pipeline.parse_vision_reply(raw).items == []


@pytest.mark.parametrize("raw", ["", "   ", "I cannot help with that.", "{broken"])
def test_unparseable_replies_raise_rather_than_returning_an_empty_plate(raw: str) -> None:
    """An empty plate and an unreadable reply are different facts. Conflating
    them would record 'this child received no food' whenever the model glitched."""
    with pytest.raises(client.AIResponseInvalid):
        pipeline.parse_vision_reply(raw)


def test_one_malformed_item_does_not_lose_the_whole_plate() -> None:
    raw = json.dumps(
        {
            "items": [
                {"food_name": "dal", "detected_grams": 120, "confidence": 0.9},
                {"food_name": "rice"},  # missing fields
                {"food_name": "roti", "detected_grams": -5, "confidence": 0.8},  # invalid
                {"food_name": "banana", "detected_grams": 100, "confidence": 0.8},
            ],
            "plate_quality_flags": [],
        }
    )
    result = pipeline.parse_vision_reply(raw)
    assert [i.food_name for i in result.items] == ["dal", "banana"]


def test_unknown_quality_flags_are_discarded() -> None:
    """Free-text flags cannot be aggregated into a district trend, so only the
    closed list survives."""
    raw = json.dumps(
        {
            "items": [],
            "plate_quality_flags": ["watery_appearance", "the_chef_seemed_sad"],
        }
    )
    assert pipeline.parse_vision_reply(raw).plate_quality_flags == ["watery_appearance"]


# --------------------------------------------------------------------------
# Costing
# --------------------------------------------------------------------------


def test_costing_is_deterministic_given_a_vision_result() -> None:
    """Everything after the model call is arithmetic, so an estimate can be
    re-derived and audited without re-running inference."""
    vision = VisionResult(
        items=[
            DetectedItem(food_name="rice", detected_grams=150, confidence=0.9),
            DetectedItem(food_name="dal", detected_grams=120, confidence=0.85),
        ]
    )
    first, _ = pipeline.cost_vision_result(vision)
    second, _ = pipeline.cost_vision_result(vision)
    assert first == second
    assert first.energy_kcal == pytest.approx(300.8, abs=1.0)


def test_out_of_vocabulary_items_are_reported_not_costed() -> None:
    vision = VisionResult(
        items=[
            DetectedItem(food_name="dal", detected_grams=120, confidence=0.9),
            DetectedItem(food_name="pizza", detected_grams=200, confidence=0.95),
        ]
    )
    nutrition, extras = pipeline.cost_vision_result(vision)
    assert extras["uncosted"] == ("pizza",)
    assert nutrition.energy_kcal == pytest.approx(94.1, abs=1.0)
    entry = next(i for i in extras["food_items"] if i["detected_name"] == "pizza")
    assert entry["costed"] is False
    assert entry["dish_code"] is None


def test_low_confidence_items_are_excluded_but_stay_visible() -> None:
    """A low-confidence detection is information for a reviewer; it is not a
    basis for telling an officer how many calories a child received."""
    vision = VisionResult(
        items=[
            DetectedItem(food_name="dal", detected_grams=120, confidence=0.9),
            DetectedItem(food_name="rice", detected_grams=150, confidence=0.10),
        ]
    )
    nutrition, extras = pipeline.cost_vision_result(vision)
    assert extras["low_confidence"] == ("rice",)
    assert nutrition.energy_kcal == pytest.approx(94.1, abs=1.0)
    rice = next(i for i in extras["food_items"] if i["dish_code"] == "rice")
    assert rice["costed"] is False and rice["cooked_grams"] == 150


def test_an_alias_is_resolved_and_the_match_score_recorded() -> None:
    vision = VisionResult(
        items=[DetectedItem(food_name="chawal", detected_grams=150, confidence=0.9)]
    )
    _, extras = pipeline.cost_vision_result(vision)
    item = extras["food_items"][0]
    assert item["dish_code"] == "rice" and item["match_score"] == 100.0


# --------------------------------------------------------------------------
# End to end on the offline provider
# --------------------------------------------------------------------------


async def test_analyse_plate_produces_a_costed_result() -> None:
    result = await pipeline.analyse_plate(
        image_bytes=b"a-plate-photo", meal_type="lunch", prescribed=["dal", "rice"]
    )
    assert result.ok and result.is_mock
    assert result.energy_kcal is not None and result.energy_kcal > 0
    assert result.model_version


async def test_the_same_image_always_yields_the_same_result() -> None:
    """Reproducibility is what makes the eval harness meaningful."""
    a = await pipeline.analyse_plate(image_bytes=b"same-photo", run_anomaly_pass=False)
    b = await pipeline.analyse_plate(image_bytes=b"same-photo", run_anomaly_pass=False)
    assert a.energy_kcal == b.energy_kcal
    assert a.food_items == b.food_items


async def test_mock_results_are_labelled_as_mock() -> None:
    """It must be impossible to present mock output as a real measurement."""
    result = await pipeline.analyse_plate(image_bytes=b"x")
    assert result.is_mock is True


async def test_a_provider_outage_fails_softly(monkeypatch) -> None:
    """Section 7: a rate limit or an outage must never lose a capture."""

    async def _down(**_):
        raise client.AIUnavailable("429 rate limit exceeded")

    monkeypatch.setattr(client, "complete_vision", _down)
    result = await pipeline.analyse_plate(image_bytes=b"x")
    assert result.ok is False
    assert "rate limit" in result.error
    assert result.nutrition is None


async def test_an_unusable_photograph_is_a_result_not_an_error(monkeypatch) -> None:
    """A model that says 'I cannot see the plate' is answering correctly.
    Retrying a dark photograph will not make it lighter."""

    async def _unusable(**_):
        return client.ModelReply(
            json.dumps(
                {
                    "items": [],
                    "plate_quality_flags": ["image_too_dark"],
                    "unusable_reason": "the image is too dark to assess",
                }
            ),
            "mock",
            "mock",
            "mock+pipeline1",
        )

    monkeypatch.setattr(client, "complete_vision", _unusable)
    result = await pipeline.analyse_plate(image_bytes=b"x")
    assert result.ok is False
    assert "too dark" in result.error
    assert result.quality_flags == ("image_too_dark",)


async def test_a_garbled_reply_fails_softly(monkeypatch) -> None:
    async def _garbage(**_):
        return client.ModelReply("I'm sorry, I can't do that", "m", "mock", "v")

    monkeypatch.setattr(client, "complete_vision", _garbage)
    result = await pipeline.analyse_plate(image_bytes=b"x")
    assert result.ok is False and result.nutrition is None


async def test_the_anomaly_pass_cannot_change_the_numbers(monkeypatch) -> None:
    """Section 6.1's second pass is advisory. If it could alter grams or
    nutrition, a language model would be back in the arithmetic path."""

    async def _meddling(**_):
        return client.ModelReply(
            json.dumps(
                {
                    "notes": ["portion looks large"],
                    "suspect_items": ["rice"],
                    "overall_plausible": False,
                }
            ),
            "m",
            "mock",
            "v",
        )

    without = await pipeline.analyse_plate(image_bytes=b"fixed", run_anomaly_pass=False)
    monkeypatch.setattr(client, "complete_text", _meddling)
    with_pass = await pipeline.analyse_plate(image_bytes=b"fixed", run_anomaly_pass=True)
    assert with_pass.energy_kcal == without.energy_kcal
    assert with_pass.food_items == without.food_items
    assert "portion looks large" in with_pass.notes


async def test_a_failing_anomaly_pass_does_not_lose_the_plate(monkeypatch) -> None:
    async def _down(**_):
        raise client.AIUnavailable("groq down")

    monkeypatch.setattr(client, "complete_text", _down)
    result = await pipeline.analyse_plate(image_bytes=b"x", run_anomaly_pass=True)
    assert result.ok is True and result.energy_kcal is not None


# --------------------------------------------------------------------------
# Prompt and schema contract
# --------------------------------------------------------------------------


def test_the_schema_constrains_food_name_to_the_vocabulary() -> None:
    """Section 6.2: telling the model the closed list beats correcting it after."""
    schema = response_schema(recipes.vocabulary())
    enum = schema["properties"]["items"]["items"]["properties"]["food_name"]["enum"]
    assert set(enum) == set(recipes.vocabulary())


def test_the_prompt_forbids_the_model_from_producing_nutrition() -> None:
    """Section 6.3's line, enforced in the prompt as well as in the code path."""
    system = prompts.VISION_SYSTEM_PROMPT.lower()
    assert "do not report calories" in system
    assert "cooked" in system, "the model must be told to estimate cooked weight"


def test_the_prompt_never_mentions_the_child() -> None:
    """Section 12: the photograph is of a plate. Section 11: no beneficiary PII
    reaches a third-party model. Both hold by construction -- the prompt is
    built from the dish vocabulary and meal type only."""
    text = prompts.VISION_SYSTEM_PROMPT + prompts.vision_user_prompt("lunch", ["dal", "roti"])
    lowered = text.lower()
    for forbidden in ("beneficiary", "date of birth", "child's name", "awc_code"):
        assert forbidden not in lowered
    assert "do not comment on the child" in lowered


def test_the_prescribed_menu_is_given_with_an_anti_bias_instruction() -> None:
    """Telling the model the menu risks it reporting the menu back, which would
    defeat the compliance feature entirely."""
    text = prompts.vision_user_prompt("lunch", ["dal", "roti", "sabzi"])
    assert "only what you can actually SEE" in text
    assert "Detecting a mismatch is the purpose" in text


def test_the_vocabulary_block_carries_both_languages() -> None:
    block = prompts.vocabulary_block()
    assert "दाल" in block and "Dal (lentils)" in block


# --------------------------------------------------------------------------
# JSON extraction helper
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        '```\n{"a": 1}\n```',
        'prose before {"a": 1} prose after',
    ],
)
def test_json_extraction_tolerates_common_model_formatting(raw: str) -> None:
    assert client.extract_json(raw) == {"a": 1}


@pytest.mark.parametrize("raw", ["", "no json here", "{unclosed"])
def test_json_extraction_refuses_nonsense(raw: str) -> None:
    with pytest.raises(client.AIResponseInvalid):
        client.extract_json(raw)


def test_default_provider_is_the_offline_mock() -> None:
    """Nothing should spend free-tier quota by accident."""
    assert client.provider() == "mock"
