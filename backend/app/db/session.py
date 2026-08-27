"""Database sessions, and the two very different ways this app talks to Postgres.

`admin_session` connects as the table owner. It bypasses RLS -- as it must, since
migrations and the seed script have to write across every AWC. Only Alembic and
`app/seed/` may use it.

`rls_session` is what every request path uses. Before any query runs it stamps
the caller's JWT claims onto the transaction and switches to Supabase's
non-owner `authenticated` role, so the row-level policies in migration 0002
actually apply. The switch is the whole point: a table's owner bypasses RLS
silently, so a backend that stays `postgres` gets policies that look like
security and enforce nothing.

Both settings are `SET LOCAL` / `set_config(..., is_local => true)`, which are
transaction-scoped. That is what makes this safe under connection pooling --
claims cannot leak from one request to the next, because the transaction that
carried them has ended.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.core.principal import Principal

#: Supabase's own non-owner Postgres role. Distinct from our `app_role` claim.
DB_ROLE = "authenticated"


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and fill it in "
            "(see docs/phase1-supabase-setup.md)."
        )
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={
            # Supabase's poolers do not play well with asyncpg's prepared
            # statement cache. Disabling it costs a little per-query planning
            # time and removes a whole class of "prepared statement already
            # exists" failures that only appear under load.
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "server_settings": {"application_name": "poshannetra-api"},
        },
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        get_engine(), expire_on_commit=False, autoflush=False, class_=AsyncSession
    )


@asynccontextmanager
async def admin_session() -> AsyncIterator[AsyncSession]:
    """Owner-role session. RLS does not apply. Migrations and seeding only."""
    async with get_sessionmaker()() as session:
        yield session


@asynccontextmanager
async def rls_session(principal: Principal) -> AsyncIterator[AsyncSession]:
    """Request-scoped session with the caller's claims enforced by Postgres."""
    async with get_sessionmaker()() as session:
        async with session.begin():
            await apply_claims(session, principal)
            yield session


async def apply_claims(session: AsyncSession, principal: Principal) -> None:
    """Stamp claims onto the current transaction, then drop to `authenticated`.

    Order matters. The claims are set while we still hold the owner role, then
    we downgrade; doing it the other way round depends on `authenticated` being
    allowed to write the GUC, which is not something to rely on.

    `set_config` is used rather than a literal `SET LOCAL` because it accepts a
    bind parameter -- the claims blob contains user-controlled values such as
    the AWC code, and string-interpolating those into DDL-adjacent SQL would be
    an injection hole in the one place we least want one.
    """
    await session.execute(
        text("SELECT set_config('request.jwt.claims', :claims, true)"),
        {"claims": principal.claims_json()},
    )
    await session.execute(text(f"SET LOCAL ROLE {DB_ROLE}"))


async def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
