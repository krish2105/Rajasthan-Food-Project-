"""Verify a Supabase project before wiring it into Render.

    uv run python scripts/check_supabase.py

Reads the same environment variables the application does, so it is checking
exactly what the deployment will use. Run it after filling `.env` and before
touching the Render dashboard: every failure it reports is one that would
otherwise surface as an opaque 500 from a service you cannot attach a debugger
to.

Checks, in the order a deployment depends on them:

  1. the connection string parses and reaches Postgres
  2. it is the session pooler, not the transaction pooler
  3. the `authenticated` role exists and can be switched to (RLS rests on this)
  4. pgcrypto is available for gen_random_uuid()
  5. the JWT secret is the symmetric one the app can actually sign with
  6. the storage bucket exists and is private
  7. the region, because Indian children's data in the wrong country is a
     legal-review problem rather than a technical one
"""

from __future__ import annotations

import asyncio
import sys

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.db.url import (
    DatabaseUrlError,
    is_in_india,
    normalise_database_url,
    region_of,
)

OK = "  \033[32mok\033[0m   "
BAD = "  \033[31mFAIL\033[0m "
WARN = "  \033[33mwarn\033[0m "


def line(status: str, message: str) -> None:
    print(f"{status} {message}")


async def check_database(raw: str) -> tuple[bool, str]:
    """Returns (ok, normalised_url). The URL is normalised here so the region
    check below reads the same string the application will actually connect
    with -- including when the operator pasted Supabase's `psql "..."` line."""
    try:
        url = normalise_database_url(raw)
    except DatabaseUrlError as exc:
        headline, *detail = str(exc).splitlines()
        line(BAD, headline)
        for part in detail:
            print(f"     {part}")
        return False, ""

    if url != (raw or "").strip().strip("'\""):
        line(OK, "connection string normalised to the asyncpg session-pooler form")

    engine = create_async_engine(
        url, connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0}
    )
    try:
        async with engine.connect() as conn:
            version = (await conn.execute(text("SHOW server_version"))).scalar_one()
            line(OK, f"connected to Postgres {version}")

            role = (
                await conn.execute(
                    text("SELECT 1 FROM pg_roles WHERE rolname = 'authenticated'")
                )
            ).scalar_one_or_none()
            if role:
                line(OK, "the `authenticated` role exists")
            else:
                line(WARN, "no `authenticated` role yet -- migration 0002 creates it")

            try:
                # SQLAlchemy's async connection already holds an implicit
                # transaction, so `SET LOCAL` is executed directly rather than
                # opening a nested one -- begin() on an active transaction
                # raises rather than nesting.
                await conn.execute(text("SET LOCAL ROLE authenticated"))
                await conn.execute(text("RESET ROLE"))
                line(OK, "can switch to `authenticated` (row-level security will apply)")
            except Exception as exc:  # noqa: BLE001
                line(BAD, f"cannot SET ROLE authenticated: {type(exc).__name__}")
                print("       Without this the backend stays the table owner and")
                print("       every RLS policy is silently bypassed.")
                return False, url

            has_pgcrypto = (
                await conn.execute(
                    text("SELECT 1 FROM pg_available_extensions WHERE name = 'pgcrypto'")
                )
            ).scalar_one_or_none()
            line(
                OK if has_pgcrypto else BAD,
                "pgcrypto available (gen_random_uuid)" if has_pgcrypto else "pgcrypto missing",
            )

            tables = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
            ).scalar_one()
            if tables:
                line(OK, f"{tables} tables already present (migrations have run)")
            else:
                line(WARN, "no tables yet -- run: alembic upgrade head")
        return True, url
    except Exception as exc:  # noqa: BLE001
        line(BAD, f"could not connect: {type(exc).__name__}: {str(exc)[:140]}")
        return False, url
    finally:
        await engine.dispose()


def check_jwt_secret(secret: str) -> bool:
    if not secret:
        line(BAD, "SUPABASE_JWT_SECRET is not set")
        return False
    if secret.startswith("-----BEGIN") or secret.startswith("{"):
        line(BAD, "that looks like an asymmetric signing key, not the legacy secret")
        print("       This build signs HS256 with the symmetric JWT secret so one")
        print("       token works for the API, Postgres RLS and Storage. If your")
        print("       project only offers the new keys, set STORAGE_MODE=service")
        print("       and see docs/phase1-supabase-setup.md.")
        return False
    if len(secret) < 32:
        line(BAD, f"JWT secret is only {len(secret)} characters; expected 40+")
        return False
    line(OK, f"JWT secret looks like the legacy HS256 one ({len(secret)} chars)")
    return True


async def check_storage(url: str, key: str, bucket: str) -> bool:
    if not url or not key:
        line(WARN, "SUPABASE_URL / SUPABASE_SERVICE_KEY not set -- storage unchecked")
        return True
    headers = {"Authorization": f"Bearer {key}", "apikey": key}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{url.rstrip('/')}/storage/v1/bucket/{bucket}",
                                        headers=headers)
    except httpx.HTTPError as exc:
        line(BAD, f"could not reach Storage: {exc}")
        return False

    if response.status_code == 404:
        line(BAD, f"bucket '{bucket}' does not exist -- create it, PRIVATE")
        return False
    if response.status_code >= 400:
        line(BAD, f"Storage refused the service key ({response.status_code})")
        return False

    body = response.json()
    if body.get("public"):
        line(BAD, f"bucket '{bucket}' is PUBLIC")
        print("       These are photographs taken inside Anganwadi centres. A")
        print("       public bucket is a public URL for every one of them.")
        return False
    line(OK, f"bucket '{bucket}' exists and is private")
    return True


def check_region(url: str) -> None:
    """Region is a legal question here, not only a latency one."""
    region = region_of(url)
    if region is None:
        line(WARN, "could not read the region from DATABASE_URL")
        return
    if is_in_india(url):
        line(OK, f"region {region} -- the data rests in India")
        return
    line(BAD, f"region {region} is outside India")
    print("       Section 12 puts this system under India's DPDP Act, 2023, and")
    print("       the first question at any government legal review is where the")
    print("       data lives. Supabase cannot move a project between regions, so")
    print("       recreating in ap-south-1 is cheap now and expensive later.")


async def main() -> None:
    settings = get_settings()
    print("Checking Supabase configuration\n")

    db_ok, url = await check_database(settings.database_url)
    check_region(url)
    # A non-Indian region is a blocking finding, not advice: it cannot be
    # changed later without moving every row.
    region_ok = is_in_india(url) is not False
    jwt_ok = check_jwt_secret(settings.supabase_jwt_secret)
    storage_ok = await check_storage(
        settings.supabase_url, settings.supabase_service_key, settings.supabase_storage_bucket
    )

    print()
    if db_ok and jwt_ok and storage_ok and region_ok:
        print("Ready. Next: alembic upgrade head, then python -m app.seed")
        sys.exit(0)
    print("Not ready -- fix the FAIL lines above before configuring Render.")
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
