"""Queries behind the District Dashboard's worklist (Section 9.2).

Section 9.2 asks for "per-AWC compliance trend, flagged days requiring
follow-up, growth-classification distribution across the block". The middle one
is the load-bearing item: it is the only thing on any surface in this system
that tells a specific person to do a specific thing on a specific day.

So the flagged-day query carries its follow-up state with it. A queue that
cannot show what has already been dealt with is a queue an officer opens twice
and then stops opening.

Everything runs under the RLS policies from migrations 0002 and 0003. No
function here filters by district for security -- the `district` parameter is
for labelling and for a state admin narrowing their own view.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.reports.aggregate import _scoped

#: Default window for the queue. Long enough that a fortnight's leave does not
#: hide anything, short enough that the list stays actionable.
DEFAULT_WINDOW_DAYS = 30


async def flagged_days(
    session: AsyncSession,
    *,
    district: str | None,
    since: date | None = None,
    until: date | None = None,
    include_resolved: bool = False,
    limit: int = 200,
) -> list[dict]:
    """Flagged compliance days, newest first, with their follow-up state.

    `include_resolved` is off by default so the queue shows outstanding work.
    An officer reviewing what was done needs the opposite, which is why it is a
    parameter rather than a hard filter.
    """
    resolved_filter = "" if include_resolved else "AND f.id IS NULL"
    sql = f"""
        SELECT m.id, m.awc_code, m.district, m.date,
               m.prescribed_items, m.detected_items, m.compliance_pct, m.flag_reason,
               a.name_en, a.name_hi, a.block, a.block_hi,
               f.id            AS follow_up_id,
               f.outcome       AS follow_up_outcome,
               f.note          AS follow_up_note,
               f.recorded_at   AS follow_up_at,
               w.name          AS follow_up_by
        FROM menu_compliance m
        JOIN awcs a ON a.awc_code = m.awc_code
        -- The most recent follow-up only. Earlier ones are the trail and are
        -- fetched per-day when an officer opens the record.
        LEFT JOIN LATERAL (
            SELECT fu.* FROM follow_ups fu
            WHERE fu.compliance_id = m.id
            ORDER BY fu.recorded_at DESC LIMIT 1
        ) f ON true
        LEFT JOIN field_workers w ON w.id = f.recorded_by
        WHERE m.flagged
          AND {_scoped("m.district")}
          AND (CAST(:since AS date) IS NULL OR m.date >= CAST(:since AS date))
          AND (CAST(:until AS date) IS NULL OR m.date <= CAST(:until AS date))
          {resolved_filter}
        ORDER BY m.date DESC, m.awc_code
        LIMIT :limit
    """
    rows = (
        await session.execute(
            text(sql),
            {"district": district, "since": since, "until": until, "limit": limit},
        )
    ).all()

    result = []
    for row in rows:
        data = dict(row._mapping)
        data["id"] = str(data["id"])
        data["date"] = data["date"].isoformat()
        data["compliance_pct"] = (
            float(data["compliance_pct"]) if data["compliance_pct"] is not None else None
        )
        data["follow_up_id"] = str(data["follow_up_id"]) if data["follow_up_id"] else None
        data["follow_up_at"] = data["follow_up_at"].isoformat() if data["follow_up_at"] else None
        # The stored reason is "English | Hindi"; split it so the UI does not
        # have to know the encoding.
        reason = data.pop("flag_reason") or ""
        english, _, hindi = reason.partition(" | ")
        data["flag_reason_en"] = english or None
        data["flag_reason_hi"] = hindi or None
        # Missing items are what the officer actually acts on.
        prescribed = set(data.get("prescribed_items") or [])
        detected = set(data.get("detected_items") or [])
        data["missing_items"] = sorted(prescribed - detected)
        result.append(data)
    return result


async def centre_compliance_trend(
    session: AsyncSession, *, awc_code: str, since: date | None = None
) -> list[dict]:
    """One centre's compliance day by day, for the per-AWC trend."""
    sql = """
        SELECT date, compliance_pct, flagged, prescribed_items, detected_items
        FROM menu_compliance
        WHERE awc_code = :awc_code
          AND (CAST(:since AS date) IS NULL OR date >= CAST(:since AS date))
        ORDER BY date
    """
    rows = (await session.execute(text(sql), {"awc_code": awc_code, "since": since})).all()
    return [
        {
            "date": r.date.isoformat(),
            "compliance_pct": float(r.compliance_pct) if r.compliance_pct is not None else None,
            "flagged": r.flagged,
            "prescribed": len(r.prescribed_items or []),
            "detected": len(r.detected_items or []),
        }
        for r in rows
    ]


