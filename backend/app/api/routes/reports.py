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

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentPrincipal, ScopedSession, require_role
from app.core.principal import Role
from app.db.models import FollowUp, MenuCompliance
from app.db.models.follow_up import OUTCOMES
from app.reports import aggregate, worklist
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


@router.get("/reports/scope")
async def report_scope(principal: CurrentPrincipal) -> dict:
    """What this caller may report on. Lets the UI pick its own title."""
    return {
        "role": principal.role.value,
        "district": principal.district,
        "can_view_state": principal.role is Role.STATE_ADMIN,
    }


# ---------------------------------------------------------------------------
# District Dashboard worklist (Section 9.2)
# ---------------------------------------------------------------------------

# Route order matters here. FastAPI resolves in registration order, so every
# literal two-segment path below must be declared before
# `/compliance/{awc_code}/{day}` at the bottom of this file -- otherwise `{day}`
# matches "trend" and "follow-ups" and rejects them as invalid dates.

OVERSIGHT = (Role.DISTRICT_OFFICIAL, Role.STATE_ADMIN)


@router.get("/compliance/flagged", dependencies=[Depends(require_role(*OVERSIGHT))])
async def flagged_queue(
    session: ScopedSession,
    principal: CurrentPrincipal,
    since: date | None = None,
    until: date | None = None,
    include_resolved: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    """The follow-up queue: flagged days with their current follow-up state.

    Defaults to a 30-day window and to outstanding items only, because the
    question an officer opens this with is "what still needs me".
    """
    window_start = since or (date.today() - timedelta(days=worklist.DEFAULT_WINDOW_DAYS))
    items = await worklist.flagged_days(
        session,
        district=principal.district,
        since=window_start,
        until=until,
        include_resolved=include_resolved,
        limit=limit,
    )
    return {
        "since": window_start.isoformat(),
        "until": until.isoformat() if until else None,
        "include_resolved": include_resolved,
        "items": items,
    }


@router.get("/compliance/quiet-centres", dependencies=[Depends(require_role(*OVERSIGHT))])
async def quiet_centres(
    session: ScopedSession,
    principal: CurrentPrincipal,
    days: int = Query(default=3, ge=1, le=60),
) -> dict:
    """Centres that have stopped uploading.

    Silence is indistinguishable from compliance unless something looks for it.
    """
    return {
        "days": days,
        "items": await worklist.centres_gone_quiet(session, district=principal.district, days=days),
    }


@router.get("/compliance/{awc_code}/trend", dependencies=[Depends(require_role(*OVERSIGHT))])
async def centre_trend(
    awc_code: str,
    session: ScopedSession,
    since: date | None = None,
) -> dict:
    """One centre's compliance day by day (Section 9.2's per-AWC trend)."""
    points = await worklist.centre_compliance_trend(session, awc_code=awc_code, since=since)
    if not points:
        # Empty because RLS removed the rows, or because the centre has no
        # record. Indistinguishable on purpose, as everywhere else.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no data for centre")
    return {"awc_code": awc_code, "points": points}


@router.get(
    "/reports/district/{district}/children", dependencies=[Depends(require_role(*OVERSIGHT))]
)
async def district_children(
    district: str,
    session: ScopedSession,
    classification: list[str] = Query(default=["SAM", "MAM"]),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    """Children whose latest measurement puts them in a given category.

    The referral list. Scored on the same basis as every prevalence figure, so
    the count on one screen and the list on another cannot disagree.
    """
    allowed = {"SAM", "MAM", "stunted", "underweight", "normal"}
    unknown = set(classification) - allowed
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown classification(s): {sorted(unknown)}")
    items = await worklist.children_needing_referral(
        session, district=district, classifications=classification, limit=limit
    )
    return {"district": district, "classification": classification, "items": items}


class FollowUpIn(BaseModel):
    outcome: str = Field(description=f"One of {OUTCOMES}")
    note: str | None = None


@router.post(
    "/compliance/{compliance_id}/follow-up",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(Role.DISTRICT_OFFICIAL))],
)
async def record_follow_up(
    compliance_id: uuid.UUID,
    payload: FollowUpIn,
    session: ScopedSession,
    principal: CurrentPrincipal,
) -> dict:
    """Record what was done about a flagged day.

    Append-only: this never edits the flag or a previous follow-up. Several may
    exist for one day, and that sequence is the trail.

    District officials only. A state admin recording a follow-up would be
    claiming to have visited a centre they did not, and the RLS policy in
    migration 0003 refuses it independently of this role gate.
    """
    if payload.outcome not in OUTCOMES:
        raise HTTPException(status_code=422, detail=f"outcome must be one of {OUTCOMES}")

    # Checked here as well as by the CHECK constraint in migration 0003. The
    # constraint is the guarantee; this is the message. Without it the officer
    # gets a 500 and no indication that what is missing is a one-line reason --
    # and "no action needed" is precisely the outcome where the next person to
    # read the record needs to know why the flag was overruled.
    if payload.outcome == "no_action_needed" and not (payload.note or "").strip():
        raise HTTPException(
            status_code=422,
            detail="a note is required when recording 'no_action_needed': "
            "say why the flag did not need acting on",
        )

    flagged = (
        await session.execute(select(MenuCompliance).where(MenuCompliance.id == compliance_id))
    ).scalar_one_or_none()
    if flagged is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such record")
    if not flagged.flagged:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="that day was not flagged; there is nothing to follow up",
        )

    row = FollowUp(
        compliance_id=flagged.id,
        awc_code=flagged.awc_code,
        district=flagged.district,
        outcome=payload.outcome,
        note=(payload.note or None),
        recorded_by=uuid.UUID(principal.worker_id) if principal.worker_id else None,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return {
        "id": str(row.id),
        "compliance_id": str(row.compliance_id),
        "outcome": row.outcome,
        "note": row.note,
        "recorded_at": row.recorded_at.isoformat(),
    }


@router.get(
    "/compliance/{compliance_id}/follow-ups", dependencies=[Depends(require_role(*OVERSIGHT))]
)
async def follow_up_trail(compliance_id: uuid.UUID, session: ScopedSession) -> dict:
    """Every follow-up recorded against one flagged day, oldest first."""
    rows = (
        (
            await session.execute(
                select(FollowUp)
                .where(FollowUp.compliance_id == compliance_id)
                .order_by(FollowUp.recorded_at)
            )
        )
        .scalars()
        .all()
    )
    return {
        "compliance_id": str(compliance_id),
        "items": [
            {
                "id": str(r.id),
                "outcome": r.outcome,
                "note": r.note,
                "recorded_at": r.recorded_at.isoformat(),
            }
            for r in rows
        ],
    }


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
