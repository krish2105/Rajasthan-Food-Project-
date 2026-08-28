"""Aggregation for the district and state report surfaces (Section 8).

All arithmetic happens in SQL, under the row-level security policies from
migration 0002. That is the point: a district official who calls the state
report gets their own district's numbers, because the policies filter the rows
before any aggregate touches them. There is no separate authorisation check to
forget, and no second implementation of prevalence in a browser that could
disagree with this one.

Two things this module is careful about, both because the output goes in front
of government reviewers:

**Prevalence is computed from each child's most recent measurement**, not from
every row ever recorded. Averaging across visits would let a child measured six
times outweigh one measured once, which quietly overstates whichever cohort was
monitored most closely.

**Measurements WHO flags as implausible are excluded.** Phase 1 records them
rather than rejecting them (a transposed digit is still evidence that something
was entered), but a prevalence figure built on a 9-SD height is not a figure
anyone should quote.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: Histogram bins for the z-score distribution, in SD. Half-SD resolution is
#: fine enough to show the shape and coarse enough that 120 children do not
#: produce a comb.
DIST_MIN, DIST_MAX, DIST_STEP = -6.0, 4.0, 0.5

#: The district parameter, cast explicitly.
#:
#: Not decoration: asyncpg infers a parameter's type from how it is used, and
#: one appearing only in `$1 IS NULL` gives it nothing to infer from -- it
#: raises AmbiguousParameterError rather than guessing.
_D = "CAST(:district AS text)"


def _scoped(column: str = "district") -> str:
    """The optional district filter.

    A *labelling* filter, not the security boundary. RLS has already removed
    rows the caller may not see, so passing NULL from a district official's
    session still returns only their district. This exists so one statement can
    serve both the state and district reports.
    """
    return f"({_D} IS NULL OR {column} = {_D})"


#: One row per child: their most recent plausible measurement.
LATEST_CTE = f"""
    WITH latest AS (
        SELECT DISTINCT ON (g.beneficiary_id)
               g.beneficiary_id, g.awc_code, g.district, g.recorded_at,
               g.haz_score, g.whz_score, g.waz_score, g.baz_score,
               g.classification, g.classification_detail, g.standard_used
        FROM growth_entries g
        WHERE g.data_quality_flags = '[]'::jsonb
          AND {_scoped("g.district")}
        ORDER BY g.beneficiary_id, g.recorded_at DESC
    )
