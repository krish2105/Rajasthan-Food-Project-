"""Background inference for captured plates (Sections 7, 8).

Section 8 says to use FastAPI `BackgroundTasks` at MVP scale and not to reach
for Celery or Redis until pilot volume actually needs it. Section 3's reasoning
applies: a queue we do not need is a component we have to operate.

The ordering is the load-bearing part, and it comes straight from Section 7:

    photo uploaded to Storage
      -> capture row written, sync_status='pending'   <- the request returns HERE
      -> [response sent to the field worker]
      -> background: inference, then row updated

A worker never waits for a model. A rate limit, an outage or an unparseable
reply leaves the row 'failed' with the reason recorded and the photograph
intact, ready for reprocessing. Losing a plate because a free-tier quota was
exhausted would be the worst possible failure for a system whose entire premise
is that the photograph is the evidence.

Why this uses `admin_session`
-----------------------------
A background task runs after the request has ended, so it has no request-scoped
session. More fundamentally, migration 0002 grants the `authenticated` role no
UPDATE on any table -- deliberately, so that records about children cannot be
edited in place through the API. The pipeline is a server-side process writing
back to a row it was handed, not a user acting on someone's data, so it uses the
owner connection. It only ever touches the single capture id it was given.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.ai import pipeline
from app.config import get_settings
from app.db.models import MenuCompliance, PlateCapture
from app.db.session import admin_session
from app.storage import supabase_storage as storage

logger = logging.getLogger("poshannetra.ai.tasks")


async def process_capture(capture_id: uuid.UUID) -> str:
    """Run the pipeline for one capture and write the result back.

    Returns the resulting sync_status. Never raises: a background task that
    raises produces an unhandled-exception log and a row stuck on 'pending'
    forever, which is indistinguishable from one that has not been picked up.
    """
    settings = get_settings()
    if not settings.ai_enabled:
        logger.info("AI disabled; capture %s left pending", capture_id)
        return "pending"

    try:
        async with admin_session() as session:
            capture = (
                await session.execute(select(PlateCapture).where(PlateCapture.id == capture_id))
            ).scalar_one_or_none()
            if capture is None:
                logger.warning("capture %s vanished before processing", capture_id)
                return "failed"
            photo_path = capture.photo_url
            meal_type = capture.meal_type
            awc_code = capture.awc_code
            captured_on = capture.captured_at.date()

        prescribed = await _prescribed_for(awc_code, captured_on)
        image_bytes = await _fetch_photo(photo_path)

        result = await pipeline.analyse_plate(
            image_bytes=image_bytes,
            meal_type=meal_type,
            prescribed=prescribed,
        )
        return await _write_back(capture_id, result)

    except storage.StorageError as exc:
        return await _mark_failed(capture_id, f"photo unavailable: {exc}")
    except Exception as exc:  # noqa: BLE001 - a background task must not escape
        logger.exception("capture %s failed unexpectedly", capture_id)
        return await _mark_failed(capture_id, f"{type(exc).__name__}: {exc}")


async def _fetch_photo(path: str) -> bytes:
    """Read the stored photo back for inference.

    Uses the service key rather than a caller token: there is no caller by this
    point. Section 11's guarantee is unaffected -- only the plate image leaves
    our infrastructure, and no beneficiary field is ever included in a prompt.
    """
    import httpx

    settings = get_settings()
    if not settings.storage_configured:
        raise storage.StorageNotConfigured(
            "SUPABASE_URL / SUPABASE_SERVICE_KEY are not set; see docs/phase1-supabase-setup.md"
        )
    base = settings.supabase_url.rstrip("/")
    bucket = settings.supabase_storage_bucket
    headers = {
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "apikey": settings.supabase_service_key,
    }
    async with httpx.AsyncClient(timeout=60) as http:
        response = await http.get(f"{base}/storage/v1/object/{bucket}/{path}", headers=headers)
    if response.status_code >= 400:
        raise storage.StorageError(f"could not read {path} ({response.status_code})")
    return response.content


async def _prescribed_for(awc_code: str, day) -> list[str]:
    """Today's menu at this centre, if it is recorded.

    Passed to the vision prompt as context, with an explicit instruction not to
    let it bias the answer -- the compliance feature exists to catch days where
    the plate differs from the menu, so a model that echoed the menu back would
    defeat the whole point.
    """
    async with admin_session() as session:
        row = (
            await session.execute(
                select(MenuCompliance.prescribed_items).where(
                    MenuCompliance.awc_code == awc_code, MenuCompliance.date == day
                )
            )
        ).scalar_one_or_none()
    return [str(c) for c in row] if row else []


async def _write_back(capture_id: uuid.UUID, result: pipeline.PipelineResult) -> str:
    if not result.ok:
        return await _mark_failed(
            capture_id, result.error or "unknown pipeline error", model_version=result.model_version
        )

    nutrition = result.nutrition
    assert nutrition is not None
    payload = {
        "items": result.food_items,
        "quality_flags": list(result.quality_flags),
        "uncosted_items": list(result.uncosted_items),
        "low_confidence_items": list(result.low_confidence_items),
        "notes": list(result.notes),
        # Composition uncertainty travels with the estimate so a dashboard can
        # show a range rather than false precision (Section 15).
        "energy_kcal_sd": nutrition.energy_kcal_sd,
        "protein_g_sd": nutrition.protein_g_sd,
        "uncalibrated": nutrition.any_uncalibrated,
        "is_mock": result.is_mock,
    }

    async with admin_session() as session:
        async with session.begin():
            capture = (
                await session.execute(select(PlateCapture).where(PlateCapture.id == capture_id))
            ).scalar_one_or_none()
            if capture is None:  # pragma: no cover - raced with a delete
                return "failed"
            capture.ai_food_items = payload
            capture.ai_calories = nutrition.energy_kcal
            capture.ai_protein_g = nutrition.protein_g
            capture.ai_carbs_g = nutrition.carbohydrate_g
            capture.ai_model_version = result.model_version
            capture.ai_error = None
            capture.sync_status = "synced"
    logger.info("capture %s synced: %.0f kcal", capture_id, nutrition.energy_kcal)
    return "synced"


async def _mark_failed(
    capture_id: uuid.UUID, reason: str, *, model_version: str | None = None
) -> str:
    """Record the failure against the row. The photograph is untouched."""
    try:
        async with admin_session() as session:
            async with session.begin():
                capture = (
                    await session.execute(select(PlateCapture).where(PlateCapture.id == capture_id))
                ).scalar_one_or_none()
                if capture is None:  # pragma: no cover
                    return "failed"
                capture.sync_status = "failed"
                capture.ai_error = reason[:1000]
                if model_version:
                    capture.ai_model_version = model_version
    except Exception:  # noqa: BLE001 - if even this fails, log and move on
        logger.exception("could not record failure for capture %s", capture_id)
    logger.warning("capture %s failed: %s", capture_id, reason)
    return "failed"
