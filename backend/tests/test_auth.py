"""Phone-OTP sign-in, throttling and refresh rotation (Sections 4, 10, 11).

The RBAC these tokens carry has been tested since Phase 1. What is new here is
how a caller proves who they are, so these tests are about the ways that can be
attacked: guessing a six-digit code, enumerating which numbers belong to staff,
and replaying a stolen refresh token.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.auth import otp, refresh
from app.auth.providers import ConsoleProvider, DeliveryError, Msg91Provider
from app.db.models import OtpCode, RefreshToken
from app.db.session import admin_session

WORKER_PHONE = "9876500001"
UNKNOWN_PHONE = "9876599999"


@pytest.fixture
async def worker_phone(fixtures):
    """Give a fixture worker a realistic Indian mobile number."""
    from app.db.models import FieldWorker

    async with admin_session() as session:
        async with session.begin():
            await session.execute(
                update(FieldWorker)
                .where(FieldWorker.phone == "5550000001")
                .values(phone=WORKER_PHONE)
            )
    return WORKER_PHONE


async def request_code(client, phone: str) -> str | None:
    response = await client.post("/auth/otp/request", json={"phone": phone})
    assert response.status_code == 202
    return response.json().get("debug_code")


async def clear_throttle() -> None:
    """Age out recent requests so a test can ask again immediately."""
    async with admin_session() as session:
        async with session.begin():
            await session.execute(
                update(OtpCode).values(created_at=datetime.now(UTC) - timedelta(hours=1))
            )


# --------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------


async def test_a_worker_can_sign_in_with_a_code(client, worker_phone) -> None:
    code = await request_code(client, worker_phone)
    assert code and len(code) == otp.CODE_LENGTH

    response = await client.post("/auth/otp/verify", json={"phone": worker_phone, "otp": code})
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "field_worker"
    assert body["awc_code"] == "TEST-A1"
    assert body["expires_in"] == 3600  # Section 11's short-lived access token
    assert body["refresh_token"]


async def test_the_token_carries_the_same_scope_as_before(client, worker_phone) -> None:
    """Phase 6 changed the identity source, not the scope model."""
    code = await request_code(client, worker_phone)
    session = (
        await client.post("/auth/otp/verify", json={"phone": worker_phone, "otp": code})
    ).json()

    headers = {"Authorization": f"Bearer {session['access_token']}"}
    me = (await client.get("/me", headers=headers)).json()
    assert me["awc_code"] == "TEST-A1"

    listing = (await client.get("/beneficiaries", headers=headers)).json()
    assert {item["awc_code"] for item in listing["items"]} == {"TEST-A1"}


async def test_a_country_code_reaches_the_same_worker(client, worker_phone) -> None:
    """A worker may type 91 in front of their number, or not."""
    code = await request_code(client, f"91{worker_phone}")
    response = await client.post("/auth/otp/verify", json={"phone": worker_phone, "otp": code})
    assert response.status_code == 200


# --------------------------------------------------------------------------
# Not telling an attacker anything
# --------------------------------------------------------------------------


async def test_an_unregistered_number_gets_the_same_reply(client, worker_phone) -> None:
    """Otherwise this endpoint enumerates which numbers belong to staff.

    The `debug_*` keys are excluded from the comparison because they only exist
    under the console provider outside production. In a deployment the provider
    is a real one, so they are never emitted at all -- see the test below.
    """
    registered = await client.post("/auth/otp/request", json={"phone": worker_phone})
    await clear_throttle()
    unknown = await client.post("/auth/otp/request", json={"phone": UNKNOWN_PHONE})

    assert registered.status_code == unknown.status_code == 202

    def public(body: dict) -> dict:
        return {k: v for k, v in body.items() if not k.startswith("debug_")}

    assert public(registered.json()) == public(unknown.json())


async def test_development_says_whether_a_number_is_registered(client, worker_phone) -> None:
    """Only in development, and only with the console provider.

    Without this the demo is actively misleading: an unregistered number gets a
    code that is genuinely correct, typing it fails, and the sign-in screen
    looks broken rather than the number looking unregistered. Found by using it.
    """
    registered = (await client.post("/auth/otp/request", json={"phone": worker_phone})).json()
    await clear_throttle()
    unknown = (await client.post("/auth/otp/request", json={"phone": UNKNOWN_PHONE})).json()

    assert registered["debug_registered"] is True
    assert unknown["debug_registered"] is False
    # And it names the numbers that do work, so a demo is not a guessing game.
    assert any(a["phone"] == worker_phone for a in unknown["debug_accounts"])


async def test_no_debug_fields_are_emitted_in_production(client, worker_phone, monkeypatch) -> None:
    """The registration hint is a development affordance. In a deployment it
    would be exactly the enumeration oracle the generic response avoids."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "app_env", "production")
    body = (await client.post("/auth/otp/request", json={"phone": worker_phone})).json()
    assert not any(key.startswith("debug_") for key in body)


