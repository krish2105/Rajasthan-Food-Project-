"""JWT minting and verification.

Tokens are signed HS256 with Supabase's own project JWT secret. That is a
deliberate choice, not a convenience: it means one token is simultaneously
valid for our FastAPI routes, for the Postgres session claims that drive RLS,
and for Supabase Storage's own policies -- so there is exactly one identity in
the system rather than three that can drift apart.

Phase 6 replaces `mint_token`'s caller (the dev endpoint) with a real phone-OTP
flow plus refresh tokens. The claim shape, the RLS policies and every route stay
untouched, which is the whole point of building the scope model first.
"""

from __future__ import annotations

import time

import jwt

from app.config import get_settings
from app.core.principal import Principal, Role


class TokenError(Exception):
    """The bearer token is missing, malformed, expired or badly signed."""


def mint_token(principal: Principal) -> tuple[str, int]:
    """Return (encoded_jwt, expires_in_seconds)."""
    settings = get_settings()
    now = int(time.time())
    ttl = settings.jwt_ttl_seconds
    payload = {
        **principal.claims(),
        "name": principal.name,
        "iat": now,
        "exp": now + ttl,
        "aud": "authenticated",
    }
    token = jwt.encode(payload, settings.supabase_jwt_secret, algorithm=settings.jwt_algorithm)
    return token, ttl


def decode_token(token: str) -> Principal:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("token is invalid") from exc

    try:
        role = Role(payload["app_role"])
    except (KeyError, ValueError) as exc:
        raise TokenError("token carries no recognised app_role") from exc

    return Principal(
        worker_id=str(payload.get("sub", "")),
        role=role,
        awc_code=payload.get("awc_code"),
        district=payload.get("district"),
        name=payload.get("name", ""),
        token=token,
    )
