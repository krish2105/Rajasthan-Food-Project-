"""One-time code lifecycle: issue, throttle, verify.

Everything that makes a six-digit code safe lives here rather than in a
provider, so it applies whichever channel delivers the message.

The threat this is actually defending against is not sophisticated. A six-digit
code is one of a million, and an endpoint that accepts unlimited guesses is a
brute force that finishes in minutes. The controls are correspondingly plain:
a short expiry, a hard attempt limit, and a cap on how many codes a number can
be sent.

Two subtler choices:

**Codes are stored as HMACs keyed on the server secret**, not as plain hashes.
A million-entry rainbow table for SHA-256 of six digits is trivial to build, so
an unkeyed hash would offer no protection at all to anyone holding a copy of
the database. The keyed HMAC means they need the secret too.

**Verification is deliberately uninformative.** An unregistered number, an
expired code and a wrong code are the same response. Otherwise the request
endpoint becomes a way to discover which phone numbers belong to Anganwadi
workers.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FieldWorker, OtpCode

CODE_LENGTH = 6
TTL_SECONDS = 300  # 5 minutes
MAX_ATTEMPTS = 5
#: How many codes one number may be sent inside the window below.
MAX_REQUESTS_PER_WINDOW = 5
REQUEST_WINDOW_SECONDS = 900  # 15 minutes
#: Minimum gap between two requests for the same number, so the endpoint cannot
#: be used to bombard someone's phone.
MIN_REQUEST_GAP_SECONDS = 30


class OtpError(Exception):
    """Base for anything that stops a code being issued or accepted."""


class Throttled(OtpError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("too many requests")
        self.retry_after = retry_after


class VerificationFailed(OtpError):
    """Wrong, expired, already used, out of attempts, or unknown number.

    One exception for all of them on purpose -- see the module docstring.

    Note that `verify` *returns* rather than raising this. Raising inside the
    caller's transaction would roll back the attempt counter that the raise is
    supposed to have recorded, silently disabling the brute-force limit. The
    class is kept for callers that want to raise after committing.
    """


@dataclass(frozen=True, slots=True)
class IssuedCode:
    code: str
    expires_at: datetime
    record_id: str


def _now() -> datetime:
    return datetime.now(UTC)


def generate_code() -> str:
    """A cryptographically random code.

    `secrets`, not `random`: a predictable OTP is not an OTP. Leading zeros are
    preserved, so "004213" stays six digits.
    """
    return f"{secrets.randbelow(10**CODE_LENGTH):0{CODE_LENGTH}d}"


def hash_code(code: str, phone: str) -> str:
    """Keyed HMAC of the code, bound to the phone number.

    Binding to the phone means a hash captured for one number cannot be
    replayed against another, even if the same code happens to be issued twice.
    """
    from app.config import get_settings

    secret = get_settings().supabase_jwt_secret.encode()
    return hmac.new(secret, f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


async def check_throttle(session: AsyncSession, phone: str) -> None:
    """Raise `Throttled` if this number has asked too often or too recently."""
    window_start = _now() - timedelta(seconds=REQUEST_WINDOW_SECONDS)
    recent = (
        (
            await session.execute(
                select(OtpCode)
                .where(OtpCode.phone == phone, OtpCode.created_at >= window_start)
                .order_by(OtpCode.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    if recent:
        since_last = (_now() - recent[0].created_at).total_seconds()
        if since_last < MIN_REQUEST_GAP_SECONDS:
            raise Throttled(retry_after=int(MIN_REQUEST_GAP_SECONDS - since_last) + 1)

    if len(recent) >= MAX_REQUESTS_PER_WINDOW:
        oldest = recent[-1].created_at
        wait = REQUEST_WINDOW_SECONDS - (_now() - oldest).total_seconds()
        raise Throttled(retry_after=max(1, int(wait) + 1))


async def issue(session: AsyncSession, phone: str) -> IssuedCode:
    """Create and store a code. Delivery is the caller's job.

    Any code still outstanding for this number is consumed first: a worker who
    asks again should find that only the newest message works, rather than
    leaving several valid codes in flight.
    """
    outstanding = (
        (
            await session.execute(
                select(OtpCode).where(
                    OtpCode.phone == phone,
                    OtpCode.consumed_at.is_(None),
                    OtpCode.expires_at > _now(),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in outstanding:
        row.consumed_at = _now()

    code = generate_code()
    expires_at = _now() + timedelta(seconds=TTL_SECONDS)
    record = OtpCode(
        phone=phone,
        code_hash=hash_code(code, phone),
        expires_at=expires_at,
        attempts=0,
    )
    session.add(record)
    await session.flush()
    return IssuedCode(code=code, expires_at=expires_at, record_id=str(record.id))


async def verify(session: AsyncSession, phone: str, code: str) -> FieldWorker | None:
    """Check a code; return the worker it belongs to, or None.

    **Returns None rather than raising**, and that is load-bearing. This runs
    inside the caller's transaction, and an exception raised here would roll
    that transaction back -- including the attempt counter this function just
    incremented. The brute-force limit would then never advance and a six-digit
    code could be guessed indefinitely. Found by test; the failure was
    completely silent.

    Every failure mode returns None without distinguishing itself. An attempt is
    counted even when the number is not registered, so behaviour stays uniform.
    """
    record = (
        await session.execute(
            select(OtpCode)
            .where(OtpCode.phone == phone, OtpCode.consumed_at.is_(None))
            .order_by(OtpCode.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if record is None or record.expires_at <= _now():
        return None

    if record.attempts >= MAX_ATTEMPTS:
        # Burn it rather than leaving an exhausted code lying around.
        record.consumed_at = _now()
        return None

    record.attempts += 1

    expected = hash_code(code, phone)
    # Constant-time comparison: a short-circuiting `==` on a hex digest leaks
    # how much of the hash matched, which over enough attempts is a shortcut.
    if not hmac.compare_digest(record.code_hash, expected):
        return None

    worker = (
        await session.execute(select(FieldWorker).where(FieldWorker.phone == phone))
    ).scalar_one_or_none()
    if worker is None:
        # The code was right but the number is not staff. Consume it anyway --
        # a correct code should never be reusable.
        record.consumed_at = _now()
        return None

    record.consumed_at = _now()
    return worker
