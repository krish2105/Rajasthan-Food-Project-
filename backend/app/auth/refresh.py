"""Refresh tokens: the reconciliation between Section 11 and Section 7.

Section 11 asks for one-hour access tokens. Section 7 requires the Field PWA to
keep working through days without connectivity. A worker with no signal cannot
refresh anything, so a short token alone would sign them out mid-shift and
strand a queue of plate photographs.

The resolution is that the *access* token stays short and the device holds a
long-lived refresh token, exchanged opportunistically whenever a connection
appears. Capture and growth entry never consult token state at all -- they write
to IndexedDB -- so an expired access token slows syncing rather than stopping
work.

Rotation on every use, with reuse treated as compromise. If a token is
presented twice, either it was replayed or the device was cloned; in both cases
the safe response is to revoke the whole chain and make the worker sign in
again.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FieldWorker, RefreshToken

#: Long enough to survive a fortnight of bad connectivity plus leave. The
#: trade-off is a lost phone staying valid for this long, which is why
#: `revoke_all_for_worker` exists.
TTL_DAYS = 30
TOKEN_BYTES = 32


class RefreshError(Exception):
    """Unknown, expired, revoked or reused.

    Raised by the route *after* committing, never from inside `rotate` -- see
    the note there.
    """


@dataclass(frozen=True, slots=True)
class IssuedRefresh:
    token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RotationResult:
    """Outcome of a rotation attempt.

    A result object rather than an exception because `rotate` runs inside the
    caller's transaction: raising would roll back the revocations it had just
    performed, so a detected token reuse would revoke nothing at all. The whole
    point of reuse detection is the revocation, and it was silently a no-op
    until a test caught it.
    """

    worker: FieldWorker | None = None
    issued: IssuedRefresh | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.worker is not None and self.issued is not None


def _now() -> datetime:
    return datetime.now(UTC)


def hash_token(token: str) -> str:
    from app.config import get_settings

    secret = get_settings().supabase_jwt_secret.encode()
    return hmac.new(secret, token.encode(), hashlib.sha256).hexdigest()


async def issue(session: AsyncSession, worker: FieldWorker) -> IssuedRefresh:
    token = secrets.token_urlsafe(TOKEN_BYTES)
    expires_at = _now() + timedelta(days=TTL_DAYS)
    session.add(
        RefreshToken(
            worker_id=worker.id,
            token_hash=hash_token(token),
            expires_at=expires_at,
        )
    )
    await session.flush()
    return IssuedRefresh(token=token, expires_at=expires_at)


async def rotate(session: AsyncSession, token: str) -> RotationResult:
    """Exchange a refresh token for a new one and its worker.

    A token that has already been rotated is not merely rejected -- every token
    for that worker is revoked. Presenting a spent token means it leaked, and
    letting the real device carry on would leave the attacker's copy working
    too.

    Returns a `RotationResult`; see that class for why this does not raise.
    """
    digest = hash_token(token)
    record = (
        await session.execute(select(RefreshToken).where(RefreshToken.token_hash == digest))
    ).scalar_one_or_none()

    if record is None:
        return RotationResult(error="unknown refresh token")

    if record.revoked_at is not None:
        if record.revoked_reason == "rotated":
            # This revocation must survive the failure, which is exactly why
            # this function returns instead of raising.
            await revoke_all_for_worker(session, record.worker_id, reason="reuse_detected")
            return RotationResult(error="refresh token reuse detected; all sessions revoked")
        return RotationResult(error="refresh token revoked")

    if record.expires_at <= _now():
        return RotationResult(error="refresh token expired")

    worker = (
        await session.execute(select(FieldWorker).where(FieldWorker.id == record.worker_id))
    ).scalar_one_or_none()
    if worker is None:
        return RotationResult(error="worker no longer exists")

    issued = await issue(session, worker)
    record.revoked_at = _now()
    record.revoked_reason = "rotated"
    record.replaced_by = hash_token(issued.token)
    record.last_used_at = _now()
    return RotationResult(worker=worker, issued=issued)


async def revoke(session: AsyncSession, token: str, *, reason: str = "signed_out") -> None:
    """Sign out one device. Unknown tokens are ignored, not reported."""
    digest = hash_token(token)
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == digest, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now(), revoked_reason=reason)
    )


async def revoke_all_for_worker(session: AsyncSession, worker_id, *, reason: str) -> None:
    """Sign out every device for one worker. The answer to a lost phone."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.worker_id == worker_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now(), revoked_reason=reason)
    )
