"""Proof that scoping is enforced by Postgres, not by the API layer.

Every test here talks to the database directly, with no FastAPI in the picture.
That is the whole point. A test that goes through the API proves the handler
filtered correctly today; a test that goes through a raw session with claims
proves that a handler written next year, by someone who never read Section 10,
*cannot* leak another school's data even if they forget every filter.

Section 11 asks for cross-school access to be "structurally impossible, not just
impossible via the UI". These are the tests that make that sentence checkable.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.principal import Principal, Role
from app.db.session import admin_session, apply_claims, get_sessionmaker


async def _count_as(claims_json: str | None, table: str = "beneficiaries") -> int:
    """Count visible rows for an arbitrary claim set, including a broken one."""
    async with get_sessionmaker()() as session:
        async with session.begin():
            if claims_json is not None:
                await session.execute(
                    text("SELECT set_config('request.jwt.claims', :c, true)"),
                    {"c": claims_json},
                )
            await session.execute(text("SET LOCAL ROLE authenticated"))
            return (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()


async def _count_for(principal: Principal, table: str = "beneficiaries") -> int:
    async with get_sessionmaker()() as session:
        async with session.begin():
            await apply_claims(session, principal)
            return (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()


def _p(role: Role, awc: str | None, district: str | None) -> Principal:
    return Principal(worker_id=str(uuid.uuid4()), role=role, awc_code=awc, district=district)


# --------------------------------------------------------------------------
# The core isolation guarantee
# --------------------------------------------------------------------------


async def test_field_worker_sees_only_their_own_awc(fixtures) -> None:
    n = await _count_for(_p(Role.FIELD_WORKER, "TEST-A1", "Banswara"))
    assert n == 2, "TEST-A1 has exactly two children in the fixture"


async def test_two_field_workers_see_disjoint_sets(fixtures) -> None:
    """The RBAC proof: no child is visible to workers at two different centres."""

    async def names(awc: str, district: str) -> set[str]:
        async with get_sessionmaker()() as session:
            async with session.begin():
                await apply_claims(session, _p(Role.FIELD_WORKER, awc, district))
                rows = await session.execute(text("SELECT name FROM beneficiaries"))
                return {r[0] for r in rows}

    a1 = await names("TEST-A1", "Banswara")
    a2 = await names("TEST-A2", "Banswara")
    b1 = await names("TEST-B1", "Dungarpur")
    assert a1 and a2 and b1
    assert a1 & a2 == set()
    assert a1 & b1 == set()
    assert a2 & b1 == set()


async def test_district_official_sees_their_district_and_no_other(fixtures) -> None:
    banswara = await _count_for(_p(Role.DISTRICT_OFFICIAL, None, "Banswara"))
    dungarpur = await _count_for(_p(Role.DISTRICT_OFFICIAL, None, "Dungarpur"))
    assert banswara == 3  # two at A1, one at A2
    assert dungarpur == 1


async def test_state_admin_sees_everything(fixtures) -> None:
    assert await _count_for(_p(Role.STATE_ADMIN, None, None)) == 4


async def test_a_field_worker_cannot_widen_scope_by_claiming_a_district(fixtures) -> None:
    """app_role decides which predicate applies. Adding a district claim to a
    field_worker token must not promote them to district-wide visibility."""
    n = await _count_for(_p(Role.FIELD_WORKER, "TEST-A1", "Banswara"))
    assert n == 2, "still only their own AWC, not all of Banswara"


async def test_a_district_official_cannot_reach_another_district(fixtures) -> None:
    async with get_sessionmaker()() as session:
        async with session.begin():
            await apply_claims(session, _p(Role.DISTRICT_OFFICIAL, None, "Dungarpur"))
            rows = await session.execute(
                text("SELECT count(*) FROM beneficiaries WHERE district = 'Banswara'")
            )
            # An explicit filter for the other district returns nothing: the
            # policy is applied before the WHERE clause can help.
            assert rows.scalar_one() == 0


# --------------------------------------------------------------------------
# Failing closed
# --------------------------------------------------------------------------


async def test_no_claims_sees_nothing(fixtures) -> None:
    assert await _count_as(None) == 0


@pytest.mark.parametrize(
    "claims",
    [
        "",
        "not json at all",
        "{",
        "[]",
        '{"app_role":"nonsense"}',
        '{"app_role":"field_worker"}',  # role with no awc_code
        '{"app_role":"district_official"}',  # role with no district
    ],
)
async def test_malformed_or_incomplete_claims_see_nothing(fixtures, claims: str) -> None:
    """Every failure mode must be an empty result, never an error.

    A database error here would surface as a 500 that is distinguishable from an
    empty 200 -- and that difference is itself a signal about which rows exist.
    """
    assert await _count_as(claims) == 0


async def test_claims_do_not_leak_between_transactions(fixtures) -> None:
    """SET LOCAL is transaction-scoped, which is what makes pooling safe.

    Reuses one session for both transactions: if claims survived a COMMIT, a
    pooled connection would serve the previous caller's scope to the next one.
    """
    async with get_sessionmaker()() as session:
        async with session.begin():
            await apply_claims(session, _p(Role.STATE_ADMIN, None, None))
            assert (
                await session.execute(text("SELECT count(*) FROM beneficiaries"))
            ).scalar_one() == 4
        async with session.begin():
            await session.execute(text("SET LOCAL ROLE authenticated"))
            assert (
                await session.execute(text("SELECT count(*) FROM beneficiaries"))
            ).scalar_one() == 0


# --------------------------------------------------------------------------
# Writes are narrower than reads
# --------------------------------------------------------------------------


async def test_field_worker_cannot_insert_into_another_awc(fixtures) -> None:
    child = fixtures["children"]["PT-A1-0001"]
    with pytest.raises(Exception) as excinfo:
        async with get_sessionmaker()() as session:
            async with session.begin():
                await apply_claims(session, _p(Role.FIELD_WORKER, "TEST-A1", "Banswara"))
                await session.execute(
                    text(
                        "INSERT INTO plate_captures "
                        "(beneficiary_id, awc_code, district, photo_url, meal_type, captured_at) "
                        "VALUES (:b, 'TEST-A2', 'Banswara', 'x.jpg', 'lunch', now())"
                    ),
                    {"b": child["id"]},
                )
    assert "row-level security" in str(excinfo.value).lower()


async def test_district_official_cannot_insert_growth_at_all(fixtures) -> None:
    """Oversight roles observe; they do not fabricate measurements."""
    child = fixtures["children"]["PT-A1-0001"]
    with pytest.raises(Exception) as excinfo:
        async with get_sessionmaker()() as session:
            async with session.begin():
                await apply_claims(session, _p(Role.DISTRICT_OFFICIAL, None, "Banswara"))
                await session.execute(
                    text(
                        "INSERT INTO growth_entries (beneficiary_id, awc_code, district,"
                        " recorded_at, height_cm, weight_kg, age_months, standard_used,"
                        " classification, classification_detail) VALUES"
                        " (:b,'TEST-A1','Banswara',CURRENT_DATE,90,12,36,"
                        "'who_2006_0_60m','normal','{}'::jsonb)"
                    ),
                    {"b": child["id"]},
                )
    assert "row-level security" in str(excinfo.value).lower()


async def test_nobody_can_update_or_delete_through_the_authenticated_role(fixtures) -> None:
    """No UPDATE or DELETE policy exists anywhere, on purpose. For a system of
    record about children, corrections belong in an append-only amendment trail
    (Phase 6+), not in a silent in-place edit."""
    for statement in (
        "UPDATE beneficiaries SET name = 'changed'",
        "DELETE FROM beneficiaries",
    ):
        # Postgres raises "permission denied" rather than an RLS violation here:
        # with no UPDATE/DELETE grant at all, the statement never reaches a
        # policy check. Either way the write is impossible for this role.
        with pytest.raises(ProgrammingError):
            async with get_sessionmaker()() as session:
                async with session.begin():
                    await apply_claims(session, _p(Role.STATE_ADMIN, None, None))
                    await session.execute(text(statement))


# --------------------------------------------------------------------------
# Coverage: every table carries a policy
# --------------------------------------------------------------------------


async def test_every_public_table_has_rls_enabled(fixtures) -> None:
    """Guards against a future migration adding a table and forgetting RLS,
    which would silently create an unscoped read path."""
    async with admin_session() as session:
        rows = await session.execute(
            text(
                "SELECT tablename, rowsecurity FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        )
        unprotected = [t for t, secure in rows if not secure]
    assert unprotected == [], f"tables without RLS: {unprotected}"


async def test_scoped_tables_are_all_isolated(fixtures) -> None:
    """The same isolation guarantee, applied to every table that carries an
    awc_code -- not just beneficiaries."""
    from sqlalchemy import insert

    from app.db.models import PlateCapture

    child_a1 = fixtures["children"]["PT-A1-0001"]
    child_b1 = fixtures["children"]["PT-B1-0001"]
    async with admin_session() as session:
        async with session.begin():
            await session.execute(
                insert(PlateCapture),
                [
                    dict(
                        beneficiary_id=child_a1["id"],
                        awc_code="TEST-A1",
                        district="Banswara",
                        photo_url="a.jpg",
                        meal_type="lunch",
                        captured_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
                    ),
                    dict(
                        beneficiary_id=child_b1["id"],
                        awc_code="TEST-B1",
                        district="Dungarpur",
                        photo_url="b.jpg",
                        meal_type="lunch",
                        captured_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
                    ),
                ],
            )
    assert await _count_for(_p(Role.FIELD_WORKER, "TEST-A1", "Banswara"), "plate_captures") == 1
    assert await _count_for(_p(Role.FIELD_WORKER, "TEST-B1", "Dungarpur"), "plate_captures") == 1
    assert await _count_for(_p(Role.STATE_ADMIN, None, None), "plate_captures") == 2