async def test_a_correct_code_for_an_unregistered_number_still_fails(client, fixtures) -> None:
    code = await request_code(client, UNKNOWN_PHONE)
    response = await client.post("/auth/otp/verify", json={"phone": UNKNOWN_PHONE, "otp": code})
    assert response.status_code == 401


@pytest.mark.parametrize("bad", ["12345", "abcdefghij", "98765"])
async def test_malformed_numbers_are_named_as_such(client, fixtures, bad: str) -> None:
    """The one thing worth telling the caller: they mistyped. That reveals
    nothing about who is registered."""
    response = await client.post("/auth/otp/request", json={"phone": bad})
    assert response.status_code == 422


async def test_wrong_and_expired_codes_are_indistinguishable(client, worker_phone) -> None:
    await request_code(client, worker_phone)
    wrong = await client.post("/auth/otp/verify", json={"phone": worker_phone, "otp": "000000"})
    async with admin_session() as session:
        async with session.begin():
            await session.execute(
                update(OtpCode).values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
            )
    expired = await client.post("/auth/otp/verify", json={"phone": worker_phone, "otp": "123456"})
    assert wrong.status_code == expired.status_code == 401
    assert wrong.json()["code"] == expired.json()["code"]


# --------------------------------------------------------------------------
# Brute force
# --------------------------------------------------------------------------


async def test_a_code_dies_after_five_wrong_attempts(client, worker_phone) -> None:
    """A six-digit code is one of a million; unlimited guesses finish in
    minutes."""
    code = await request_code(client, worker_phone)
    for _ in range(otp.MAX_ATTEMPTS):
        assert (
            await client.post("/auth/otp/verify", json={"phone": worker_phone, "otp": "000000"})
        ).status_code == 401

    # Even the right code no longer works.
    assert (
        await client.post("/auth/otp/verify", json={"phone": worker_phone, "otp": code})
    ).status_code == 401


async def test_a_code_cannot_be_used_twice(client, worker_phone) -> None:
    code = await request_code(client, worker_phone)
    first = await client.post("/auth/otp/verify", json={"phone": worker_phone, "otp": code})
    second = await client.post("/auth/otp/verify", json={"phone": worker_phone, "otp": code})
    assert first.status_code == 200
    assert second.status_code == 401


async def test_requesting_again_invalidates_the_previous_code(client, worker_phone) -> None:
    """Only the newest message should work, or several codes stay live at once."""
    first = await request_code(client, worker_phone)
    await clear_throttle()
    second = await request_code(client, worker_phone)
    assert first != second
    assert (
        await client.post("/auth/otp/verify", json={"phone": worker_phone, "otp": first})
    ).status_code == 401
    assert (
        await client.post("/auth/otp/verify", json={"phone": worker_phone, "otp": second})
    ).status_code == 200


async def test_codes_are_never_stored_in_the_clear(client, worker_phone) -> None:
    """A million-entry table for six digits is trivial to build, so the stored
    value is an HMAC keyed on the server secret rather than a plain hash."""
    code = await request_code(client, worker_phone)
    async with admin_session() as session:
        row = (
            await session.execute(select(OtpCode).order_by(OtpCode.created_at.desc()).limit(1))
        ).scalar_one()
    assert code not in row.code_hash
    assert len(row.code_hash) == 64
    assert row.code_hash == otp.hash_code(code, worker_phone)


async def test_a_code_hash_is_bound_to_its_phone_number(worker_phone) -> None:
    """So a hash captured for one number cannot be replayed against another."""
    assert otp.hash_code("123456", "9876500001") != otp.hash_code("123456", "9876500002")


def test_codes_are_cryptographically_random() -> None:
    codes = {otp.generate_code() for _ in range(400)}
    assert len(codes) > 350, "predictable codes are not one-time codes"
    assert all(len(c) == otp.CODE_LENGTH and c.isdigit() for c in codes)


# --------------------------------------------------------------------------
# Throttling
# --------------------------------------------------------------------------


async def test_requests_are_spaced_so_a_phone_cannot_be_bombarded(client, worker_phone) -> None:
    await client.post("/auth/otp/request", json={"phone": worker_phone})
    second = await client.post("/auth/otp/request", json={"phone": worker_phone})
    assert second.status_code == 429
    assert "Retry-After" in second.headers


