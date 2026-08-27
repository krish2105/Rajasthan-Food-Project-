"""Beneficiary listing and lookup (Section 8).

Note what is absent from every query below: a `WHERE awc_code = ...` clause.
That is deliberate. Scoping happens in the RLS policies from migration 0002, so
a handler cannot leak another school's children by forgetting a filter. The
filters that *are* here narrow within what the caller may already see; they
never widen it.
"""

from __future__ import annotations

import base64
import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import ScopedSession
from app.db.models import Beneficiary
from app.growth.assess import age_in_days
from app.growth.lms import DAYS_PER_MONTH
from app.schemas.common import Page
from app.schemas.entities import BeneficiaryOut

router = APIRouter(prefix="/beneficiaries", tags=["beneficiaries"])

MAX_PAGE_SIZE = 200


def _encode_cursor(value: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(str(value).encode()).decode()


def _decode_cursor(cursor: str) -> uuid.UUID:
    try:
        return uuid.UUID(base64.urlsafe_b64decode(cursor.encode()).decode())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="malformed cursor"
        ) from exc


def _to_out(row: Beneficiary, today) -> BeneficiaryOut:
    out = BeneficiaryOut.model_validate(row)
    out.age_months = round(age_in_days(row.dob, today) / DAYS_PER_MONTH)
    return out


@router.get("", response_model=Page[BeneficiaryOut])
async def list_beneficiaries(
    session: ScopedSession,
    awc_code: str | None = None,
    district: str | None = None,
    q: str | None = Query(default=None, description="Case-insensitive name search"),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = None,
) -> Page[BeneficiaryOut]:
    from datetime import date as _date

    stmt = select(Beneficiary).order_by(Beneficiary.id)
    if awc_code:
        stmt = stmt.where(Beneficiary.awc_code == awc_code)
    if district:
        stmt = stmt.where(Beneficiary.district == district)
    if q:
        stmt = stmt.where(func.lower(Beneficiary.name).like(f"%{q.lower()}%"))
    if cursor:
        stmt = stmt.where(Beneficiary.id > _decode_cursor(cursor))

    # Fetch one extra row to decide `has_more` without a second COUNT query.
    rows = list((await session.execute(stmt.limit(limit + 1))).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    today = _date.today()
    return Page[BeneficiaryOut](
        items=[_to_out(r, today) for r in rows],
        next_cursor=_encode_cursor(rows[-1].id) if rows and has_more else None,
        has_more=has_more,
    )


@router.get("/{beneficiary_id}", response_model=BeneficiaryOut)
async def get_beneficiary(beneficiary_id: uuid.UUID, session: ScopedSession) -> BeneficiaryOut:
    from datetime import date as _date

    row = (
        await session.execute(select(Beneficiary).where(Beneficiary.id == beneficiary_id))
    ).scalar_one_or_none()
    # 404, not 403, when the row exists but is out of scope. RLS has already
    # made it invisible, so the handler genuinely cannot tell the two cases
    # apart -- and that is the desired behaviour: a distinguishable 403 would
    # confirm that a given child exists at some other school.
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return _to_out(row, _date.today())
