"""Test fixtures.

Tests run against a real Postgres, not SQLite. That is not incidental: the
security model in this codebase *is* row-level security, and RLS cannot be
exercised on a database that does not implement it. A test suite that passed on
SQLite would prove nothing about the property that matters most here.

By default the suite targets a local Postgres. Set TEST_DATABASE_URL to point
elsewhere. The whole suite is skipped -- loudly -- when no database is
reachable, rather than silently passing with the security tests unrun.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = f"postgresql+asyncpg://{getpass.getuser()}@localhost:5432/poshannetra_pytest"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", DEFAULT_DB)
#: 32+ bytes: PyJWT warns below that for HS256, and a real Supabase JWT
#: secret is comfortably longer. Keeping the test key realistic means the
#: warning stays meaningful if a short secret ever shows up in .env.
TEST_JWT_SECRET = "test-only-secret-not-a-real-key-0123456789abcdef"

os.environ.update(
    APP_ENV="test",
    DATABASE_URL=TEST_DATABASE_URL,
    SUPABASE_JWT_SECRET=TEST_JWT_SECRET,
    SUPABASE_URL="",
    SUPABASE_SERVICE_KEY="",
    SEED_UPLOAD_PHOTOS="false",
)


def _asyncpg_dsn(url: str, database: str | None = None) -> str:
    dsn = url.replace("postgresql+asyncpg://", "postgresql://")
    if database:
        dsn = dsn.rsplit("/", 1)[0] + "/" + database
    return dsn


async def _database_exists() -> bool:
    import asyncpg

    name = TEST_DATABASE_URL.rsplit("/", 1)[-1]
    conn = await asyncpg.connect(_asyncpg_dsn(TEST_DATABASE_URL, "postgres"))
    try:
        return bool(await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name))
    finally:
        await conn.close()


async def _create_database() -> None:
    import asyncpg

    name = TEST_DATABASE_URL.rsplit("/", 1)[-1]
    conn = await asyncpg.connect(_asyncpg_dsn(TEST_DATABASE_URL, "postgres"))
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    """Create and migrate the test database once per session."""
    import asyncio

    try:
        if not asyncio.run(_database_exists()):
            asyncio.run(_create_database())
    except Exception as exc:  # noqa: BLE001
        pytest.skip(
            f"no Postgres reachable at {TEST_DATABASE_URL.rsplit('@', 1)[-1]}: "
            f"{type(exc).__name__}. RLS and API tests cannot run without one.",
            allow_module_level=True,
        )

    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL}
    result = subprocess.run(
        [str(BACKEND_DIR / ".venv" / "bin" / "alembic"), "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade failed:\n{result.stdout}\n{result.stderr}")


# --------------------------------------------------------------------------
# A small, deterministic fixture set -- deliberately NOT the demo seed.
# Tests that depend on 5,000 generated rows are slow and fragile; these are
# hand-chosen so every assertion below can name the exact row it expects.
# --------------------------------------------------------------------------

FIXTURE = {
    "awcs": [
        dict(
            awc_code="TEST-A1",
            name_en="Test AWC One",
            name_hi="परीक्षण केंद्र एक",
            centre_type="anganwadi",
            district="Banswara",
            district_hi="बांसवाड़ा",
            block="Ghatol",
            block_hi="घाटोल",
            latitude=23.5,
            longitude=74.2,
        ),
        dict(
            awc_code="TEST-A2",
            name_en="Test AWC Two",
            name_hi="परीक्षण केंद्र दो",
            centre_type="ashram_school",
            district="Banswara",
            district_hi="बांसवाड़ा",
            block="Anandpuri",
            block_hi="आनंदपुरी",
            latitude=23.3,
            longitude=74.1,
        ),
        dict(
            awc_code="TEST-B1",
            name_en="Test AWC Three",
            name_hi="परीक्षण केंद्र तीन",
            centre_type="anganwadi",
            district="Dungarpur",
            district_hi="डूंगरपुर",
            block="Sagwara",
            block_hi="सागवाड़ा",
            latitude=23.6,
            longitude=74.0,
        ),
    ],
    "workers": [
        dict(
            phone="5550000001",
            name="Worker A1",
            role="field_worker",
            awc_code="TEST-A1",
            district="Banswara",
        ),
        dict(
            phone="5550000002",
            name="Worker A2",
            role="field_worker",
            awc_code="TEST-A2",
            district="Banswara",
        ),
        dict(
            phone="5550000003",
            name="Worker B1",
            role="field_worker",
            awc_code="TEST-B1",
            district="Dungarpur",
        ),
        dict(
            phone="5550000010",
            name="Official Banswara",
            role="district_official",
            awc_code=None,
            district="Banswara",
        ),
        dict(
            phone="5550000011",
            name="Official Dungarpur",
            role="district_official",
            awc_code=None,
            district="Dungarpur",
        ),
        dict(
            phone="5550000020", name="State Admin", role="state_admin", awc_code=None, district=None
        ),
    ],
}


@pytest.fixture(scope="function")
async def fixtures(database) -> dict:
    """Reset to the fixture set before each test. Function scope keeps tests
    independent: a test that inserts a capture cannot affect the next one."""
    from sqlalchemy import delete, insert, select

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

    today = date.today()
    async with admin_session() as session:
        async with session.begin():
            for model in (
                MenuCompliance,
                PlateCapture,
                GrowthEntry,
                Beneficiary,
                FieldWorker,
                MenuItem,
                AWC,
            ):
                await session.execute(delete(model))
            await session.execute(insert(AWC), FIXTURE["awcs"])
            await session.execute(insert(FieldWorker), FIXTURE["workers"])
            await session.execute(
                insert(MenuItem),
                [dict(code="dal", name_en="Dal", name_hi="दाल", category="pulse")],
            )

            children = [
                # A toddler at A1: exercises the WHO 2006 path.
                dict(
                    id=uuid.uuid4(),
                    awc_code="TEST-A1",
                    district="Banswara",
                    block="Ghatol",
                    name="कमला डामोर",
                    dob=today - timedelta(days=1100),
                    gender="F",
                    poshan_tracker_id="PT-A1-0001",
                ),
                dict(
                    id=uuid.uuid4(),
                    awc_code="TEST-A1",
                    district="Banswara",
                    block="Ghatol",
                    name="रमेश मीणा",
                    dob=today - timedelta(days=900),
                    gender="M",
                    poshan_tracker_id="PT-A1-0002",
                ),
                # A school-age child at A2: exercises the WHO 2007 path (D1).
                dict(
                    id=uuid.uuid4(),
                    awc_code="TEST-A2",
                    district="Banswara",
                    block="Anandpuri",
                    name="सीता कटारा",
                    dob=today - timedelta(days=3300),
                    gender="F",
                    poshan_tracker_id="PT-A2-0001",
                ),
                # A different district entirely: the cross-district isolation case.
                dict(
                    id=uuid.uuid4(),
                    awc_code="TEST-B1",
                    district="Dungarpur",
                    block="Sagwara",
                    name="गीता रोत",
                    dob=today - timedelta(days=1200),
                    gender="F",
                    poshan_tracker_id="PT-B1-0001",
                ),
            ]
            await session.execute(insert(Beneficiary), children)

            workers = {r.phone: r for r in (await session.execute(select(FieldWorker))).scalars()}

    return {
        "children": {c["poshan_tracker_id"]: c for c in children},
        "workers": workers,
        "today": today,
    }


@pytest.fixture
def token_for():
    """Mint a JWT for a fixture worker, exactly as /auth/dev/token would."""
    from app.core.principal import Principal, Role
    from app.core.security import mint_token

    def _make(worker) -> str:
        principal = Principal(
            worker_id=str(worker.id),
            role=Role(worker.role),
            awc_code=worker.awc_code,
            district=worker.district,
            name=worker.name,
        )
        return mint_token(principal)[0]

    return _make


@pytest.fixture
async def client():
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def auth(token_for):
    def _headers(worker) -> dict[str, str]:
        return {"Authorization": f"Bearer {token_for(worker)}"}

    return _headers


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    """Give each test's event loop a fresh engine.

    `get_engine` is lru_cached, and an asyncpg pool is bound to the loop that
    created it. pytest-asyncio runs each test in its own loop, so a cached
    engine from a previous test hands the next one connections whose waiters
    belong to a closed loop -- surfacing as "Event loop is closed" rather than
    as anything to do with the test. Disposing inside the test's own loop, then
    clearing the cache, keeps the production code free of test-only plumbing.
    """
    yield
    from app.db.session import dispose_engine, get_engine, get_sessionmaker

    await dispose_engine()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
