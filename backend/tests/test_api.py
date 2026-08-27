"""End-to-end API behaviour: the role x route matrix, and the Phase 1 contracts.

These complement tests/test_rls.py rather than duplicating it. The RLS suite
proves the database refuses out-of-scope rows; this suite proves the API turns
that into the right status codes, the right bodies, and the right bilingual
payloads -- and that the growth endpoint computes a classification the client
never got to influence.
"""

from __future__ import annotations

import io
import uuid
from datetime import date, timedelta

import pytest
from PIL import Image

from app.storage import supabase_storage as storage


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
    """Storage is stubbed so the suite never touches the network or Supabase
    free-tier quota. The upload path itself is exercised; only the HTTP call is
    replaced."""
    uploaded: dict[str, bytes] = {}

    async def _upload(*, path, data, content_type, principal=None):
        if content_type not in storage.ALLOWED_CONTENT_TYPES:
            raise storage.StorageError(f"unsupported content type {content_type!r}")
        uploaded[path] = data
        return path

    async def _sign(*, path, principal=None, ttl=300):
        return f"https://stub.invalid/{path}?token=stub"

    monkeypatch.setattr(storage, "upload_photo", _upload)
    monkeypatch.setattr(storage, "create_signed_url", _sign)
    return uploaded


def _jpeg(colour=(200, 160, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), colour).save(buf, format="JPEG")
    return buf.getvalue()


# --------------------------------------------------------------------------
# Health and authentication
# --------------------------------------------------------------------------


async def test_health_is_open(client) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["phase"] == 1


async def test_health_db_reports_policy_count(client, fixtures) -> None:
    r = await client.get("/health/db")
    assert r.status_code == 200
    # If this is ever 0, RLS silently stopped protecting anything.
    assert r.json()["rls_policies"] > 0


async def test_dev_token_issues_a_scoped_token(client, fixtures) -> None:
    r = await client.post("/auth/dev/token", json={"phone": "5550000001"})
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "field_worker"
    assert body["awc_code"] == "TEST-A1"
    assert body["expires_in"] == 3600  # Section 11: short-lived


async def test_dev_token_rejects_unknown_phone(client, fixtures) -> None:
    assert (await client.post("/auth/dev/token", json={"phone": "0000000000"})).status_code == 404