"""

_STUNTED = "classification_detail->>'stunting' IN ('stunted','severely_stunted')"
_UNDERWEIGHT = (
    "classification_detail->>'underweight' IN ('underweight','severely_underweight')"
)
_WASTED = (
    "classification_detail->>'wasting' "
    "IN ('moderate_acute_malnutrition','severe_acute_malnutrition') "
    "OR classification_detail->>'thinness' IN ('thinness','severe_thinness')"
)


@dataclass(frozen=True, slots=True)
class Scope:
    """What the caller is allowed to see, for labelling only."""

    label: str
    district: str | None = None


def _rate(numerator: int, denominator: int) -> float | None:
    """None rather than 0.0 when nothing is measured.

    A rate of zero reads as "no malnutrition here", which is a very different
    claim from "nobody has been measured yet".
    """
    return round(numerator / denominator, 4) if denominator else None


async def coverage(session: AsyncSession, district: str | None) -> dict:
    sql = f"""
        SELECT
          (SELECT count(DISTINCT district) FROM awcs WHERE {_scoped()}) AS districts,
          (SELECT count(*) FROM awcs WHERE {_scoped()})                 AS centres,
          (SELECT count(*) FROM beneficiaries WHERE {_scoped()})        AS children,
          (SELECT count(*) FROM plate_captures WHERE {_scoped()})       AS captures,
          (SELECT count(*) FROM growth_entries WHERE {_scoped()})       AS growth_entries
    """
    row = (await session.execute(text(sql), {"district": district})).one()
    return dict(row._mapping)


async def prevalence(session: AsyncSession, district: str | None) -> dict:
    """Stunting, wasting and underweight from each child's latest measurement.

    Read off `classification_detail` rather than the coarse `classification`
    column, because a child can be stunted and underweight at once and the
    single column reports only the most severe. Summing the coarse column would
    undercount every condition except the worst one present.
    """
    sql = LATEST_CTE + f"""
        SELECT
          count(*)                                                   AS measured,
          count(*) FILTER (WHERE {_STUNTED})                         AS stunted,
          count(*) FILTER (WHERE classification_detail->>'stunting'
                           = 'severely_stunted')                     AS severely_stunted,
          count(*) FILTER (WHERE {_UNDERWEIGHT})                     AS underweight,
          count(*) FILTER (WHERE classification_detail->>'underweight'
                           = 'severely_underweight')                 AS severely_underweight,
          count(*) FILTER (WHERE {_WASTED})                          AS wasted,
          count(*) FILTER (WHERE classification = 'SAM')             AS sam,
          count(*) FILTER (WHERE classification = 'MAM')             AS mam,
          count(*) FILTER (WHERE standard_used = 'who_2006_0_60m')   AS under_five,
          count(*) FILTER (WHERE standard_used = 'who_2007_5_19y')   AS school_age
        FROM latest
    """
    row = (await session.execute(text(sql), {"district": district})).one()
    data = dict(row._mapping)
    measured = data["measured"] or 0
    data["stunting_rate"] = _rate(data["stunted"], measured)
    data["underweight_rate"] = _rate(data["underweight"], measured)
    data["wasting_rate"] = _rate(data["wasted"], measured)
    data["sam_rate"] = _rate(data["sam"], measured)
    return data


async def distribution(
    session: AsyncSession, district: str | None, index: str = "haz"
) -> dict:
    """Histogram of z-scores for one index, plus the cohort mean.

    This is what the pitch surface leads with. A prevalence percentage says how
    many children fall past a threshold; the distribution shows the whole cohort
    sitting left of the WHO reference population, which is the actual finding
    and much harder to argue with.
    """
    column = {
        "haz": "haz_score",
        "whz": "whz_score",
        "waz": "waz_score",
        "baz": "baz_score",
    }[index]
    buckets = int((DIST_MAX - DIST_MIN) / DIST_STEP)

    sql = LATEST_CTE + f"""
        SELECT width_bucket({column}, :lo, :hi, :buckets) AS bucket, count(*) AS n
        FROM latest WHERE {column} IS NOT NULL
        GROUP BY bucket ORDER BY bucket
    """
    rows = (
        await session.execute(
            text(sql),
            {"district": district, "lo": DIST_MIN, "hi": DIST_MAX, "buckets": buckets},
        )
    ).all()
    counts = {int(r.bucket): int(r.n) for r in rows}

    bins = [
        {"z": round(DIST_MIN + (i - 1) * DIST_STEP, 2), "count": counts.get(i, 0)}
        for i in range(1, buckets + 1)
    ]
    # width_bucket returns 0 and n+1 for out-of-range values. Folding those into
    # the end bins rather than dropping them keeps the histogram total equal to
    # the measured count -- otherwise the most severe children, who are exactly
    # the ones in the tail, would silently vanish from the chart.
    if bins:
        bins[0]["count"] += counts.get(0, 0)
        bins[-1]["count"] += counts.get(buckets + 1, 0)

    mean_sql = LATEST_CTE + f"SELECT avg({column}) AS mean_z, count({column}) AS n FROM latest"
    mean_row = (await session.execute(text(mean_sql), {"district": district})).one()

    return {
        "index": index,
        "bins": bins,
        "mean_z": round(float(mean_row.mean_z), 3) if mean_row.mean_z is not None else None,
        "n": int(mean_row.n or 0),
        "bin_width": DIST_STEP,
    }


async def centres(session: AsyncSession, district: str | None) -> list[dict]:
    """Per-centre rollup, including coordinates for the map."""
    sql = LATEST_CTE + f"""
        SELECT a.awc_code, a.name_en, a.name_hi, a.centre_type,
               a.district, a.district_hi, a.block, a.block_hi,
               a.latitude, a.longitude,
               (SELECT count(*) FROM beneficiaries b
                 WHERE b.awc_code = a.awc_code)                 AS children,
               count(l.beneficiary_id)                          AS measured,
               count(*) FILTER (WHERE {_STUNTED})               AS stunted,
               count(*) FILTER (WHERE l.classification = 'SAM') AS sam,
               (SELECT count(*) FROM menu_compliance m
                 WHERE m.awc_code = a.awc_code)                 AS menu_days,
               (SELECT count(*) FROM menu_compliance m
                 WHERE m.awc_code = a.awc_code AND m.flagged)   AS flagged_days,
               (SELECT round(avg(m.compliance_pct), 1) FROM menu_compliance m
                 WHERE m.awc_code = a.awc_code)                 AS compliance_pct,
               (SELECT count(*) FROM plate_captures p
                 WHERE p.awc_code = a.awc_code)                 AS captures
        FROM awcs a
        LEFT JOIN latest l ON l.awc_code = a.awc_code
        WHERE {_scoped("a.district")}
        GROUP BY a.awc_code
        ORDER BY a.district, a.awc_code
    """
    rows = (await session.execute(text(sql), {"district": district})).all()

    result = []
    for r in rows:
        data = dict(r._mapping)
        data["stunting_rate"] = _rate(data["stunted"], data["measured"] or 0)
        for key in ("latitude", "longitude", "compliance_pct"):
            data[key] = float(data[key]) if data[key] is not None else None
        result.append(data)
    return result


async def trend(session: AsyncSession, district: str | None) -> list[dict]:
    """Month-by-month prevalence.

    Every measurement in each month counts, not just the latest, because the
    question here is what a month looked like rather than where a child stands
    today.
    """
    sql = f"""
        SELECT to_char(date_trunc('month', recorded_at), 'YYYY-MM') AS month,
               count(*)                              AS measured,
               count(*) FILTER (WHERE {_STUNTED})    AS stunted,
               count(*) FILTER (WHERE {_UNDERWEIGHT}) AS underweight,
               count(*) FILTER (WHERE classification = 'SAM') AS sam,
               round(avg(haz_score), 3)              AS mean_haz
        FROM growth_entries
        WHERE data_quality_flags = '[]'::jsonb AND {_scoped()}
        GROUP BY 1 ORDER BY 1
    """
    rows = (await session.execute(text(sql), {"district": district})).all()
    out = []
    for r in rows:
        data = dict(r._mapping)
        measured = data["measured"] or 0
        data["stunting_rate"] = _rate(data["stunted"], measured)
        data["underweight_rate"] = _rate(data["underweight"], measured)
        data["mean_haz"] = float(data["mean_haz"]) if data["mean_haz"] is not None else None
        out.append(data)
    return out


async def compliance_summary(session: AsyncSession, district: str | None) -> dict:
    """Menu compliance -- the Gadchiroli-precedent feature, in aggregate."""
    sql = f"""
        SELECT count(*) AS days,
               count(*) FILTER (WHERE flagged) AS flagged,
               round(avg(compliance_pct), 1)   AS mean_compliance_pct,
               min(date) AS first_day, max(date) AS last_day
        FROM menu_compliance WHERE {_scoped()}
    """
    row = (await session.execute(text(sql), {"district": district})).one()
    data = dict(row._mapping)
    data["flag_rate"] = _rate(data["flagged"], data["days"] or 0)
    data["mean_compliance_pct"] = (
        float(data["mean_compliance_pct"]) if data["mean_compliance_pct"] is not None else None
    )
    for key in ("first_day", "last_day"):
        data[key] = data[key].isoformat() if data[key] else None

    reasons_sql = f"""
        SELECT split_part(flag_reason, ' | ', 1) AS reason, count(*) AS n
        FROM menu_compliance
        WHERE flagged AND flag_reason IS NOT NULL AND {_scoped()}
        GROUP BY 1 ORDER BY n DESC LIMIT 5
    """
    reasons = (await session.execute(text(reasons_sql), {"district": district})).all()
    data["top_reasons"] = [{"reason": r.reason, "count": int(r.n)} for r in reasons]
    return data


async def data_quality(session: AsyncSession, district: str | None) -> dict:
    """What the reader should know before quoting anything above.

    `ai_is_mock` is the important field. Phase 2 defaults to an offline mock
    provider, and a pitch surface presenting mock nutrition estimates as
    measurements would be doing exactly what Section 15 asks us not to do. The
    flag travels with the report so the page can say so on itself.
    """
    sql = f"""
        SELECT
          (SELECT count(*) FROM growth_entries
            WHERE data_quality_flags <> '[]'::jsonb
              AND {_scoped()})                         AS flagged_measurements,
          (SELECT count(*) FROM plate_captures
            WHERE sync_status = 'synced' AND {_scoped()}) AS captures_analysed,
          (SELECT count(*) FROM plate_captures
            WHERE sync_status = 'pending' AND {_scoped()}) AS captures_pending,
          (SELECT count(*) FROM plate_captures
            WHERE ai_model_version LIKE 'mock%'
              AND {_scoped()})                         AS captures_from_mock
    """
    row = (await session.execute(text(sql), {"district": district})).one()
    data = dict(row._mapping)
    data["ai_is_mock"] = data["captures_from_mock"] > 0 or data["captures_analysed"] == 0
    return data


async def _period(session: AsyncSession, district: str | None) -> dict:
    sql = f"""
        SELECT min(recorded_at) AS first_measurement, max(recorded_at) AS last_measurement
        FROM growth_entries WHERE {_scoped()}
    """
    row = (await session.execute(text(sql), {"district": district})).one()
    return {
        "first_measurement": row.first_measurement.isoformat() if row.first_measurement else None,
        "last_measurement": row.last_measurement.isoformat() if row.last_measurement else None,
        "generated_on": date.today().isoformat(),
    }


async def build_report(session: AsyncSession, scope: Scope) -> dict:
    """Assemble one report. Serves both the state and district surfaces."""
    district = scope.district
    return {
        "scope": scope.label,
        "district": district,
        "period": await _period(session, district),
        "coverage": await coverage(session, district),
        "prevalence": await prevalence(session, district),
        "distribution": await distribution(session, district, "haz"),
        "centres": await centres(session, district),
        "trend": await trend(session, district),
        "compliance": await compliance_summary(session, district),
        "data_quality": await data_quality(session, district),
    }
