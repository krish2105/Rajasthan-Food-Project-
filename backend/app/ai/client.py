"""Model routing via LiteLLM, plus a deterministic offline provider.

Section 4 chooses LiteLLM so that swapping Gemini, Groq or a future free-tier
model never touches business logic, and Section 4's zero-paid-API constraint is
absolute: every call here must land on a free tier.

Three providers
---------------
``gemini``  Vision. Gemini Flash via Google AI Studio's free tier.
``groq``    Fast structured text. The anomaly pass in Section 6.1.
``mock``    Deterministic, offline, no network.

The mock is not a testing afterthought -- it is how the pipeline is developed and
how CI runs. A test suite that depends on a live free-tier quota is a test suite
that fails for reasons unrelated to the code, and the quota is a shared resource
the pilot needs. `AI_PROVIDER=mock` is the default precisely so that nothing
accidentally spends quota.

Failure posture (Section 7)
---------------------------
Every failure here is raised as `AIUnavailable` and is expected to be caught
upstream. A rate limit or an outage must never lose a plate photograph: the
capture row is already written before inference is attempted, and a failed call
leaves it queued for reprocessing rather than discarded.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("poshannetra.ai")

#: Free-tier models as of this build. Both are swappable by environment
#: variable without touching any calling code -- the point of the abstraction.
DEFAULT_VISION_MODEL = "gemini/gemini-2.0-flash"
DEFAULT_TEXT_MODEL = "groq/llama-3.3-70b-versatile"

#: Model identifier recorded for mock runs. Derived through `version_tag` like
#: any other model so the audit trail is consistent, and distinctive enough that
#: mock output can never be mistaken for a real measurement in the database.
MOCK_MODEL = "mock/deterministic"

#: Free tiers are rate-limited, not merely slow. Retries are few and spaced,
#: because hammering a free tier is how a pilot loses access to it.
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (2.0, 8.0)
REQUEST_TIMEOUT = 60.0


class AIUnavailable(RuntimeError):
    """The model call failed. Never fatal to a capture."""


class AIResponseInvalid(ValueError):
    """The model replied, but not with usable JSON."""


@dataclass(frozen=True, slots=True)
class ModelReply:
    content: str
    model: str
    provider: str
    #: Recorded on every capture for the Section 6.5 audit trail.
    version_tag: str


def provider() -> str:
    from app.config import get_settings

    return get_settings().ai_provider


def vision_model() -> str:
    from app.config import get_settings

    return get_settings().ai_vision_model or DEFAULT_VISION_MODEL


def text_model() -> str:
    from app.config import get_settings

    return get_settings().ai_text_model or DEFAULT_TEXT_MODEL


def export_provider_keys() -> None:
    """Publish API keys into the environment for LiteLLM to pick up.

    LiteLLM reads provider credentials from the environment. Keeping them in
    Settings and exporting once at startup means the keys have exactly one
    declared home (.env), rather than being read from two places that can
    disagree. Called from the application lifespan and from the eval CLI.
    """
    from app.config import get_settings

    settings = get_settings()
    if settings.gemini_api_key:
        os.environ.setdefault("GEMINI_API_KEY", settings.gemini_api_key)
    if settings.groq_api_key:
        os.environ.setdefault("GROQ_API_KEY", settings.groq_api_key)


def extract_json(raw: str) -> dict[str, Any]:
    """Parse JSON out of a model reply.

    Models asked for JSON still return fenced blocks, or a sentence before the
    object. This tolerates those without tolerating actual nonsense: it will not
    invent structure, it just finds the object if one is there.
    """
    text = (raw or "").strip()
    if not text:
        raise AIResponseInvalid("empty model reply")

    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise AIResponseInvalid(f"reply was not valid JSON: {text[:200]!r}") from exc
    raise AIResponseInvalid(f"no JSON object in reply: {text[:200]!r}")


async def _call_litellm(*, model: str, messages: list[dict], response_format: dict | None) -> str:
    import litellm

    last: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "timeout": REQUEST_TIMEOUT,
                "temperature": 0.0,  # portion estimates should be reproducible
            }
            if response_format:
                kwargs["response_format"] = response_format
            response = await litellm.acompletion(**kwargs)
            return response.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001 - LiteLLM raises many provider types
            last = exc
            if attempt < MAX_ATTEMPTS - 1:
                delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
                logger.warning(
                    "model call failed (attempt %d/%d), retrying in %.0fs: %s",
                    attempt + 1,
                    MAX_ATTEMPTS,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
    raise AIUnavailable(f"{model} unavailable after {MAX_ATTEMPTS} attempts: {last}")


async def complete_vision(
    *, image_bytes: bytes, content_type: str, system: str, user: str, schema: dict | None
) -> ModelReply:
    """One vision call. The image goes to the provider; no beneficiary data does.

    Section 11 is explicit: only the plate photograph is sent to a third-party
    model. No name, no date of birth, no beneficiary ID, no AWC code appears in
    any prompt -- matching a photo to a child happens entirely in our own
    database. Note that `user` is built from the dish vocabulary and meal type
    only, which is why that guarantee holds by construction rather than by care.
    """
    if provider() == "mock":
        return _mock_vision(image_bytes)

    encoded = base64.b64encode(image_bytes).decode()
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{content_type};base64,{encoded}"},
                },
            ],
        },
    ]
    model = vision_model()
    content = await _call_litellm(
        model=model,
        messages=messages,
        response_format={"type": "json_object"} if schema else None,
    )
    return ModelReply(content, model, provider(), version_tag(model))


async def complete_text(*, system: str, user: str) -> ModelReply:
    if provider() == "mock":
        return _mock_text(user)
    model = text_model()
    content = await _call_litellm(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
    )
    return ModelReply(content, model, provider(), version_tag(model))


def version_tag(model: str) -> str:
    """Stored in `plate_captures.ai_model_version` for the Section 6.5 audit
    trail, so an estimate is always attributable to what produced it."""
    return f"{model}+pipeline1"


# ---------------------------------------------------------------------------
# Deterministic offline provider
# ---------------------------------------------------------------------------


def _mock_vision(image_bytes: bytes) -> ModelReply:
    """A plausible plate, derived deterministically from the image bytes.

    The same image always yields the same answer, so tests and the eval harness
    are reproducible. This is a stand-in for the wiring, not for the model: it
    can verify that the pipeline parses, validates, costs and stores a result,
    and it can verify nothing whatsoever about recognition accuracy. The eval
    harness refuses to report metrics computed under the mock provider.
    """
    from app.nutrition.recipes import DISHES

    digest = hashlib.sha256(image_bytes).digest()
    count = 2 + digest[0] % 3
    chosen: list[dict] = []
    for i in range(count):
        dish = DISHES[digest[i + 1] % len(DISHES)]
        if any(c["food_name"] == dish.code for c in chosen):
            continue
        jitter = 0.65 + (digest[i + 5] / 255.0) * 0.7
        chosen.append(
            {
                "food_name": dish.code,
                "detected_grams": round(dish.cooked_serving_g * jitter, 1),
                "confidence": round(0.62 + (digest[i + 9] / 255.0) * 0.35, 2),
            }
        )
    flags = ["watery_appearance"] if digest[20] % 5 == 0 else []
    payload = {"items": chosen, "plate_quality_flags": flags, "unusable_reason": None}
    return ModelReply(json.dumps(payload), MOCK_MODEL, "mock", version_tag(MOCK_MODEL))


def _mock_text(user: str) -> ModelReply:
    payload = {"notes": [], "suspect_items": [], "overall_plausible": True}
    if "detected_grams" in user:
        grams = [float(g) for g in re.findall(r"detected_grams=([\d.]+)", user)]
        if grams and sum(grams) > 800:
            payload = {
                "notes": [f"total plate weight {sum(grams):.0f} g is high for one child"],
                "suspect_items": [],
                "overall_plausible": False,
            }
    return ModelReply(json.dumps(payload), MOCK_MODEL, "mock", version_tag(MOCK_MODEL))
