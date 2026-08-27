"""Development-only token issuance. Phase 6 replaces this with phone OTP.

Section 16 step 6 defers real auth until the core flows work, and Section 10
says a stubbed OTP is acceptable until there is a district partner. What is
*not* deferred is the scope model: the token minted here carries exactly the
claims a real OTP token will carry, so the RLS policies and every route are
already running against production-shaped identities.

This router refuses to serve when APP_ENV=production. That check is the only
thing standing between a demo convenience and an authentication bypass, so it
returns 404 rather than 403 -- in production the endpoint should not appear to
exist at all.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.config import get_settings
from app.core.principal import Principal, Role
from app.core.security import mint_token
from app.db.models import FieldWorker
from app.db.session import admin_session
from app.schemas.entities import DevTokenIn, TokenOut

router = APIRouter(prefix="/auth", tags=["auth (dev)"])


@router.post("/dev/token", response_model=TokenOut)
async def dev_token(payload: DevTokenIn) -> TokenOut:
    if get_settings().is_production:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # Uses admin_session because the caller has no identity yet -- this is the
    # one place in the request path where that is legitimate. It reads a single
    # row by phone number and returns no beneficiary data.
    async with admin_session() as session:
        worker = (
            await session.execute(select(FieldWorker).where(FieldWorker.phone == payload.phone))
        ).scalar_one_or_none()

    if worker is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no worker with that phone"
        )

    principal = Principal(
        worker_id=str(worker.id),
        role=Role(worker.role),
        awc_code=worker.awc_code,
        district=worker.district,
        name=worker.name,
    )
    token, ttl = mint_token(principal)
    return TokenOut(
        access_token=token,
        expires_in=ttl,
        role=principal.role,
        awc_code=principal.awc_code,
        district=principal.district,
    )