async def children_needing_referral(
    session: AsyncSession, *, district: str | None, classifications: list[str], limit: int = 200
) -> list[dict]:
    """Children whose most recent measurement puts them in a given category.

    The referral list. Scored from the latest plausible measurement per child,
    the same basis as every prevalence figure elsewhere, so a Collector cannot
    be shown a count on one screen and a different list on another.
    """
    sql = f"""
        WITH latest AS (
            SELECT DISTINCT ON (g.beneficiary_id)
                   g.beneficiary_id, g.awc_code, g.district, g.recorded_at,
                   g.classification, g.classification_detail,
                   g.haz_score, g.whz_score, g.waz_score, g.baz_score,
                   g.height_cm, g.weight_kg, g.age_months
            FROM growth_entries g
            WHERE g.data_quality_flags = '[]'::jsonb
              AND {_scoped("g.district")}
            ORDER BY g.beneficiary_id, g.recorded_at DESC
        )
        SELECT l.*, b.name, b.gender, b.poshan_tracker_id,
               a.name_en AS centre_en, a.name_hi AS centre_hi, a.block
        FROM latest l
        JOIN beneficiaries b ON b.id = l.beneficiary_id
        JOIN awcs a ON a.awc_code = l.awc_code
        WHERE l.classification = ANY(:classifications)
        -- Most severe first, then longest since measured: an SAM child last
        -- seen six weeks ago is the top of anyone's list.
        ORDER BY CASE l.classification WHEN 'SAM' THEN 0 WHEN 'MAM' THEN 1 ELSE 2 END,
                 l.recorded_at ASC
        LIMIT :limit
    """
    rows = (
        await session.execute(
            text(sql),
            {"district": district, "classifications": classifications, "limit": limit},
        )
    ).all()

    result = []
    for row in rows:
        data = dict(row._mapping)
        data["beneficiary_id"] = str(data["beneficiary_id"])
        data["recorded_at"] = data["recorded_at"].isoformat()
        for key in ("haz_score", "whz_score", "waz_score", "baz_score", "height_cm", "weight_kg"):
            data[key] = float(data[key]) if data[key] is not None else None
        result.append(data)
    return result


async def centres_gone_quiet(
    session: AsyncSession, *, district: str | None, days: int = 3
) -> list[dict]:
    """Centres that have stopped uploading.

    Not in Section 9.2's list, but it belongs in a worklist: a centre with no
    captures is invisible to every other view on this page, and silence is
    indistinguishable from compliance unless something looks for it. Section 7
    treats connectivity as the likeliest failure point, so this is as often a
    broken phone as a broken kitchen -- either way it is the officer's problem.
    """
    sql = f"""
        SELECT a.awc_code, a.name_en, a.name_hi, a.block, a.district,
               max(p.captured_at) AS last_capture,
               count(p.id)        AS total_captures
        FROM awcs a
        LEFT JOIN plate_captures p ON p.awc_code = a.awc_code
        WHERE {_scoped("a.district")}
        GROUP BY a.awc_code
        HAVING max(p.captured_at) IS NULL
            OR max(p.captured_at) < now() - make_interval(days => :days)
        ORDER BY max(p.captured_at) NULLS FIRST
    """
    rows = (await session.execute(text(sql), {"district": district, "days": days})).all()
    return [
        {
            **dict(r._mapping),
            "last_capture": r.last_capture.isoformat() if r.last_capture else None,
        }
        for r in rows
    ]
