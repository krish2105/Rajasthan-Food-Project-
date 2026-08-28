"""Tables backing phone-OTP sign-in (Sections 4, 10, 11).

Neither table is ever read through the API. The auth flow runs *before* a
caller has an identity, so it uses the owner connection; migration 0004
consequently enables row-level security on both and grants the `authenticated`
role nothing at all. A user who somehow reached these tables through a request
session would see zero rows, which is the correct amount of a one-time code or
somebody else's refresh token to be able to read.

Nothing here stores a secret in the clear. Both the OTP and the refresh token
are kept as HMACs keyed on the server secret, so a copy of the database on its
own does not let anyone sign in.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, uuid_pk


class OtpCode(Base):
    """A one-time code issued to a phone number.

    Rows are kept after use rather than deleted: the request-throttle counts
    recent rows per phone, and an audit of "how many codes were sent to this
    number last night" is worth more than the space saved.
    """

    __tablename__ = "otp_codes"

    id = uuid_pk()
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    #: HMAC-SHA256 of the code, keyed on the server secret. A six-digit code has
    #: only a million possibilities, so a plain hash would be trivially
    #: reversible from a database copy; the keyed HMAC means an attacker needs
    #: the secret as well.
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    #: What the delivery provider said. Kept so an undelivered code can be
    #: distinguished from a code the worker never typed.
    delivery_status: Mapped[str | None] = mapped_column(String(32))
    delivery_detail: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_otp_codes_phone_created", "phone", "created_at"),)


class RefreshToken(Base):
    """A long-lived credential exchanged for short access tokens.

    Section 11 asks for 1-hour JWTs, and Section 7 requires the Field PWA to
    keep working through days without connectivity. Those pull in opposite
    directions, and this is where they are reconciled: the access token stays
    short, and the device holds a refresh token long enough to survive a
    fortnight of bad signal.

    Rotated on every use. A refresh token that is presented twice is either a
    replay or a clone, and both are treated as compromise.
    """

    __tablename__ = "refresh_tokens"

    id = uuid_pk()
    worker_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("field_workers.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Why it was revoked -- 'rotated', 'signed_out', 'reuse_detected'. The last
    #: is the one worth looking for in a log.
    revoked_reason: Mapped[str | None] = mapped_column(String(32))
    #: The token that replaced this one, so a reuse can be traced to its chain.
    replaced_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_refresh_tokens_worker", "worker_id"),
        Index("ix_refresh_tokens_expires", "expires_at"),
    )
