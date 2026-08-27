"""Growth measurement recording and history (Sections 6.4, 8).

`POST /growth` is the one endpoint in Phase 1 that computes rather than stores.
It runs `app/growth/assess.py` synchronously -- no queue, no background task,
no model call -- because the classification is arithmetic over a lookup table
and takes microseconds. A field worker gets the child's status before they put
the phone down, which is the entire operational point.

The client cannot supply z-scores or a classification. They are not in the
request schema at all, so there is no code path by which a caller could write a
classification the server did not derive.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentPrincipal, ScopedSession, require_role
from app.core.principal import Role
from app.db.models import Beneficiary, GrowthEntry
from app.growth.assess import assess
from app.growth.lms import Sex
from app.schemas.entities import GrowthEntryCreated, GrowthEntryIn, GrowthEntryOut

#: Spelled as a literal: Starlette renamed its 422 constant, and pinning to
#: either spelling breaks on the other version.
HTTP_422 = 422

router = APIRouter(prefix="/growth", tags=["growth"])


@router.post(
    "",
    response_model=GrowthEntryCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(Role.FIELD_WORKER))],
)
async def record_growth(
    payload: GrowthEntryIn, session: ScopedSession, principal: CurrentPrincipal
) -> GrowthEntryCreated:
    recorded_at = payload.recorded_at or date.today()
    if recorded_at > date.today():
        raise HTTPException(
            status_code=HTTP_422,
            detail="recorded_at cannot be in the future",
        )

    # RLS makes an out-of-scope child invisible, so this doubles as the
    # authorisation check: a worker cannot record a measurement against another
    # school's child, because they cannot see that child at all.
    child = (
        await session.execute(select(Beneficiary).where(Beneficiary.id == payload.beneficiary_id))
    ).scalar_one_or_none()
    if child is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="beneficiary not found")

    try:
        result = assess(
            dob=child.dob,
            recorded_at=recorded_at,
            sex=Sex.MALE if child.gender == "M" else Sex.FEMALE,
            height_cm=payload.height_cm,
            weight_kg=payload.weight_kg,
        )
    except ValueError as exc:
        raise HTTPException(status_code=HTTP_422, detail=str(exc)) from exc

    entry = GrowthEntry(
        beneficiary_id=child.id,
        awc_code=child.awc_code,
        district=child.district,
        recorded_at=recorded_at,
        height_cm=payload.height_cm,
        weight_kg=payload.weight_kg,
        age_months=result.age_months,
        standard_used=result.standard_used,
        waz_score=result.waz,
        haz_score=result.haz,
        whz_score=result.whz,
        baz_score=result.baz,
        bmi=result.bmi,
        classification=result.classification,
        classification_detail=result.classification_detail,
        data_quality_flags=result.data_quality_flags,
        recorded_by=uuid.UUID(principal.worker_id) if principal.worker_id else None,
    )
    session.add(entry)
    await session.flush()
    await session.refresh(entry)
    return GrowthEntryCreated(entry=GrowthEntryOut.model_validate(entry), notes=result.notes)


@router.get("/{beneficiary_id}", response_model=list[GrowthEntryOut])
async def growth_history(beneficiary_id: uuid.UUID, session: ScopedSession) -> list[GrowthEntry]:
    """Full history, oldest first -- the shape a trend chart wants."""
    rows = (
        (
            await session.execute(
                select(GrowthEntry)
                .where(GrowthEntry.beneficiary_id == beneficiary_id)
                .order_by(GrowthEntry.recorded_at)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)
