"""OTP delivery.

The code itself is generated, hashed, expired and verified by this system --
see `app/auth/otp.py`. A provider here only *delivers* it. That split is
deliberate: it means the throttling, the attempt limit and the hashed storage
apply no matter which channel is used, and swapping providers cannot weaken
them.

Two providers:

``console``  Logs the code. The default, and what tests and local development
             use, because a test suite that sends real SMS is a test suite that
             costs money and cannot run offline.
``msg91``    Real delivery through MSG91 (Section 4's named provider).

Section 10 advises against spending build time on a real SMS integration until
there is a district partner in hand. That advice was overridden deliberately, so
the MSG91 client here is complete rather than a placeholder -- but it cannot be
exercised against the live service without an account, an authkey, a DLT-
approved template and credits, none of which exist yet. See
docs/phase6-auth-setup.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger("poshannetra.auth")

#: MSG91's OTP endpoint. Confirmed against the live service on 2026-08-28.
MSG91_SEND_URL = "https://control.msg91.com/api/v5/otp"
MSG91_TIMEOUT = 15.0


class DeliveryError(RuntimeError):
    """The code could not be delivered. Never leaks the code itself."""


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    status: str
    detail: str | None = None
    #: Returned only by the console provider outside production, so a demo does
    #: not require reading server logs. Never populated by a real provider.
    code_for_display: str | None = None


class OtpProvider:
    name = "base"

    async def send(self, *, phone: str, code: str, ttl_seconds: int) -> DeliveryResult:
        raise NotImplementedError


class ConsoleProvider(OtpProvider):
    """Logs the code instead of sending it.

    The default. `code_for_display` is populated only when the application is
    not running in production, which is what lets the sign-in screen show the
    code during a demo without anyone reading a server log.
    """

    name = "console"

    def __init__(self, *, reveal: bool) -> None:
        self._reveal = reveal

    async def send(self, *, phone: str, code: str, ttl_seconds: int) -> DeliveryResult:
        logger.info("OTP for %s: %s (expires in %ss)", phone, code, ttl_seconds)
        return DeliveryResult(
            status="console",
            detail="logged, not sent",
            code_for_display=code if self._reveal else None,
        )


class Msg91Provider(OtpProvider):
    """Delivers through MSG91.

    Two things about this API are easy to get wrong and are handled explicitly:

    **It returns HTTP 200 on failure.** An invalid authkey, an unapproved
    template and a malformed number all come back as ``200`` with
    ``{"type": "error"}`` in the body. Checking the status code alone would
    report every failure as a successful send, and the worker would sit waiting
    for a message that was never dispatched. Verified against the live endpoint.

    **We pass our own code.** MSG91 can generate and verify one itself, but
    then the expiry, the attempt limit and the throttle would be its policy
    rather than ours, and would change if the provider did. The code is ours;
    MSG91 is the transport.
    """

    name = "msg91"

    def __init__(self, *, authkey: str, template_id: str, sender: str | None = None) -> None:
        if not authkey or not template_id:
            raise DeliveryError(
                "MSG91 needs both an authkey and a DLT-approved template id; "
                "see docs/phase6-auth-setup.md"
            )
        self._authkey = authkey
        self._template_id = template_id
        self._sender = sender

    async def send(self, *, phone: str, code: str, ttl_seconds: int) -> DeliveryResult:
        payload: dict[str, object] = {
            "template_id": self._template_id,
            # MSG91 wants the full international form with no plus sign. Indian
            # numbers are stored here as ten digits, so the country code is
            # added rather than assumed to be present.
            "mobile": phone if phone.startswith("91") else f"91{phone}",
            "otp": code,
            "otp_expiry": max(1, ttl_seconds // 60),
        }
        if self._sender:
            payload["sender"] = self._sender

        try:
            async with httpx.AsyncClient(timeout=MSG91_TIMEOUT) as client:
                response = await client.post(
                    MSG91_SEND_URL,
                    json=payload,
                    headers={"authkey": self._authkey, "content-type": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise DeliveryError(f"could not reach MSG91: {exc}") from exc

        # Transport-level failure is still possible and still matters.
        if response.status_code >= 400:
            raise DeliveryError(f"MSG91 returned HTTP {response.status_code}")

        try:
            body = response.json()
        except ValueError as exc:
            raise DeliveryError("MSG91 returned a non-JSON response") from exc

        if str(body.get("type", "")).lower() == "error":
            # The message is MSG91's, and is safe to surface to an operator: it
            # names the misconfiguration ("Invalid authkey", "The provided flow
            # ID or template ID is invalid") without revealing the code.
            raise DeliveryError(f"MSG91 refused the request: {body.get('message')}")

        return DeliveryResult(status="sent", detail=str(body.get("message") or "")[:200])


def build_provider() -> OtpProvider:
    """Construct the configured provider.

    Defaults to `console` so that nothing spends SMS credits by accident, and
    so CI never depends on a third party being reachable.
    """
    from app.config import get_settings

    settings = get_settings()
    if settings.otp_provider == "msg91":
        return Msg91Provider(
            authkey=settings.msg91_authkey,
            template_id=settings.msg91_template_id,
            sender=settings.msg91_sender or None,
        )
    return ConsoleProvider(reveal=settings.otp_reveal_allowed)
