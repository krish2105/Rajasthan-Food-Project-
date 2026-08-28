"""The District Dashboard's worklist and follow-up trail (Sections 9.2, 15).

The flagged-day queue is the only place in this system that tells a specific
person to do a specific thing on a specific day, so these tests care about two
properties above all: an officer sees exactly their own district's outstanding
work, and what they record about it cannot later be rewritten.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import insert, text

from app.db.models import GrowthEntry, MenuCompliance
from app.db.session import admin_session

TODAY = date.today()
SAM_DETAIL = {
    "wasting": "severe_acute_malnutrition",
    "thinness": None,
    "stunting": "severely_stunted",
    "underweight": "severely_underweight",
}
NORMAL_DETAIL = {
    "wasting": "normal",
    "thinness": None,
    "stunting": "normal",
    "underweight": "normal",
}


async def add_compliance(awc, district, day, *, flagged, prescribed, detected, reason=None):
    row_id = uuid.uuid4()
    async with admin_session() as session:
        async with session.begin():
            await session.execute(
                insert(MenuCompliance),
                [
                    dict(
                        id=row_id,
                        awc_code=awc,
                        district=district,
                        date=day,
                        prescribed_items=prescribed,
                        detected_items=detected,
                        compliance_pct=round(100 * len(detected) / len(prescribed), 2),
                        flagged=flagged,
                        flag_reason=reason,
                    )
                ],
            )
    return row_id


async def add_growth(child_id, awc, district, *, classification, detail, when=None):
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
                        recorded_at=when or TODAY,
                        height_cm=88,
                        weight_kg=9,
                        age_months=36,
                        standard_used="who_2006_0_60m",
                        haz_score=-3.2,
                        whz_score=-3.4,
                        waz_score=-3.5,
                        classification=classification,
                        classification_detail=detail,
                        data_quality_flags=[],
                    )
                ],
            )


# --------------------------------------------------------------------------
# The queue
# --------------------------------------------------------------------------


async def test_queue_shows_only_outstanding_flags_by_default(client, fixtures, auth) -> None:
    await add_compliance(
        "TEST-A1",
        "Banswara",
        TODAY,
        flagged=True,
        prescribed=["dal", "roti", "banana"],
        detected=["dal", "roti"],
        reason="Prescribed 3 items, 2 served | निर्धारित 3 में से 2",
    )
    await add_compliance(
        "TEST-A1",
        "Banswara",
        TODAY - timedelta(days=1),
        flagged=False,
        prescribed=["dal", "roti"],
        detected=["dal", "roti"],
    )

    body = (
        await client.get("/compliance/flagged", headers=auth(fixtures["workers"]["5550000010"]))
    ).json()
    assert len(body["items"]) == 1
    assert body["items"][0]["missing_items"] == ["banana"]


async def test_queue_names_what_is_missing(client, fixtures, auth) -> None:
    """The officer acts on the gap, not on a percentage."""
    await add_compliance(
        "TEST-A1",
        "Banswara",
        TODAY,
        flagged=True,
        prescribed=["dal", "roti", "banana", "sabzi"],
        detected=["dal"],
        reason="Prescribed 4 items, 1 served | निर्धारित 4 में से 1",
    )
    body = (
        await client.get("/compliance/flagged", headers=auth(fixtures["workers"]["5550000010"]))
    ).json()
    assert body["items"][0]["missing_items"] == ["banana", "roti", "sabzi"]


async def test_queue_splits_the_bilingual_flag_reason(client, fixtures, auth) -> None:
    """Stored as 'English | Hindi'; the UI should not have to know that."""
    await add_compliance(
        "TEST-A1",
        "Banswara",
        TODAY,
        flagged=True,
        prescribed=["dal", "roti"],
        detected=["dal"],
        reason="Prescribed 2 items, 1 served | निर्धारित 2 में से 1",
    )
    item = (
        await client.get("/compliance/flagged", headers=auth(fixtures["workers"]["5550000010"]))
    ).json()["items"][0]
    assert item["flag_reason_en"] == "Prescribed 2 items, 1 served"
    assert item["flag_reason_hi"] == "निर्धारित 2 में से 1"


async def test_queue_is_scoped_to_the_officers_district(client, fixtures, auth) -> None:
    """RLS filters the rows; the route passes no district of its own."""
    await add_compliance(
        "TEST-A1",
        "Banswara",
        TODAY,
        flagged=True,
        prescribed=["dal", "roti"],
        detected=["dal"],
        reason="a | ब",
    )
    await add_compliance(
        "TEST-B1",
        "Dungarpur",
        TODAY,
        flagged=True,
        prescribed=["dal", "roti"],
        detected=["dal"],
        reason="b | ब",
    )

    banswara = (
        await client.get("/compliance/flagged", headers=auth(fixtures["workers"]["5550000010"]))
    ).json()
    dungarpur = (
        await client.get("/compliance/flagged", headers=auth(fixtures["workers"]["5550000011"]))
    ).json()
    assert {i["awc_code"] for i in banswara["items"]} == {"TEST-A1"}
    assert {i["awc_code"] for i in dungarpur["items"]} == {"TEST-B1"}


async def test_state_admin_sees_every_district_in_the_queue(client, fixtures, auth) -> None:
    await add_compliance(
        "TEST-A1",
        "Banswara",
        TODAY,
        flagged=True,
        prescribed=["dal", "roti"],
        detected=["dal"],
        reason="a | ब",
    )
    await add_compliance(
        "TEST-B1",
        "Dungarpur",
        TODAY,
        flagged=True,
        prescribed=["dal", "roti"],
        detected=["dal"],
        reason="b | ब",
    )
    body = (
        await client.get("/compliance/flagged", headers=auth(fixtures["workers"]["5550000020"]))
    ).json()
    assert len(body["items"]) == 2


async def test_field_workers_cannot_see_the_queue(client, fixtures, auth) -> None:
    """A flag against their own kitchen, in an app used while cooking, changes
    what gets photographed."""
    r = await client.get("/compliance/flagged", headers=auth(fixtures["workers"]["5550000001"]))
    assert r.status_code == 403


async def test_queue_window_defaults_to_thirty_days(client, fixtures, auth) -> None:
    await add_compliance(
        "TEST-A1",
        "Banswara",
        TODAY - timedelta(days=90),
        flagged=True,
        prescribed=["dal", "roti"],
        detected=["dal"],
        reason="old | पुराना",
    )
    body = (
        await client.get("/compliance/flagged", headers=auth(fixtures["workers"]["5550000010"]))
    ).json()
    assert body["items"] == []
    wide = (
        await client.get(
            f"/compliance/flagged?since={(TODAY - timedelta(days=120)).isoformat()}",
            headers=auth(fixtures["workers"]["5550000010"]),
        )
    ).json()
    assert len(wide["items"]) == 1


# --------------------------------------------------------------------------
# Follow-ups
# --------------------------------------------------------------------------


async def test_recording_a_follow_up_clears_the_item_from_the_queue(client, fixtures, auth) -> None:
    """A queue with no way to clear an item is a queue nobody opens twice."""
    compliance_id = await add_compliance(
        "TEST-A1",
        "Banswara",
        TODAY,
        flagged=True,
        prescribed=["dal", "roti"],
        detected=["dal"],
        reason="a | ब",
    )
    headers = auth(fixtures["workers"]["5550000010"])

    created = await client.post(
        f"/compliance/{compliance_id}/follow-up",
        headers=headers,
        json={"outcome": "visited", "note": "Spoke to the cook; supply chased."},
    )
    assert created.status_code == 201

    outstanding = (await client.get("/compliance/flagged", headers=headers)).json()
    assert outstanding["items"] == []

    everything = (
        await client.get("/compliance/flagged?include_resolved=true", headers=headers)
    ).json()
    assert everything["items"][0]["follow_up_outcome"] == "visited"
    assert everything["items"][0]["follow_up_by"] == "Official Banswara"


async def test_follow_ups_are_append_only(client, fixtures, auth) -> None:
    """A correction is another row. For a record of what an official did about
    a flagged kitchen, a history that can be rewritten is worth less than none."""
    compliance_id = await add_compliance(
        "TEST-A1",
        "Banswara",
        TODAY,
        flagged=True,
        prescribed=["dal", "roti"],
        detected=["dal"],
        reason="a | ब",
    )
    headers = auth(fixtures["workers"]["5550000010"])

    await client.post(
        f"/compliance/{compliance_id}/follow-up",
        headers=headers,
        json={"outcome": "contacted", "note": "Called the supervisor."},
    )
    await client.post(
        f"/compliance/{compliance_id}/follow-up",
        headers=headers,
        json={"outcome": "escalated", "note": "No response; escalated to block."},
    )

    trail = (await client.get(f"/compliance/{compliance_id}/follow-ups", headers=headers)).json()
    assert [f["outcome"] for f in trail["items"]] == ["contacted", "escalated"]


async def test_the_database_refuses_to_update_or_delete_a_follow_up(client, fixtures, auth) -> None:
    """Append-only is enforced by the absence of a policy, not by convention."""
    from sqlalchemy.exc import ProgrammingError

    from app.core.principal import Principal, Role
    from app.db.session import apply_claims, get_sessionmaker

    compliance_id = await add_compliance(
        "TEST-A1",
        "Banswara",
        TODAY,
        flagged=True,
        prescribed=["dal", "roti"],
        detected=["dal"],
        reason="a | ब",
    )
    await client.post(
        f"/compliance/{compliance_id}/follow-up",
        headers=auth(fixtures["workers"]["5550000010"]),
        json={"outcome": "visited", "note": "Visited."},
    )

    principal = Principal(
        worker_id=str(uuid.uuid4()), role=Role.DISTRICT_OFFICIAL, awc_code=None, district="Banswara"
    )
    for statement in ("UPDATE follow_ups SET note = 'rewritten'", "DELETE FROM follow_ups"):
        with pytest.raises(ProgrammingError):
            async with get_sessionmaker()() as session:
                async with session.begin():
                    await apply_claims(session, principal)
                    await session.execute(text(statement))


async def test_a_state_admin_cannot_record_a_follow_up(client, fixtures, auth) -> None:
    """They did not visit the centre. Recording one would claim they had."""
    compliance_id = await add_compliance(
        "TEST-A1",
        "Banswara",
        TODAY,
        flagged=True,
        prescribed=["dal", "roti"],
        detected=["dal"],
        reason="a | ब",
    )
    r = await client.post(
        f"/compliance/{compliance_id}/follow-up",
        headers=auth(fixtures["workers"]["5550000020"]),
        json={"outcome": "visited"},
    )
    assert r.status_code == 403


async def test_an_officer_cannot_follow_up_another_district(client, fixtures, auth) -> None:
    compliance_id = await add_compliance(
        "TEST-A1",
        "Banswara",
        TODAY,
        flagged=True,
        prescribed=["dal", "roti"],
        detected=["dal"],
        reason="a | ब",
    )
    r = await client.post(
        f"/compliance/{compliance_id}/follow-up",
        headers=auth(fixtures["workers"]["5550000011"]),
        json={"outcome": "visited"},
    )
    assert r.status_code == 404


async def test_no_action_needed_requires_a_reason(client, fixtures, auth) -> None:
    """Overruling a flag is the one outcome where the next reader needs to know
    why. A 422 with a message, not a 500 from the CHECK constraint."""
    compliance_id = await add_compliance(
        "TEST-A1",
        "Banswara",
        TODAY,
        flagged=True,
        prescribed=["dal", "roti"],
        detected=["dal"],
        reason="a | ब",
    )
    r = await client.post(
        f"/compliance/{compliance_id}/follow-up",
        headers=auth(fixtures["workers"]["5550000010"]),
        json={"outcome": "no_action_needed"},
    )
    assert r.status_code == 422
    assert "note is required" in r.json()["code"]


async def test_cannot_follow_up_a_day_that_was_not_flagged(client, fixtures, auth) -> None:
    compliance_id = await add_compliance(
        "TEST-A1",
        "Banswara",
        TODAY,
        flagged=False,
        prescribed=["dal", "roti"],
        detected=["dal", "roti"],
    )
    r = await client.post(
        f"/compliance/{compliance_id}/follow-up",
        headers=auth(fixtures["workers"]["5550000010"]),
        json={"outcome": "visited"},
    )
    assert r.status_code == 409


async def test_unknown_outcomes_are_rejected(client, fixtures, auth) -> None:
    compliance_id = await add_compliance(
        "TEST-A1",
        "Banswara",
        TODAY,
        flagged=True,
        prescribed=["dal", "roti"],
        detected=["dal"],
        reason="a | ब",
    )
    r = await client.post(
        f"/compliance/{compliance_id}/follow-up",
        headers=auth(fixtures["workers"]["5550000010"]),
        json={"outcome": "handled_somehow"},
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------
# Referral list, centre trend, quiet centres
# --------------------------------------------------------------------------


async def test_referral_list_is_ordered_most_severe_first(client, fixtures, auth) -> None:
    """An SAM child last seen weeks ago is the top of anyone's list."""
    children = fixtures["children"]
    await add_growth(
        children["PT-A1-0001"]["id"],
        "TEST-A1",
        "Banswara",
        classification="MAM",
        detail=NORMAL_DETAIL,
    )
    await add_growth(
        children["PT-A1-0002"]["id"], "TEST-A1", "Banswara", classification="SAM", detail=SAM_DETAIL
    )

    body = (
        await client.get(
            "/reports/district/Banswara/children",
            headers=auth(fixtures["workers"]["5550000010"]),
        )
    ).json()
    assert [c["classification"] for c in body["items"]] == ["SAM", "MAM"]
    assert body["items"][0]["name"]


