"""District and state reporting.

Two things matter here and they are different. The prevalence arithmetic has to
be right, because these numbers go in front of government reviewers. And the
scoping has to hold *through the aggregation* -- a SUM over rows a caller may
not see would leak the shape of another district's data even without returning
a single row of it.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import insert

from app.db.models import GrowthEntry, MenuCompliance
from app.db.session import admin_session


async def _growth(
    child_id, awc, district, *, recorded_at, detail, classification="normal", haz=-1.0, flags=None
):
    async with admin_session() as session:
        async with session.begin():
            await session.execute(
                insert(GrowthEntry),
                [
                    dict(
                        id=uuid.uuid4(),
                        beneficiary_id=child_id,
                        awc_code=awc,
                        district=district,
                        recorded_at=recorded_at,
                        height_cm=88,
                        weight_kg=11,
                        age_months=36,
                        standard_used="who_2006_0_60m",
                        haz_score=haz,
                        whz_score=-1.0,
                        waz_score=-1.0,
                        classification=classification,
                        classification_detail=detail,
                        data_quality_flags=flags or [],
                    )
                ],
            )


NORMAL = {"wasting": "normal", "thinness": None, "stunting": "normal", "underweight": "normal"}
STUNTED = {
    "wasting": "normal",
    "thinness": None,
    "stunting": "stunted",
    "underweight": "underweight",
}
SAM = {
    "wasting": "severe_acute_malnutrition",
    "thinness": None,
    "stunting": "severely_stunted",
    "underweight": "severely_underweight",
}


# --------------------------------------------------------------------------
# Scoping -- the security property
# --------------------------------------------------------------------------


async def test_state_report_is_state_admin_only(client, fixtures, auth) -> None:
    for phone in ("5550000001", "5550000010"):
        r = await client.get("/reports/state", headers=auth(fixtures["workers"][phone]))
        assert r.status_code == 403


async def test_field_workers_cannot_see_compliance(client, fixtures, auth) -> None:
    """A flag against their own kitchen, in an app used while cooking, changes
    what gets photographed. It is for the officer who follows it up."""
    r = await client.get(
        "/compliance/TEST-A1/2026-08-26", headers=auth(fixtures["workers"]["5550000001"])
    )
    assert r.status_code == 403


async def test_district_official_aggregates_only_their_district(client, fixtures, auth) -> None:
    """The route passes no district filter of its own -- RLS removes the rows
    before the aggregate runs. This is what makes that claim checkable."""
    child_a = fixtures["children"]["PT-A1-0001"]["id"]
    child_b = fixtures["children"]["PT-B1-0001"]["id"]
    today = date.today()
    await _growth(
        child_a, "TEST-A1", "Banswara", recorded_at=today, detail=STUNTED, classification="stunted"
    )
    await _growth(child_b, "TEST-B1", "Dungarpur", recorded_at=today, detail=NORMAL)

    r = await client.get(
        "/reports/district/Banswara", headers=auth(fixtures["workers"]["5550000010"])
    )
    assert r.status_code == 200
    body = r.json()
    assert body["coverage"]["children"] == 3  # TEST-A1 x2 + TEST-A2 x1
    assert body["prevalence"]["measured"] == 1
    assert body["prevalence"]["stunted"] == 1


async def test_asking_for_another_district_is_404_not_that_district(client, fixtures, auth) -> None:
    """RLS empties the report; reporting 404 keeps it indistinguishable from a
    district that does not exist, matching the beneficiary rule."""
    r = await client.get(
        "/reports/district/Dungarpur", headers=auth(fixtures["workers"]["5550000010"])
    )
    assert r.status_code == 404


async def test_state_admin_sees_every_district(client, fixtures, auth) -> None:
    r = await client.get("/reports/state", headers=auth(fixtures["workers"]["5550000020"]))
    body = r.json()
    assert body["coverage"]["districts"] == 2
    assert body["coverage"]["centres"] == 3


# --------------------------------------------------------------------------
# Prevalence arithmetic
# --------------------------------------------------------------------------


async def test_prevalence_uses_the_latest_measurement_per_child(client, fixtures, auth) -> None:
    """Averaging across visits would let a child measured six times outweigh
    one measured once, overstating whichever cohort was watched most closely."""
    child = fixtures["children"]["PT-A1-0001"]["id"]
    today = date.today()
    await _growth(
        child,
        "TEST-A1",
        "Banswara",
        recorded_at=today - timedelta(days=60),
        detail=SAM,
        classification="SAM",
    )
    await _growth(child, "TEST-A1", "Banswara", recorded_at=today, detail=NORMAL)

    body = (
        await client.get("/reports/state", headers=auth(fixtures["workers"]["5550000020"]))
    ).json()
    assert body["prevalence"]["measured"] == 1
    assert body["prevalence"]["sam"] == 0, "the older SAM reading must not count today"


async def test_implausible_measurements_are_excluded(client, fixtures, auth) -> None:
    """Phase 1 records them for audit; a prevalence figure built on a 9-SD
    height is not one anyone should quote."""
    child = fixtures["children"]["PT-A1-0001"]["id"]
    await _growth(
        child,
        "TEST-A1",
        "Banswara",
        recorded_at=date.today(),
        detail=SAM,
        classification="SAM",
        haz=9.3,
        flags=["haz"],
    )
    body = (
        await client.get("/reports/state", headers=auth(fixtures["workers"]["5550000020"]))
    ).json()
    assert body["prevalence"]["measured"] == 0
    assert body["data_quality"]["flagged_measurements"] == 1


async def test_conditions_are_counted_independently(client, fixtures, auth) -> None:
    """A child can be stunted AND underweight. Summing the coarse
    `classification` column would count only the most severe and undercount
    every other condition present."""
    child = fixtures["children"]["PT-A1-0001"]["id"]
    await _growth(
        child,
        "TEST-A1",
        "Banswara",
        recorded_at=date.today(),
        detail=STUNTED,
        classification="stunted",
    )
    body = (
        await client.get("/reports/state", headers=auth(fixtures["workers"]["5550000020"]))
    ).json()
    prevalence = body["prevalence"]
    assert prevalence["stunted"] == 1
    assert prevalence["underweight"] == 1, "underweight must not be hidden by 'stunted'"


async def test_rates_are_null_not_zero_when_nothing_is_measured(client, fixtures, auth) -> None:
    """A rate of zero reads as 'no malnutrition here', which is a very
    different claim from 'nobody has been measured yet'."""
    body = (
        await client.get("/reports/state", headers=auth(fixtures["workers"]["5550000020"]))
    ).json()
    assert body["prevalence"]["measured"] == 0
    assert body["prevalence"]["stunting_rate"] is None


# --------------------------------------------------------------------------
# The distribution -- what the pitch surface leads with
# --------------------------------------------------------------------------


async def test_distribution_bins_span_the_full_range(client, fixtures, auth) -> None:
    body = (
        await client.get("/reports/state", headers=auth(fixtures["workers"]["5550000020"]))
    ).json()
    dist = body["distribution"]
    assert dist["index"] == "haz"
    assert dist["bins"][0]["z"] == -6.0
    assert dist["bins"][-1]["z"] == 3.5
    assert dist["bin_width"] == 0.5


async def test_distribution_counts_total_to_the_measured_count(client, fixtures, auth) -> None:
    """Out-of-range values are folded into the end bins rather than dropped, so
    a histogram cannot silently lose the most severe children -- who are
    precisely the ones sitting in the tail."""
    child_a = fixtures["children"]["PT-A1-0001"]["id"]
    child_b = fixtures["children"]["PT-A1-0002"]["id"]
    today = date.today()
    await _growth(child_a, "TEST-A1", "Banswara", recorded_at=today, detail=NORMAL, haz=-0.5)
    await _growth(
        child_b,
        "TEST-A1",
        "Banswara",
        recorded_at=today,
        detail=SAM,
        classification="SAM",
        haz=-5.9,
    )

    body = (
        await client.get("/reports/state", headers=auth(fixtures["workers"]["5550000020"]))
    ).json()
    dist = body["distribution"]
    assert sum(b["count"] for b in dist["bins"]) == dist["n"] == 2


async def test_distribution_reports_the_cohort_mean(client, fixtures, auth) -> None:
    child_a = fixtures["children"]["PT-A1-0001"]["id"]
    child_b = fixtures["children"]["PT-A1-0002"]["id"]
    today = date.today()
    await _growth(child_a, "TEST-A1", "Banswara", recorded_at=today, detail=NORMAL, haz=-1.0)
    await _growth(child_b, "TEST-A1", "Banswara", recorded_at=today, detail=NORMAL, haz=-3.0)
    body = (
        await client.get("/reports/state", headers=auth(fixtures["workers"]["5550000020"]))
    ).json()
    assert body["distribution"]["mean_z"] == pytest.approx(-2.0, abs=0.01)


# --------------------------------------------------------------------------
# Centres, compliance, honesty
# --------------------------------------------------------------------------


async def test_centres_carry_coordinates_for_the_map(client, fixtures, auth) -> None:
    body = (
        await client.get("/reports/state", headers=auth(fixtures["workers"]["5550000020"]))
    ).json()
    for centre in body["centres"]:
        assert centre["latitude"] is not None and centre["longitude"] is not None
        assert centre["name_hi"], "the map labels must be available in Hindi"


async def test_a_centre_with_no_measurements_reports_null_not_zero(client, fixtures, auth) -> None:
    body = (
        await client.get("/reports/state", headers=auth(fixtures["workers"]["5550000020"]))
    ).json()
    assert all(c["stunting_rate"] is None for c in body["centres"])


async def test_compliance_summary_counts_flagged_days(client, fixtures, auth) -> None:
    async with admin_session() as session:
        async with session.begin():
            await session.execute(
                insert(MenuCompliance),
                [
                    dict(
                        id=uuid.uuid4(),
                        awc_code="TEST-A1",
                        district="Banswara",
                        date=date(2026, 8, 24),
                        prescribed_items=["dal", "roti"],
                        detected_items=["dal", "roti"],
                        compliance_pct=100,
                        flagged=False,
                    ),
                    dict(
                        id=uuid.uuid4(),
                        awc_code="TEST-A1",
                        district="Banswara",
                        date=date(2026, 8, 25),
                        prescribed_items=["dal", "roti"],
                        detected_items=["dal"],
                        compliance_pct=50,
                        flagged=True,
                        flag_reason="Prescribed 2 items, 1 served | निर्धारित 2 में से 1",
                    ),
                ],
            )
    body = (
        await client.get("/reports/state", headers=auth(fixtures["workers"]["5550000020"]))
    ).json()
    compliance = body["compliance"]
    assert compliance["days"] == 2
    assert compliance["flagged"] == 1
    assert compliance["flag_rate"] == 0.5
    assert compliance["top_reasons"][0]["reason"] == "Prescribed 2 items, 1 served"


async def test_report_declares_whether_the_ai_output_is_mock(client, fixtures, auth) -> None:
    """The load-bearing honesty field. Phase 2 defaults to an offline mock
    provider, and a pitch surface presenting mock nutrition estimates as
    measurements is exactly what Section 15 asks us not to do. The flag travels
    with the report so the page can say so."""
    body = (
        await client.get("/reports/state", headers=auth(fixtures["workers"]["5550000020"]))
    ).json()
    assert body["data_quality"]["ai_is_mock"] is True


async def test_compliance_detail_returns_both_item_lists(client, fixtures, auth) -> None:
    async with admin_session() as session:
        async with session.begin():
            await session.execute(
                insert(MenuCompliance),
                [
                    dict(
                        id=uuid.uuid4(),
                        awc_code="TEST-A1",
                        district="Banswara",
                        date=date(2026, 8, 25),
                        prescribed_items=["dal", "roti", "sabzi"],
                        detected_items=["dal", "roti"],
                        compliance_pct=66.67,
                        flagged=True,
                        flag_reason="Prescribed 3 items, 2 served | निर्धारित 3 में से 2",
                    )
                ],
            )
    r = await client.get(
        "/compliance/TEST-A1/2026-08-25", headers=auth(fixtures["workers"]["5550000010"])
    )
    body = r.json()
    assert body["prescribed_items"] == ["dal", "roti", "sabzi"]
    assert body["detected_items"] == ["dal", "roti"]
    assert body["flagged"] is True
    assert " | " in body["flag_reason"], "flag reasons stay bilingual"


async def test_unknown_compliance_day_is_404(client, fixtures, auth) -> None:
    r = await client.get(
        "/compliance/TEST-A1/2020-01-01", headers=auth(fixtures["workers"]["5550000010"])
    )
    assert r.status_code == 404


async def test_scope_endpoint_tells_the_ui_what_it_may_show(client, fixtures, auth) -> None:
    admin = (
        await client.get("/reports/scope", headers=auth(fixtures["workers"]["5550000020"]))
    ).json()
    official = (
        await client.get("/reports/scope", headers=auth(fixtures["workers"]["5550000010"]))
    ).json()
    assert admin["can_view_state"] is True and admin["district"] is None
    assert official["can_view_state"] is False and official["district"] == "Banswara"
