"""Liveness and database reachability.

`/health/db` exists partly for a mundane operational reason: Supabase pauses a
free-tier project after a week of inactivity, and a paused project fails at the
worst possible moment -- the start of a demo. Pinging this endpoint on a
schedule keeps the project warm (Section 13).
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.db.session import get_engine
from app.db.url import is_in_india, region_of

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app_env": settings.app_env,
        "phase": 2,
        "ai": {
            "enabled": settings.ai_enabled,
            "provider": settings.ai_provider,
            "configured": settings.ai_configured,
            # Surfaced so a demo cannot quietly present mock output as real.
            "is_mock": settings.ai_provider == "mock",
        },
    }


@router.get("/health/db")
async def health_db() -> JSONResponse:
    settings = get_settings()
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
            rls = await conn.execute(
                text("SELECT count(*) FROM pg_policies WHERE schemaname = 'public'")
            )
            policy_count = rls.scalar_one()
    except Exception as exc:  # noqa: BLE001 - report, never leak the DSN
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable", "error": type(exc).__name__},
        )
    # Data residency, answerable without dashboard access. Section 12 puts this
    # system under the DPDP Act, 2023, so "where does the data rest" is a
    # question a reviewer is entitled to check for themselves rather than take
    # on trust. Only the region code is exposed -- never the host or the DSN.
    region = region_of(settings.database_url)
    return JSONResponse(
        content={
            "status": "ok",
            "rls_policies": policy_count,
            "data_residency": {
                "region": region,
                "in_india": is_in_india(settings.database_url),
            },
        }
    )
