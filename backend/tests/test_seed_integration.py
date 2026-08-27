"""The seed's write path, exercised against a real database.

`tests/test_seed.py` covers generation in isolation. This file runs the actual
`seed()` orchestration end to end, because the failure modes it catches are
different ones: a constraint the generated data violates, a foreign key wired to
the wrong column, a chunked insert that drops a chunk.

It is slower than the rest of the suite -- it writes several thousand rows -- and
that is the point. A demo dataset that has never been inserted is not a demo
dataset.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, text

from app.db.models import (
    AWC,
    Beneficiary,
    FieldWorker,
    GrowthEntry,
    MenuCompliance,
    MenuItem,
    PlateCapture,
)
from app.db.session import admin_session
from app.seed import reference
from app.seed.__main__ import seed

pytestmark = pytest.mark.usefixtures("database")


@pytest.fixture(scope="module")
def seeded(database):
    """Seed once for this module, in an event loop of its own.

    Deliberately a *sync* fixture driving `asyncio.run`. A module-scoped async
    fixture would hold an asyncpg pool across the per-test engine disposal in
    conftest, and the pool's connections would then belong to a loop that has
    since closed. Seeding in a self-contained loop and disposing the engine
    before returning leaves each test to build its own, in its own loop.
    """
    import asyncio

    async def _seed_then_release() -> None:
        from app.db.session import dispose_engine, get_engine, get_sessionmaker

        try:
            await seed(dry_run=False)
        finally:
            await dispose_engine()
            get_engine.cache_clear()
            get_sessionmaker.cache_clear()

    asyncio.run(_seed_then_release())


async def _count(model) -> int:
    async with admin_session() as session:
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_seed_writes_every_table(seeded) -> None:
    assert await _count(AWC) == len(reference.AWCS)
    assert await _count(MenuItem) == len(reference.MENU_ITEMS)
    assert await _count(FieldWorker) == len(reference.FIELD_WORKERS)
    assert await _count(Beneficiary) == sum(a["child_count"] for a in reference.AWCS)
    assert await _count(GrowthEntry) > 0
    assert await _count(PlateCapture) > 0
    assert await _count(MenuCompliance) > 0


async def test_seed_is_idempotent(seeded) -> None:
    """Running it twice must not double the data or violate a unique key."""
    before = await _count(Beneficiary)
    await seed(dry_run=False)
    assert await _count(Beneficiary) == before


async def test_every_growth_row_respects_the_d1_invariant(seeded) -> None:
    """The CHECK constraint enforces this, so a violation would have failed the
    insert -- but asserting it here documents what the seed actually produced."""
    async with admin_session() as session:
        rows = await session.execute(
            text(
                "SELECT standard_used, count(*), count(whz_score), count(baz_score) "
                "FROM growth_entries GROUP BY standard_used"
            )
        )
        by_standard = {r[0]: (r[1], r[2], r[3]) for r in rows}

    assert set(by_standard) == {"who_2006_0_60m", "who_2007_5_19y"}, (
        "the seed must exercise both WHO references, or deviation D1 goes undemonstrated"
    )
    total_2006, whz_2006, baz_2006 = by_standard["who_2006_0_60m"]
    total_2007, whz_2007, baz_2007 = by_standard["who_2007_5_19y"]
    assert whz_2006 == total_2006 and baz_2006 == 0
    assert whz_2007 == 0 and baz_2007 == total_2007


async def test_weight_for_age_is_absent_above_ten_years(seeded) -> None:
    """WHO defines no reference there, so the column must be NULL -- not zero,
    and not quietly computed from the wrong table."""
    async with admin_session() as session:
        stray = (
            await session.execute(
                text(
                    "SELECT count(*) FROM growth_entries "
                    "WHERE age_months > 120 AND waz_score IS NOT NULL"
                )
            )
        ).scalar_one()
    assert stray == 0


async def test_seeded_zscores_are_reproducible_from_stored_measurements(seeded) -> None:
    """The audit property, checked against what is actually in the database."""
    from app.growth.assess import assess
    from app.growth.lms import Sex

    async with admin_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT g.recorded_at, g.height_cm, g.weight_kg, g.haz_score,"
                    " g.classification, b.dob, b.gender"
                    " FROM growth_entries g JOIN beneficiaries b ON b.id = g.beneficiary_id"
                    " ORDER BY g.id LIMIT 150"
                )
            )
        ).all()

    assert rows
    for recorded_at, height, weight, haz, classification, dob, gender in rows:
        again = assess(
            dob=dob,
            recorded_at=recorded_at,
            sex=Sex.MALE if gender == "M" else Sex.FEMALE,
            height_cm=float(height),
            weight_kg=float(weight),
        )
        assert float(haz) == pytest.approx(again.haz, abs=0.005)
        assert classification == again.classification


async def test_no_seeded_measurement_is_implausible(seeded) -> None:
    """If the generator ever produces a flagged value, the targets have drifted
    into territory WHO would treat as a data-entry error."""
    async with admin_session() as session:
        flagged = (
            await session.execute(
                text("SELECT count(*) FROM growth_entries WHERE data_quality_flags <> '[]'::jsonb")
            )
        ).scalar_one()
    assert flagged == 0


async def test_captures_are_all_pending_with_no_ai_output(seeded) -> None:
    """The Phase 1 contract. If this ever fails, something is writing AI columns
    before the Phase 2 pipeline exists."""
    async with admin_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT count(*), count(*) FILTER (WHERE sync_status = 'pending'),"
                    " count(ai_calories), count(ai_model_version) FROM plate_captures"
                )
            )
        ).one()
    total, pending, calories, model_version = row
    assert total > 0
    assert pending == total
    assert calories == 0 and model_version == 0


async def test_flagged_compliance_days_exist_and_all_carry_reasons(seeded) -> None:
    async with admin_session() as session:
        total, flagged, with_reason = (
            await session.execute(
                text(
                    "SELECT count(*), count(*) FILTER (WHERE flagged),"
                    " count(*) FILTER (WHERE flagged AND flag_reason IS NOT NULL)"
                    " FROM menu_compliance"
                )
            )
        ).one()
    assert flagged > 0, "an all-compliant demo demonstrates nothing"
    assert flagged < total, "an all-flagged demo is equally useless"
    assert with_reason == flagged


async def test_capture_photo_paths_are_namespaced_by_awc(seeded) -> None:
    """The first path segment is what Storage RLS matches on."""
    async with admin_session() as session:
        mismatched = (
            await session.execute(
                text(
                    "SELECT count(*) FROM plate_captures "
                    "WHERE split_part(photo_url, '/', 1) <> awc_code"
                )
            )
        ).scalar_one()
    assert mismatched == 0


async def test_seed_refuses_to_run_in_production(seeded, monkeypatch) -> None:
    """The guard that stops a demo script from touching a live database."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "app_env", "production")
    with pytest.raises(SystemExit):
        await seed(dry_run=True)
