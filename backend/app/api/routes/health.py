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

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    return {"status": "ok", "app_env": settings.app_env, "phase": 1}


@router.get("/health/db")
async def health_db() -> JSONResponse:
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
    return JSONResponse(content={"status": "ok", "rls_policies": policy_count})
