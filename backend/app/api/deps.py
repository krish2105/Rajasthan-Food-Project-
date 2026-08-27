"""Request dependencies: who is calling, and a session that enforces their scope.

Section 10's rule is that role checks are server-side and never trusted to the
client. Here that means the route handler never reads a role from a header or a
query parameter -- it gets a `Principal` decoded from a signature-verified JWT,
and the session it receives has already had those claims stamped onto the
Postgres transaction, so the policies in migration 0002 apply to every statement
the handler runs.

`require_role` is a second, coarser gate on top of RLS. RLS decides which *rows*
a caller sees; `require_role` decides whether they may call the endpoint at all.
Both are needed: RLS alone would let a district official POST a growth entry and
get a confusing policy violation instead of a clean 403.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.principal import Principal, Role
from app.core.security import TokenError, decode_token
from app.db.session import rls_session


async def get_principal(
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_bearer_token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_token(authorization.split(" ", 1)[1].strip())
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


async def get_session(principal: CurrentPrincipal) -> AsyncIterator[AsyncSession]:
    async with rls_session(principal) as session:
        yield session


ScopedSession = Annotated[AsyncSession, Depends(get_session)]


def require_role(*allowed: Role):
    """Gate an endpoint to specific roles. RLS still scopes the rows returned."""

    async def _guard(principal: CurrentPrincipal) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"role '{principal.role.value}' may not use this endpoint; "
                    f"allowed: {', '.join(r.value for r in allowed)}"
                ),
            )
        return principal

    return _guard


def preferred_lang(
    lang: str | None = None,
    accept_language: Annotated[str | None, Header()] = None,
) -> str:
    """Resolve a display-language *hint*.

    Deliberately only a hint: every bilingual payload carries both languages
    regardless, so an offline client can toggle without refetching (Section 9.1).
    Hindi is the default because the primary user is an Anganwadi worker and
    Section 9.1 specifies Hindi-first, English second -- not the reverse.
    """
    if lang in {"hi", "en"}:
        return lang
    if accept_language and accept_language.lower().startswith("en"):
        return "en"
    return "hi"


PreferredLang = Annotated[str, Depends(preferred_lang)]