async def test_referral_list_is_district_scoped(client, fixtures, auth) -> None:
    await add_growth(
        fixtures["children"]["PT-B1-0001"]["id"],
        "TEST-B1",
        "Dungarpur",
        classification="SAM",
        detail=SAM_DETAIL,
    )
    body = (
        await client.get(
            "/reports/district/Banswara/children",
            headers=auth(fixtures["workers"]["5550000010"]),
        )
    ).json()
    assert body["items"] == []


async def test_referral_list_rejects_unknown_classifications(client, fixtures, auth) -> None:
    r = await client.get(
        "/reports/district/Banswara/children?classification=invented",
        headers=auth(fixtures["workers"]["5550000010"]),
    )
    assert r.status_code == 422


async def test_centre_trend_returns_days_in_order(client, fixtures, auth) -> None:
    for offset in (2, 1, 0):
        await add_compliance(
            "TEST-A1",
            "Banswara",
            TODAY - timedelta(days=offset),
            flagged=False,
            prescribed=["dal", "roti"],
            detected=["dal", "roti"],
        )
    body = (
        await client.get(
            "/compliance/TEST-A1/trend", headers=auth(fixtures["workers"]["5550000010"])
        )
    ).json()
    dates = [p["date"] for p in body["points"]]
    assert dates == sorted(dates)


