"""Storage guards that need no network.

The HTTP calls themselves are stubbed in the API tests. What matters here is the
logic wrapped around them: the path convention that Storage RLS depends on, the
upload validation, and which credential each mode presents.
"""

from __future__ import annotations

import uuid

import pytest

from app.config import get_settings
from app.core.principal import Principal, Role
from app.storage import supabase_storage as storage


def _principal(token: str = "caller-jwt") -> Principal:
    return Principal(
        worker_id=str(uuid.uuid4()),
        role=Role.FIELD_WORKER,
        awc_code="TEST-A1",
        district="Banswara",
        token=token,
    )


def test_object_path_puts_the_awc_code_first() -> None:
    """Storage RLS matches on `(storage.foldername(name))[1]`, so the AWC code
    leading the path is a security property, not a naming convention."""
    b, c = uuid.uuid4(), uuid.uuid4()
    assert storage.object_path("TEST-A1", b, c, "jpg") == f"TEST-A1/{b}/{c}.jpg"


def test_rls_mode_presents_the_callers_own_token(monkeypatch) -> None:
    """This is what makes Supabase Storage policies load-bearing rather than
    decorative -- the service key would bypass them entirely."""
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_mode", "rls")
    monkeypatch.setattr(settings, "supabase_service_key", "SERVICE-KEY")
    assert storage._auth_token(_principal("caller-jwt")) == "caller-jwt"


def test_service_mode_falls_back_to_the_service_key(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_mode", "service")
    monkeypatch.setattr(settings, "supabase_service_key", "SERVICE-KEY")
    assert storage._auth_token(_principal("caller-jwt")) == "SERVICE-KEY"


def test_rls_mode_without_a_token_does_not_silently_use_the_service_key_path(
    monkeypatch,
) -> None:
    """An anonymous principal in rls mode falls back to the service key, which
    is a real widening -- pinned here so the behaviour is deliberate and visible
    rather than discovered later."""
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_mode", "rls")
    monkeypatch.setattr(settings, "supabase_service_key", "SERVICE-KEY")
    assert storage._auth_token(None) == "SERVICE-KEY"


async def test_upload_rejects_an_unsupported_content_type() -> None:
    with pytest.raises(storage.StorageError, match="unsupported content type"):
        await storage.upload_photo(
            path="a/b/c.pdf", data=b"%PDF", content_type="application/pdf"
        )


async def test_upload_rejects_an_oversized_photo() -> None:
    """A basic Android camera can produce a file large enough to matter on a
    metered rural connection (Section 7)."""
    oversized = b"\x00" * (storage.MAX_PHOTO_BYTES + 1)
    with pytest.raises(storage.StorageError, match="exceeds"):
        await storage.upload_photo(
            path="a/b/c.jpg", data=oversized, content_type="image/jpeg"
        )


async def test_upload_raises_a_clear_error_when_storage_is_unconfigured(monkeypatch) -> None:
    """The API turns this into a 503 with the setup doc named, rather than a
    confusing stack trace."""
    settings = get_settings()
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_service_key", "")
    with pytest.raises(storage.StorageNotConfigured, match="phase1-supabase-setup"):
        await storage.upload_photo(path="a/b/c.jpg", data=b"x", content_type="image/jpeg")


def test_signed_urls_are_short_lived() -> None:
    """They are handed to a dashboard for immediate rendering, not stored."""
    assert storage.SIGNED_URL_TTL_SECONDS <= 900
