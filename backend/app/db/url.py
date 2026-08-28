"""Normalise and validate the Postgres connection string.

Every way into this database -- the API, Alembic, the seed script, the Supabase
preflight check -- reads DATABASE_URL. When that value is wrong, SQLAlchemy
raises `ArgumentError: Could not parse SQLAlchemy URL from given URL string`
about forty frames deep, naming neither the variable nor the mistake. This
module turns the three mistakes that actually happen into one sentence that
says what to fix.

Two of them are unambiguous typos and are simply corrected: Supabase hands out
`postgresql://`, while this application needs the asyncpg driver, and the
Connect dialog presents the string already wrapped in a `psql "..."` command
that is easy to copy whole. Rewriting those is safe because there is exactly
one correct interpretation.

The other two are refused rather than repaired, because both produce a system
that starts cleanly and is subtly wrong: an unfilled placeholder would connect
to nothing, and the transaction pooler on port 6543 does not guarantee that
`SET LOCAL` survives a statement -- which silently disables every row-level
security policy this application's authorisation model rests on.
"""

from __future__ import annotations

import re

#: The scheme Supabase hands out, and the one this application needs.
_SYNC_SCHEME = "postgresql://"
_ASYNC_SCHEME = "postgresql+asyncpg://"

#: Supabase's Connect dialog shows the string inside a ready-to-run command.
_PSQL_WRAPPED = re.compile(r"""^\s*psql\s+["']?(?P<url>[^"']+)["']?\s*$""")

#: Left-in placeholders, from .env.example and from Supabase's own dialog.
_PLACEHOLDERS = ("<", ">", "[YOUR-PASSWORD]", "[YOUR_PASSWORD]", "YOUR-PASSWORD")

#: Supabase's transaction pooler. See the module docstring.
_TRANSACTION_POOLER_PORT = ":6543"


class DatabaseUrlError(ValueError):
    """A DATABASE_URL that cannot be used, with an explanation a human can act on."""


def normalise_database_url(raw: str) -> str:
    """Return a usable asyncpg URL, or raise DatabaseUrlError explaining why not.

    Callers should let the message reach the terminal unchanged; it names the
    specific mistake rather than the symptom.
    """
    url = (raw or "").strip().strip("'\"").strip()

    if not url:
        raise DatabaseUrlError(
            "DATABASE_URL is not set.\n"
            "  Supabase dashboard -> Connect -> Session pooler, then copy the URI.\n"
            "  See docs/phase1-supabase-setup.md."
        )

    wrapped = _PSQL_WRAPPED.match(url)
    if wrapped:
        # Supabase shows `psql "postgresql://..."`. Copying the whole line is
        # the single most common way this value arrives broken.
        url = wrapped.group("url").strip()

    if any(token in url for token in _PLACEHOLDERS):
        raise DatabaseUrlError(
            "DATABASE_URL still contains a placeholder, so it points at no real database.\n"
            f"  Got: {redact(url)}\n"
            "  Replace the bracketed part with your project ref and database password."
        )

    if not url.startswith((_SYNC_SCHEME, _ASYNC_SCHEME)):
        raise DatabaseUrlError(
            "DATABASE_URL does not look like a Postgres connection string.\n"
            f"  Got: {redact(url)}\n"
            f"  Expected it to begin with {_SYNC_SCHEME} or {_ASYNC_SCHEME}"
        )

    if _TRANSACTION_POOLER_PORT in url:
        raise DatabaseUrlError(
            "DATABASE_URL points at Supabase's transaction pooler (port 6543).\n"
            "  Use the SESSION pooler on port 5432 instead.\n"
            "  Row-level security here depends on SET LOCAL surviving the\n"
            "  transaction, which the transaction pooler does not guarantee --\n"
            "  so 6543 would start cleanly and enforce no access control at all."
        )

    if url.startswith(_SYNC_SCHEME):
        # Unambiguous: asyncpg is the only driver this application uses.
        url = _ASYNC_SCHEME + url[len(_SYNC_SCHEME) :]

    return url


def redact(url: str) -> str:
    """Mask the password so a connection string can be shown in a log or error."""
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:***@", url)
