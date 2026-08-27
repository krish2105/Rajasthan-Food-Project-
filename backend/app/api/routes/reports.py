"""District and state reporting (Section 8).

Section 16 orders the District Dashboard before the State Admin view, but the
two consume the same aggregation, so both routes are built here rather than
letting Phase 4 add a second implementation of prevalence that could disagree
with this one.

Scoping is the interesting part. `/reports/state` is gated to `state_admin` by
`require_role`, but the aggregation underneath is scoped by RLS regardless --
so `/reports/district/{district}` returns nothing at all when a district
official names someone else's district, rather than returning their data. The
route does not filter; the policies do.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentPrincipal, ScopedSession, require_role
from app.core.principal import Role
from app.db.models import MenuCompliance
from app.reports import aggregate
from app.reports.aggregate import Scope

router = APIRouter(tags=["reports"])


@router.get(
    "/reports/state",
    dependencies=[Depends(require_role(Role.STATE_ADMIN))],
)
async def state_report(session: ScopedSession) -> dict:
    """State-wide rollup. The pitch surface's primary data source."""
    return await aggregate.build_report(session, Scope(label="state"))


@router.get(
    "/reports/district/{district}",
    dependencies=[Depends(require_role(Role.DISTRICT_OFFICIAL, Role.STATE_ADMIN))],
)
async def district_report(district: str, session: ScopedSession) -> dict:
    report = await aggregate.build_report(session, Scope(label="district", district=district))
    # An out-of-scope district produces an empty report rather than an error,
    # because RLS filtered the rows before the aggregate ran. Reporting that as
    # 404 keeps it indistinguishable from a district that does not exist --
    # which is the same reasoning as the 404-not-403 rule on beneficiaries.
    if report["coverage"]["centres"] == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no data for district")
    return report


@router.get(
    "/compliance/{awc_code}/{day}",
    dependencies=[Depends(require_role(Role.DISTRICT_OFFICIAL, Role.STATE_ADMIN))],
)
async def compliance_for_day(awc_code: str, day: date, session: ScopedSession) -> dict:
    """One centre's menu compliance for one day (Section 8).

    Scoped to oversight roles: a field worker seeing a compliance flag against
    their own kitchen, in an app they use while cooking, changes what gets
    photographed. The flag is for the block officer who follows it up.
    """
    row = (
        await session.execute(
            select(MenuCompliance).where(
                MenuCompliance.awc_code == awc_code, MenuCompliance.date == day
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no record for that day")
    return {
        "awc_code": row.awc_code,
        "district": row.district,
        "date": row.date.isoformat(),
        "prescribed_items": row.prescribed_items,
        "detected_items": row.detected_items,
        "compliance_pct": float(row.compliance_pct) if row.compliance_pct is not None else None,
        "flagged": row.flagged,
        "flag_reason": row.flag_reason,
    }


@router.get("/reports/scope")
async def report_scope(principal: CurrentPrincipal) -> dict:
    """What this caller may report on. Lets the UI pick its own title."""
    return {
        "role": principal.role.value,
        "district": principal.district,
        "can_view_state": principal.role is Role.STATE_ADMIN,
    }
