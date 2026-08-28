"""Phone-OTP sign-in (Sections 4, 10, 11).

This replaces the development token endpoint that carried Phases 1 to 5. That
endpoint was gated on APP_ENV and tested, but it was still an authentication
bypass one environment variable away from being live, and Section 16 step 6 is
the moment to remove it rather than keep two ways of obtaining a token where
only one is hardened.

The scope model did not change. Roles, claims and every row-level security
policy have been real since Phase 1; only the way a caller proves who they are
is different now.

Responses are deliberately uninformative about failure. An unregistered number,
a wrong code and an expired code all produce the same reply, because a phone
number that answers differently is a phone number an attacker can enumerate --
and the numbers here belong to Anganwadi workers.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.auth import otp, refresh
from app.auth.providers import DeliveryError, build_provider
from app.config import get_settings
from app.core.principal import Principal, Role
from app.core.security import mint_token
from app.db.session import admin_session

logger = logging.getLogger("poshannetra.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

#: Indian mobile numbers. Ten digits, and a leading 91 country code is stripped
#: so both forms reach the same worker record.
PHONE_PATTERN = r"^[6-9]\d{9}$"


def normalise_phone(raw: str) -> str:
    digits = "".join(c for c in raw if c.isdigit())
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    return digits


class OtpRequest(BaseModel):
    phone: str = Field(min_length=10, max_length=15)


class OtpVerify(BaseModel):
    phone: str = Field(min_length=10, max_length=15)
    otp: str = Field(min_length=4, max_length=8)


class RefreshRequest(BaseModel):
    refresh_token: str


class SessionOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_at: str
    role: Role
    name: str
    awc_code: str | None
    district: str | None


@router.post("/otp/request", status_code=status.HTTP_202_ACCEPTED)
async def request_otp(payload: OtpRequest, request: Request) -> dict:
    """Send a one-time code.

    Always reports success, whether or not the number belongs to staff. The
    alternative turns this endpoint into a way to discover which numbers are
    registered, and the throttle applies either way so an attacker learns
    nothing from timing either.
    """
    settings = get_settings()
    phone = normalise_phone(payload.phone)

    generic = {
        "status": "sent",
        "expires_in": otp.TTL_SECONDS,
        "message_en": "If that number is registered, a code is on its way.",
        "message_hi": "यदि यह नंबर दर्ज है, तो कोड भेजा जा रहा है।",
    }

    if len(phone) != 10:
        # Malformed input is the one thing worth naming: the worker mistyped,
        # and telling them so does not reveal anything about who is registered.
        raise HTTPException(
            status_code=422,  # spelled literally: Starlette renamed the constant
            detail="enter a 10-digit mobile number",
        )

    async with admin_session() as session:
        async with session.begin():
            try:
                await otp.check_throttle(session, phone)
            except otp.Throttled as exc:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"too many requests; try again in {exc.retry_after}s",
                    headers={"Retry-After": str(exc.retry_after)},
                ) from exc

            issued = await otp.issue(session, phone)

            provider = build_provider()
            try:
                result = await provider.send(
                    phone=phone, code=issued.code, ttl_seconds=otp.TTL_SECONDS
                )
                status_text, detail = result.status, result.detail
            except DeliveryError as exc:
                # The code is already stored. Recording why it never arrived is
                # what lets an operator tell "the worker never typed it" apart
                # from "it was never sent".
                logger.error("OTP delivery failed for %s: %s", phone, exc)
                status_text, detail, result = "failed", str(exc)[:500], None

            from sqlalchemy import select

            from app.db.models import OtpCode

            record = (
                await session.execute(select(OtpCode).where(OtpCode.id == issued.record_id))
            ).scalar_one()
            record.delivery_status = status_text
            record.delivery_detail = detail

    if status_text == "failed":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="could not send the code; try again shortly",
        )

    # Only the console provider outside production populates this, so a demo
    # does not require reading a server log.
    if result is not None and result.code_for_display and not settings.is_production:
        return {**generic, "debug_code": result.code_for_display, "provider": provider.name}
    return {**generic, "provider": provider.name}


@router.post("/otp/verify", response_model=SessionOut)
async def verify_otp(payload: OtpVerify, request: Request) -> SessionOut:
    """Exchange a code for an access token and a refresh token."""
    phone = normalise_phone(payload.phone)

    async with admin_session() as session:
        async with session.begin():
            worker = await otp.verify(session, phone, payload.otp.strip())
            # The 401 is raised after this block, not inside it. Raising here
            # would roll the transaction back and discard the attempt counter
            # that makes the brute-force limit work.
            principal = None
            issued_refresh = None
            if worker is not None:
                issued_refresh = await refresh.issue(session, worker)
                principal = Principal(
                    worker_id=str(worker.id),
                    role=Role(worker.role),
                    awc_code=worker.awc_code,
                    district=worker.district,
                    name=worker.name,
                )

    if principal is None or issued_refresh is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="that code is not valid"
        )

    access, ttl = mint_token(principal)
    return SessionOut(
        access_token=access,
        refresh_token=issued_refresh.token,
        expires_in=ttl,
        refresh_expires_at=issued_refresh.expires_at.isoformat(),
        role=principal.role,
        name=principal.name,
        awc_code=principal.awc_code,
        district=principal.district,
    )


@router.post("/refresh", response_model=SessionOut)
async def refresh_session(payload: RefreshRequest) -> SessionOut:
    """Exchange a refresh token for a new pair.

    Rotating on every use means a captured token is good for one exchange. If
    the same token arrives twice the chain is revoked, because either it was
    replayed or the device was cloned and neither should keep working.
    """
    async with admin_session() as session:
        async with session.begin():
            result = await refresh.rotate(session, payload.refresh_token)
            # Committed before the 401 below: a detected reuse revokes every
            # session for that worker, and those revocations must survive the
            # rejection that follows.
            principal = None
            if result.ok:
                worker = result.worker
                assert worker is not None
                principal = Principal(
                    worker_id=str(worker.id),
                    role=Role(worker.role),
                    awc_code=worker.awc_code,
                    district=worker.district,
                    name=worker.name,
                )

    if principal is None or result.issued is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=result.error or "refresh failed",
        )
    issued = result.issued

    access, ttl = mint_token(principal)
    return SessionOut(
        access_token=access,
        refresh_token=issued.token,
        expires_in=ttl,
        refresh_expires_at=issued.expires_at.isoformat(),
        role=principal.role,
        name=principal.name,
        awc_code=principal.awc_code,
        district=principal.district,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: RefreshRequest) -> None:
    """Sign out this device.

    Unknown tokens succeed silently: reporting which ones exist would make this
    an oracle, and a client signing out has nothing useful to do with the
    difference.
    """
    async with admin_session() as session:
        async with session.begin():
            await refresh.revoke(session, payload.refresh_token)