async def test_a_number_is_capped_within_the_window(client, worker_phone) -> None:
    for _ in range(otp.MAX_REQUESTS_PER_WINDOW):
        response = await client.post("/auth/otp/request", json={"phone": worker_phone})
        if response.status_code == 429:
            # Age out only the inter-request gap, not the window.
            async with admin_session() as session:
                async with session.begin():
                    await session.execute(
                        update(OtpCode).values(created_at=datetime.now(UTC) - timedelta(seconds=60))
                    )
            response = await client.post("/auth/otp/request", json={"phone": worker_phone})
        assert response.status_code == 202

    async with admin_session() as session:
        async with session.begin():
            await session.execute(
                update(OtpCode).values(created_at=datetime.now(UTC) - timedelta(seconds=60))
            )
    assert (await client.post("/auth/otp/request", json={"phone": worker_phone})).status_code == 429


async def test_the_throttle_applies_to_unregistered_numbers_too(client, fixtures) -> None:
    """Otherwise timing tells an attacker which numbers are staff."""
    await client.post("/auth/otp/request", json={"phone": UNKNOWN_PHONE})
    assert (
        await client.post("/auth/otp/request", json={"phone": UNKNOWN_PHONE})
    ).status_code == 429


# --------------------------------------------------------------------------
# Refresh: reconciling Section 11 with Section 7
# --------------------------------------------------------------------------


async def sign_in(client, phone: str) -> dict:
    code = await request_code(client, phone)
    return (await client.post("/auth/otp/verify", json={"phone": phone, "otp": code})).json()