async def test_dev_token_is_absent_in_production(client, fixtures, monkeypatch) -> None:
    """The only thing between a demo convenience and an auth bypass."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "production")
    r = await client.post("/auth/dev/token", json={"phone": "5550000001"})
    assert r.status_code == 404


@pytest.mark.parametrize("path", ["/me", "/awcs", "/beneficiaries", "/captures"])
async def test_protected_routes_require_a_token(client, fixtures, path: str) -> None:
    r = await client.get(path)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


async def test_a_tampered_token_is_rejected(client, fixtures, auth) -> None:
    headers = auth(fixtures["workers"]["5550000001"])
    headers["Authorization"] = headers["Authorization"][:-4] + "aaaa"
    assert (await client.get("/me", headers=headers)).status_code == 401


async def test_me_reports_server_side_scope(client, fixtures, auth) -> None:
    r = await client.get("/me", headers=auth(fixtures["workers"]["5550000001"]))
    body = r.json()
    assert body["role"] == "field_worker"
    assert body["awc_code"] == "TEST-A1"
    # Bilingual, both languages present (Section 9.1).
    assert body["scope_description_hi"] and body["scope_description_en"]


# --------------------------------------------------------------------------
# Scoping, as the client experiences it
# --------------------------------------------------------------------------


async def test_field_workers_get_disjoint_beneficiary_lists(client, fixtures, auth) -> None:
    a1 = await client.get("/beneficiaries", headers=auth(fixtures["workers"]["5550000001"]))
    b1 = await client.get("/beneficiaries", headers=auth(fixtures["workers"]["5550000003"]))
    names_a1 = {i["name"] for i in a1.json()["items"]}
    names_b1 = {i["name"] for i in b1.json()["items"]}
    assert len(names_a1) == 2 and len(names_b1) == 1
    assert names_a1 & names_b1 == set()


async def test_district_official_sees_the_whole_district(client, fixtures, auth) -> None:
    r = await client.get("/beneficiaries", headers=auth(fixtures["workers"]["5550000010"]))
    assert len(r.json()["items"]) == 3


async def test_state_admin_sees_every_district(client, fixtures, auth) -> None:
    r = await client.get("/beneficiaries", headers=auth(fixtures["workers"]["5550000020"]))
    assert len(r.json()["items"]) == 4


async def test_out_of_scope_child_is_404_not_403(client, fixtures, auth) -> None:
    """403 would confirm the child exists somewhere. 404 does not."""
    other = fixtures["children"]["PT-B1-0001"]["id"]
    r = await client.get(f"/beneficiaries/{other}", headers=auth(fixtures["workers"]["5550000001"]))
    assert r.status_code == 404


async def test_a_filter_cannot_widen_scope(client, fixtures, auth) -> None:
    """Asking for another AWC explicitly returns nothing, not that AWC."""
    r = await client.get(
        "/beneficiaries?awc_code=TEST-B1", headers=auth(fixtures["workers"]["5550000001"])
    )
    assert r.json()["items"] == []


async def test_name_search_stays_within_scope(client, fixtures, auth) -> None:
    r = await client.get("/beneficiaries?q=गीता", headers=auth(fixtures["workers"]["5550000001"]))
    assert r.json()["items"] == []  # गीता is at TEST-B1


async def test_awcs_are_returned_bilingually(client, fixtures, auth) -> None:
    r = await client.get("/awcs", headers=auth(fixtures["workers"]["5550000010"]))
    items = r.json()
    assert items, "district official should see their district's centres"
    for a in items:
        # Both languages always ship together so an offline client can toggle.
        assert a["name_hi"] and a["name_en"]
        assert a["district_hi"] and a["block_hi"]


async def test_error_bodies_are_bilingual_problem_json(client, fixtures) -> None:
    r = await client.get("/me")
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["title_en"] and body["title_hi"] and body["status"] == 401


# --------------------------------------------------------------------------
# Growth: deterministic classification, computed server-side
# --------------------------------------------------------------------------


async def test_recording_growth_for_a_toddler_uses_who_2006(client, fixtures, auth) -> None:
    child = fixtures["children"]["PT-A1-0001"]
    r = await client.post(
        "/growth",
        headers=auth(fixtures["workers"]["5550000001"]),
        json={"beneficiary_id": str(child["id"]), "height_cm": 88.0, "weight_kg": 11.2},
    )
    assert r.status_code == 201
    entry = r.json()["entry"]
    assert entry["standard_used"] == "who_2006_0_60m"
    assert entry["whz_score"] is not None
    assert entry["baz_score"] is None
    assert entry["classification"] in {"normal", "MAM", "SAM", "stunted", "underweight"}


async def test_recording_growth_for_a_school_child_uses_who_2007(client, fixtures, auth) -> None:
    """Deviation D1, visible through the API."""
    child = fixtures["children"]["PT-A2-0001"]
    r = await client.post(
        "/growth",
        headers=auth(fixtures["workers"]["5550000002"]),
        json={"beneficiary_id": str(child["id"]), "height_cm": 124.0, "weight_kg": 22.5},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["entry"]["standard_used"] == "who_2007_5_19y"
    assert body["entry"]["whz_score"] is None
    assert body["entry"]["baz_score"] is not None
    # The reason weight-for-height is absent is surfaced, not silently omitted.
    assert any("weight-for-height is undefined" in n for n in body["notes"])


async def test_classification_is_not_client_controllable(client, fixtures, auth) -> None:
    """Extra fields are ignored -- there is no path by which a caller writes a
    classification the server did not derive (Section 6.4)."""
    child = fixtures["children"]["PT-A1-0002"]
    r = await client.post(
        "/growth",
        headers=auth(fixtures["workers"]["5550000001"]),
        json={
            "beneficiary_id": str(child["id"]),
            "height_cm": 85.0,
            "weight_kg": 11.0,
            "classification": "normal",
            "waz_score": 0.0,
            "whz_score": 0.0,
        },
    )
    assert r.status_code == 201
    entry = r.json()["entry"]
    from app.growth.assess import assess
    from app.growth.lms import Sex

    expected = assess(
        dob=child["dob"],
        recorded_at=date.today(),
        sex=Sex.MALE,
        height_cm=85.0,
        weight_kg=11.0,
    )
    assert entry["classification"] == expected.classification
    assert float(entry["haz_score"]) == pytest.approx(expected.haz, abs=0.01)


async def test_stored_zscores_are_reproducible_from_stored_measurements(
    client, fixtures, auth
) -> None:
    """The audit property: re-run the pure function on the stored height and
    weight and you get the stored z-score back."""
    child = fixtures["children"]["PT-A1-0001"]
    r = await client.post(
        "/growth",
        headers=auth(fixtures["workers"]["5550000001"]),
        json={"beneficiary_id": str(child["id"]), "height_cm": 91.3, "weight_kg": 12.4},
    )
    entry = r.json()["entry"]

    from app.growth.assess import assess
    from app.growth.lms import Sex

    again = assess(
        dob=child["dob"],
        recorded_at=date.fromisoformat(entry["recorded_at"]),
        sex=Sex.FEMALE,
        height_cm=float(entry["height_cm"]),
        weight_kg=float(entry["weight_kg"]),
    )
    assert float(entry["haz_score"]) == pytest.approx(again.haz, abs=0.005)
    assert float(entry["whz_score"]) == pytest.approx(again.whz, abs=0.005)
    assert entry["classification"] == again.classification


async def test_only_field_workers_may_record_growth(client, fixtures, auth) -> None:
    child = fixtures["children"]["PT-A1-0001"]
    for phone in ("5550000010", "5550000020"):
        r = await client.post(
            "/growth",
            headers=auth(fixtures["workers"][phone]),
            json={"beneficiary_id": str(child["id"]), "height_cm": 88.0, "weight_kg": 11.0},
        )
        assert r.status_code == 403


async def test_cannot_record_growth_for_another_awcs_child(client, fixtures, auth) -> None:
    other = fixtures["children"]["PT-B1-0001"]
    r = await client.post(
        "/growth",
        headers=auth(fixtures["workers"]["5550000001"]),
        json={"beneficiary_id": str(other["id"]), "height_cm": 88.0, "weight_kg": 11.0},
    )
    assert r.status_code == 404


async def test_future_measurement_is_rejected(client, fixtures, auth) -> None:
    child = fixtures["children"]["PT-A1-0001"]
    r = await client.post(
        "/growth",
        headers=auth(fixtures["workers"]["5550000001"]),
        json={
            "beneficiary_id": str(child["id"]),
            "recorded_at": (date.today() + timedelta(days=1)).isoformat(),
            "height_cm": 88.0,
            "weight_kg": 11.0,
        },
    )
    assert r.status_code == 422


async def test_growth_history_is_oldest_first(client, fixtures, auth) -> None:
    child = fixtures["children"]["PT-A1-0001"]
    headers = auth(fixtures["workers"]["5550000001"])
    for offset, h, w in ((60, 86.0, 10.8), (30, 87.0, 11.0), (0, 88.0, 11.3)):
        await client.post(
            "/growth",
            headers=headers,
            json={
                "beneficiary_id": str(child["id"]),
                "recorded_at": (date.today() - timedelta(days=offset)).isoformat(),
                "height_cm": h,
                "weight_kg": w,
            },
        )
    rows = (await client.get(f"/growth/{child['id']}", headers=headers)).json()
    assert len(rows) == 3
    assert [r["recorded_at"] for r in rows] == sorted(r["recorded_at"] for r in rows)


# --------------------------------------------------------------------------
# Captures
# --------------------------------------------------------------------------


async def test_capture_upload_creates_a_pending_row(client, fixtures, auth, fake_storage) -> None:
    child = fixtures["children"]["PT-A1-0001"]
    r = await client.post(
        "/captures",
        headers=auth(fixtures["workers"]["5550000001"]),
        data={"beneficiary_id": str(child["id"]), "meal_type": "lunch"},
        files={"photo": ("plate.jpg", _jpeg(), "image/jpeg")},
    )
    assert r.status_code == 201
    body = r.json()
    # Phase 1 stores; Phase 2 infers. Every AI column must still be empty.
    assert body["sync_status"] == "pending"
    assert body["ai_calories"] is None and body["ai_model_version"] is None
    assert body["photo_signed_url"].startswith("https://stub.invalid/")


async def test_photo_path_is_namespaced_by_awc(client, fixtures, auth, fake_storage) -> None:
    """The first path segment is what the Storage RLS policy matches on."""
    child = fixtures["children"]["PT-A1-0001"]
    r = await client.post(
        "/captures",
        headers=auth(fixtures["workers"]["5550000001"]),
        data={"beneficiary_id": str(child["id"]), "meal_type": "breakfast"},
        files={"photo": ("plate.jpg", _jpeg(), "image/jpeg")},
    )
    path = r.json()["photo_url"]
    assert path.startswith("TEST-A1/")
    assert path in fake_storage


async def test_capture_rejects_non_image_uploads(client, fixtures, auth) -> None:
    child = fixtures["children"]["PT-A1-0001"]
    r = await client.post(
        "/captures",
        headers=auth(fixtures["workers"]["5550000001"]),
        data={"beneficiary_id": str(child["id"]), "meal_type": "lunch"},
        files={"photo": ("notes.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 415


async def test_capture_rejects_an_unknown_meal_type(client, fixtures, auth) -> None:
    child = fixtures["children"]["PT-A1-0001"]
    r = await client.post(
        "/captures",
        headers=auth(fixtures["workers"]["5550000001"]),
        data={"beneficiary_id": str(child["id"]), "meal_type": "dinner"},
        files={"photo": ("plate.jpg", _jpeg(), "image/jpeg")},
    )
    assert r.status_code == 422


async def test_only_field_workers_may_upload_captures(client, fixtures, auth) -> None:
    child = fixtures["children"]["PT-A1-0001"]
    r = await client.post(
        "/captures",
        headers=auth(fixtures["workers"]["5550000010"]),
        data={"beneficiary_id": str(child["id"]), "meal_type": "lunch"},
        files={"photo": ("plate.jpg", _jpeg(), "image/jpeg")},
    )
    assert r.status_code == 403


async def test_cannot_upload_a_capture_for_another_awcs_child(client, fixtures, auth) -> None:
    other = fixtures["children"]["PT-B1-0001"]
    r = await client.post(
        "/captures",
        headers=auth(fixtures["workers"]["5550000001"]),
        data={"beneficiary_id": str(other["id"]), "meal_type": "lunch"},
        files={"photo": ("plate.jpg", _jpeg(), "image/jpeg")},
    )
    assert r.status_code == 404


async def test_capture_listing_is_scoped(client, fixtures, auth, fake_storage) -> None:
    child = fixtures["children"]["PT-A1-0001"]
    await client.post(
        "/captures",
        headers=auth(fixtures["workers"]["5550000001"]),
        data={"beneficiary_id": str(child["id"]), "meal_type": "lunch"},
        files={"photo": ("plate.jpg", _jpeg(), "image/jpeg")},
    )
    mine = await client.get("/captures", headers=auth(fixtures["workers"]["5550000001"]))
    theirs = await client.get("/captures", headers=auth(fixtures["workers"]["5550000003"]))
    assert len(mine.json()["items"]) == 1
    assert theirs.json()["items"] == []


async def test_unknown_capture_is_404(client, fixtures, auth) -> None:
    r = await client.get(
        f"/captures/{uuid.uuid4()}", headers=auth(fixtures["workers"]["5550000001"])
    )
    assert r.status_code == 404


async def test_listing_survives_a_storage_outage(client, fixtures, auth, monkeypatch) -> None:
    """A dashboard without thumbnails beats a dashboard that 500s."""
    child = fixtures["children"]["PT-A1-0001"]
    headers = auth(fixtures["workers"]["5550000001"])
    await client.post(
        "/captures",
        headers=headers,
        data={"beneficiary_id": str(child["id"]), "meal_type": "lunch"},
        files={"photo": ("plate.jpg", _jpeg(), "image/jpeg")},
    )

    async def _boom(**_):
        raise storage.StorageError("simulated outage")

    monkeypatch.setattr(storage, "create_signed_url", _boom)
    r = await client.get("/captures", headers=headers)
    assert r.status_code == 200
    assert r.json()["items"][0]["photo_signed_url"] is None
    assert r.json()["items"][0]["photo_url"]  # path still returned
