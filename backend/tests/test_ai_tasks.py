"""Background inference against a real database.

The property under test is Section 7's: capture must survive inference failing.
Every failure mode below has to leave the photograph intact and the row
identifiable for reprocessing -- never lost, and never stuck indistinguishably
on 'pending'.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, select

from app.ai import client, pipeline, tasks
from app.config import get_settings
from app.db.models import PlateCapture
from app.db.session import admin_session
from app.storage import supabase_storage as storage


@pytest.fixture
async def capture(fixtures) -> uuid.UUID:
    """One pending capture, exactly as POST /captures leaves it."""
    child = fixtures["children"]["PT-A1-0001"]
    capture_id = uuid.uuid4()
    async with admin_session() as session:
        async with session.begin():
            await session.execute(
                insert(PlateCapture),
                [
                    dict(
                        id=capture_id,
                        beneficiary_id=child["id"],
                        awc_code="TEST-A1",
                        district="Banswara",
                        photo_url="TEST-A1/x/y.jpg",
                        meal_type="lunch",
                        captured_at=datetime.now(UTC),
                        sync_status="pending",
                    )
                ],
            )
    return capture_id


async def _row(capture_id: uuid.UUID) -> PlateCapture:
    async with admin_session() as session:
        return (
            await session.execute(select(PlateCapture).where(PlateCapture.id == capture_id))
        ).scalar_one()


@pytest.fixture(autouse=True)
def stub_photo_fetch(monkeypatch):
    async def _fetch(path: str) -> bytes:
        return b"a-deterministic-plate-photo"

    monkeypatch.setattr(tasks, "_fetch_photo", _fetch)


# --------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------


async def test_a_processed_capture_is_marked_synced_with_nutrition(capture) -> None:
    assert await tasks.process_capture(capture) == "synced"
    row = await _row(capture)
    assert row.sync_status == "synced"
    assert row.ai_calories and row.ai_calories > 0
    assert row.ai_protein_g is not None and row.ai_carbs_g is not None
    assert row.ai_model_version
    assert row.ai_error is None


async def test_the_stored_payload_is_auditable(capture) -> None:
    """A district officer's dashboard, and any later review, both need to see
    what was detected and how confident the model was -- not just a number."""
    await tasks.process_capture(capture)
    payload = (await _row(capture)).ai_food_items
    assert "items" in payload and payload["items"]
    for item in payload["items"]:
        assert "cooked_grams" in item and "confidence" in item and "costed" in item
    assert "energy_kcal_sd" in payload, "uncertainty must travel with the estimate"
    assert payload["is_mock"] is True, "mock output must stay identifiable"
    assert payload["uncalibrated"] is True


async def test_the_model_version_is_recorded_for_the_audit_trail(capture) -> None:
    """Section 6.5: every estimate must be attributable to what produced it."""
    await tasks.process_capture(capture)
    assert (await _row(capture)).ai_model_version == client.version_tag("mock/deterministic")


# --------------------------------------------------------------------------
# Failing safely -- Section 7
# --------------------------------------------------------------------------


async def test_a_provider_outage_marks_failed_and_keeps_the_photo(capture, monkeypatch) -> None:
    async def _down(**_):
        raise client.AIUnavailable("429 rate limit exceeded")

    monkeypatch.setattr(client, "complete_vision", _down)
    assert await tasks.process_capture(capture) == "failed"
    row = await _row(capture)
    assert row.sync_status == "failed"
    assert "rate limit" in row.ai_error
    assert row.photo_url, "the evidence must survive the failure"
    assert row.ai_calories is None


async def test_an_unreadable_photo_marks_failed_rather_than_raising(capture, monkeypatch) -> None:
    async def _boom(path: str) -> bytes:
        raise storage.StorageError("404 from storage")

    monkeypatch.setattr(tasks, "_fetch_photo", _boom)
    assert await tasks.process_capture(capture) == "failed"
    assert "photo unavailable" in (await _row(capture)).ai_error


async def test_an_unexpected_error_never_escapes_the_task(capture, monkeypatch) -> None:
    """A background task that raises leaves the row on 'pending' forever, which
    is indistinguishable from one nothing has picked up yet."""

    async def _explode(**_):
        raise RuntimeError("something entirely unexpected")

    monkeypatch.setattr(pipeline, "analyse_plate", _explode)
    assert await tasks.process_capture(capture) == "failed"
    assert "RuntimeError" in (await _row(capture)).ai_error


async def test_a_failed_capture_can_be_reprocessed_successfully(capture, monkeypatch) -> None:
    """Free-tier rate limits are routine, not exceptional. Without a retry path
    one busy afternoon would strand a day's evidence permanently."""
    real = client.complete_vision
    calls = {"n": 0}

    async def _rate_limited_once(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise client.AIUnavailable("429")
        return await real(**kwargs)

    # A counter rather than monkeypatch.undo(): undo() would also revert the
    # autouse photo stub, and a transient-then-recovering provider is a truer
    # model of a free-tier rate limit than a hard swap anyway.
    monkeypatch.setattr(client, "complete_vision", _rate_limited_once)
    assert await tasks.process_capture(capture) == "failed"
    assert await tasks.process_capture(capture) == "synced"
    row = await _row(capture)
    assert row.ai_error is None and row.ai_calories > 0


async def test_a_vanished_capture_is_handled_quietly(fixtures) -> None:
    assert await tasks.process_capture(uuid.uuid4()) == "failed"


async def test_disabling_ai_leaves_captures_pending(capture, monkeypatch) -> None:
    """The Section 7 guarantee, as a switch: capture never depends on inference."""
    monkeypatch.setattr(get_settings(), "ai_enabled", False)
    assert await tasks.process_capture(capture) == "pending"
    row = await _row(capture)
    assert row.sync_status == "pending" and row.ai_calories is None


async def test_processing_is_idempotent(capture) -> None:
    """Reprocessing a synced capture must not corrupt or duplicate anything."""
    await tasks.process_capture(capture)
    first = await _row(capture)
    await tasks.process_capture(capture)
    second = await _row(capture)
    assert first.ai_calories == second.ai_calories
    assert first.ai_food_items == second.ai_food_items