async def test_centre_trend_for_another_district_is_404(client, fixtures, auth) -> None:
    """RLS empties it; 404 keeps that indistinguishable from a centre that does
    not exist, matching the rule everywhere else."""
    await add_compliance(
        "TEST-B1", "Dungarpur", TODAY, flagged=False, prescribed=["dal"], detected=["dal"]
    )
    r = await client.get(
        "/compliance/TEST-B1/trend", headers=auth(fixtures["workers"]["5550000010"])
    )
    assert r.status_code == 404


async def test_quiet_centres_surfaces_silence(client, fixtures, auth) -> None:
    """A centre with no captures is invisible to every other view, and silence
    is indistinguishable from compliance unless something looks for it."""
    body = (
        await client.get(
            "/compliance/quiet-centres", headers=auth(fixtures["workers"]["5550000010"])
        )
    ).json()
    codes = {c["awc_code"] for c in body["items"]}
    assert {"TEST-A1", "TEST-A2"} <= codes
    assert "TEST-B1" not in codes, "another district's centres must not appear"


async def test_route_literals_are_not_parsed_as_dates(client, fixtures, auth) -> None:
    """Regression: /compliance/{awc}/{day} was registered before the literal
    two-segment routes, so "trend" was matched as a date and rejected."""
    headers = auth(fixtures["workers"]["5550000010"])
    assert (await client.get("/compliance/flagged", headers=headers)).status_code == 200
    assert (await client.get("/compliance/quiet-centres", headers=headers)).status_code == 200