async def test_a_refresh_token_buys_a_new_access_token(client, worker_phone) -> None:
    session = await sign_in(client, worker_phone)
    response = await client.post("/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert response.status_code == 200
    assert response.json()["access_token"] != session["access_token"]


async def test_refresh_tokens_last_long_enough_to_survive_being_offline(
    client, worker_phone
) -> None:
    """Section 7: a worker at a centre with a fortnight of bad connectivity must
    not come back to a sign-in screen and a queue that will not send."""
    session = await sign_in(client, worker_phone)
    expires = datetime.fromisoformat(session["refresh_expires_at"])
    assert (expires - datetime.now(UTC)).days >= 28


async def test_a_refresh_token_rotates_on_use(client, worker_phone) -> None:
    session = await sign_in(client, worker_phone)
    rotated = (
        await client.post("/auth/refresh", json={"refresh_token": session["refresh_token"]})
    ).json()
    assert rotated["refresh_token"] != session["refresh_token"]


async def test_reusing_a_spent_refresh_token_revokes_everything(client, worker_phone) -> None:
    """Presenting a spent token means it leaked. Letting the real device carry
    on would leave the attacker's copy working too."""
    session = await sign_in(client, worker_phone)
    rotated = (
        await client.post("/auth/refresh", json={"refresh_token": session["refresh_token"]})
    ).json()

    replayed = await client.post("/auth/refresh", json={"refresh_token": session["refresh_token"]})
    assert replayed.status_code == 401
    assert "reuse" in replayed.json()["code"].lower()

    # The device that did nothing wrong is signed out too. That is the point.
    assert (
        await client.post("/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
    ).status_code == 401


async def test_an_expired_refresh_token_is_refused(client, worker_phone) -> None:
    session = await sign_in(client, worker_phone)
    async with admin_session() as session_db:
        async with session_db.begin():
            await session_db.execute(
                update(RefreshToken).values(expires_at=datetime.now(UTC) - timedelta(days=1))
            )
    assert (
        await client.post("/auth/refresh", json={"refresh_token": session["refresh_token"]})
    ).status_code == 401


async def test_an_unknown_refresh_token_is_refused(client, fixtures) -> None:
    assert (
        await client.post("/auth/refresh", json={"refresh_token": "not-a-real-token"})
    ).status_code == 401


async def test_refresh_tokens_are_never_stored_in_the_clear(client, worker_phone) -> None:
    session = await sign_in(client, worker_phone)
    async with admin_session() as db:
        row = (
            await db.execute(select(RefreshToken).order_by(RefreshToken.created_at.desc()).limit(1))
        ).scalar_one()
    assert session["refresh_token"] not in row.token_hash
    assert row.token_hash == refresh.hash_token(session["refresh_token"])


async def test_logging_out_revokes_the_device(client, worker_phone) -> None:
    session = await sign_in(client, worker_phone)
    assert (
        await client.post("/auth/logout", json={"refresh_token": session["refresh_token"]})
    ).status_code == 204
    assert (
        await client.post("/auth/refresh", json={"refresh_token": session["refresh_token"]})
    ).status_code == 401


async def test_logging_out_an_unknown_token_succeeds_quietly(client, fixtures) -> None:
    """Reporting which tokens exist would make this an oracle, and a client
    signing out has nothing useful to do with the difference."""
    assert (
        await client.post("/auth/logout", json={"refresh_token": "never-existed"})
    ).status_code == 204


# --------------------------------------------------------------------------
# Delivery providers
# --------------------------------------------------------------------------


async def test_the_console_provider_reveals_the_code_outside_production() -> None:
    result = await ConsoleProvider(reveal=True).send(
        phone="9876500001", code="123456", ttl_seconds=300
    )
    assert result.code_for_display == "123456"


async def test_the_console_provider_hides_the_code_in_production() -> None:
    result = await ConsoleProvider(reveal=False).send(
        phone="9876500001", code="123456", ttl_seconds=300
    )
    assert result.code_for_display is None


def test_msg91_refuses_to_start_without_credentials() -> None:
    """A provider that silently no-ops is worse than one that will not start."""
    with pytest.raises(DeliveryError, match="authkey"):
        Msg91Provider(authkey="", template_id="")


async def test_msg91_treats_a_200_with_type_error_as_a_failure(monkeypatch) -> None:
    """MSG91 returns HTTP 200 on an invalid authkey or template, signalling the
    failure in the body. Checking the status code alone would report every
    misconfiguration as a successful send, and the worker would wait for a
    message that was never dispatched. Confirmed against the live endpoint."""
    import httpx

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {"message": "Invalid authkey", "type": "error", "code": "201"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
    provider = Msg91Provider(authkey="wrong", template_id="t1")
    with pytest.raises(DeliveryError, match="Invalid authkey"):
        await provider.send(phone="9876500001", code="123456", ttl_seconds=300)


async def test_msg91_adds_the_country_code_and_never_sends_the_code_in_a_log(
    monkeypatch,
) -> None:
    import httpx

    captured: dict = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {"message": "abc123", "type": "success"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
    provider = Msg91Provider(authkey="k", template_id="t1", sender="POSHAN")
    result = await provider.send(phone="9876500001", code="123456", ttl_seconds=300)

    assert result.status == "sent"
    assert result.code_for_display is None, "a real provider must never echo the code"
    assert captured["json"]["mobile"] == "919876500001"
    assert captured["json"]["otp"] == "123456"
    assert captured["json"]["otp_expiry"] == 5
    assert captured["headers"]["authkey"] == "k"


# --------------------------------------------------------------------------
# The deployed demo
# --------------------------------------------------------------------------


async def test_a_demo_deployment_can_reveal_codes_for_seeded_numbers(
    client, fixtures, monkeypatch
) -> None:
    """Section 14 step 1 calls for a deployed demo build. With no SMS credits,
    a reviewer would otherwise have to read Render's logs to sign in.

    This is an open door by design, which is why it is off by default, gated on
    a demo environment, and restricted to the reserved seeded range."""
    from app.config import get_settings
    from app.db.models import FieldWorker

    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "demo")
    monkeypatch.setattr(settings, "demo_reveal_otp", True)

    async with admin_session() as session:
        async with session.begin():
            await session.execute(
                update(FieldWorker)
                .where(FieldWorker.phone == "5550000001")
                .values(phone="9999900001")
            )

    body = (await client.post("/auth/otp/request", json={"phone": "9999900001"})).json()
    assert body.get("debug_code")


async def test_a_demo_never_reveals_a_code_for_a_number_outside_the_seeded_range(
    client, fixtures, monkeypatch
) -> None:
    """So a real worker's code can never be disclosed, even if a real number
    somehow ended up in a demo database."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "demo")
    monkeypatch.setattr(settings, "demo_reveal_otp", True)

    body = (await client.post("/auth/otp/request", json={"phone": "9876500001"})).json()
    assert "debug_code" not in body


async def test_production_never_reveals_a_code_however_it_is_configured(
    client, fixtures, monkeypatch
) -> None:
    """The flag is not a production override. `seeding_allowed` is false there,
    so the reveal cannot be switched on by a stray environment variable."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "demo_reveal_otp", True)

    body = (await client.post("/auth/otp/request", json={"phone": "9999900001"})).json()
    assert "debug_code" not in body
