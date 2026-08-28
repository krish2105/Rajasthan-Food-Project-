"""Alembic environment. Runs async against the same DATABASE_URL the app uses.

Migrations connect as the table owner, which is correct and necessary: creating
policies and granting the `authenticated` role requires ownership. The runtime
never uses this connection mode (see app/db/session.py).
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.config import get_settings
from app.db.models import Base
from app.db.url import DatabaseUrlError, normalise_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    settings = get_settings()
    try:
        return normalise_database_url(settings.database_url)
    except DatabaseUrlError as exc:
        # A misconfigured connection string is the operator's mistake, not a
        # bug: print the explanation and stop, rather than burying it under an
        # Alembic traceback.
        print(f"\n{exc}\n", file=sys.stderr)
        raise SystemExit(2) from None


def run_migrations_offline() -> None:
    context.configure(
        url=_url(), target_metadata=target_metadata, literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(
        _url(),
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
    )
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
