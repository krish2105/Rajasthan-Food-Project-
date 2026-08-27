"""Shared response shapes, including the bilingual and error contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Bilingual(BaseModel):
    """A label carried in both languages, always.

    Section 9.1 puts the Field PWA on an intermittent connection, so a Hindi/
    English toggle cannot afford a network round-trip -- both strings ship
    together and the client switches locally. `?lang=` only sets a preference
    hint; it never removes a language from the payload.
    """

    en: str
    hi: str


class Page[T](BaseModel):
    """Cursor-paginated envelope. Cursors, not offsets, because the Field PWA
    syncs against a list that is being appended to while it reads."""

    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False


class Problem(BaseModel):
    """RFC 7807 problem detail, bilingual (Section 9.1).

    The Hindi title travels with the error so a Hindi-first client needs no
    local string table and cannot fall back to English on an unrecognised code.
    """

    model_config = ConfigDict(populate_by_name=True)

    type: str = "about:blank"
    title_en: str
    title_hi: str
    status: int
    code: str = Field(description="Stable machine-readable error code")
    detail: str | None = None
