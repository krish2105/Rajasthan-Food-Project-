"""Caller identity and the bilingual reference data the Field PWA caches.

Section 7 requires the beneficiary and centre lists to be available offline, so
these endpoints are the PWA's first-sync payload. They return both languages in
one response for the reason given in schemas/common.py.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentPrincipal, ScopedSession
from app.core.principal import Role
from app.db.models import AWC, MenuItem
from app.schemas.entities import AWCOut, MenuItemOut, MeOut

router = APIRouter(tags=["reference"])

_SCOPE_EN = {
    Role.FIELD_WORKER: "Your Anganwadi centre only",
    Role.DISTRICT_OFFICIAL: "All centres in your district",
    Role.STATE_ADMIN: "All centres, state-wide",
}
_SCOPE_HI = {
    Role.FIELD_WORKER: "केवल आपका आंगनवाड़ी केंद्र",
    Role.DISTRICT_OFFICIAL: "आपके ज़िले के सभी केंद्र",
    Role.STATE_ADMIN: "राज्य भर के सभी केंद्र",
}


@router.get("/me", response_model=MeOut)
async def me(principal: CurrentPrincipal) -> MeOut:
    """What the server believes about the caller.

    Useful in its own right, and a fast way for a reviewer to confirm that scope
    comes from the token rather than from anything the client asserted.
    """
    return MeOut(
        worker_id=principal.worker_id,
        name=principal.name,
        role=principal.role,
        awc_code=principal.awc_code,
        district=principal.district,
        scope_description_en=_SCOPE_EN[principal.role],
        scope_description_hi=_SCOPE_HI[principal.role],
    )


@router.get("/awcs", response_model=list[AWCOut])
async def list_awcs(session: ScopedSession) -> list[AWC]:
    """Centres visible to the caller. Row scoping is done by RLS, not here."""
    result = await session.execute(select(AWC).order_by(AWC.district, AWC.awc_code))
    return list(result.scalars().all())


@router.get("/menu-items", response_model=list[MenuItemOut])
async def list_menu_items(session: ScopedSession) -> list[MenuItem]:
    """Bilingual PM POSHAN vocabulary. Shared reference data, not scoped."""
    result = await session.execute(select(MenuItem).order_by(MenuItem.code))
    return list(result.scalars().all())
