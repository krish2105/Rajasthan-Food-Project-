"""Supabase Storage access for plate photos (Sections 7, 11, 12).

Two modes, selected by STORAGE_MODE:

  * ``rls`` (default) -- every call carries the *caller's* JWT, so Supabase
    Storage evaluates its own policies against the same `awc_code` claim
    Postgres uses. Storage is then genuinely part of the security boundary.
  * ``service`` -- fallback for projects that no longer expose a legacy HS256
    JWT secret, where our tokens cannot be validated by Supabase. Calls use the
    service key and scope is enforced only in application code. Postgres RLS is
    unaffected either way. Documented in docs/phase1-supabase-setup.md.

The object path is always ``{awc_code}/{beneficiary_id}/{capture_id}.jpg``. The
first segment is what the Storage policy matches on, which is why the path is
built here from the authenticated principal rather than from anything the client
sends.

Photos are of *plates*, never of children (Section 12). Nothing in this module
should ever be repurposed to store an image of a person.
"""

from __future__ import annotations

import uuid

import httpx

from app.config import get_settings
from app.core.principal import Principal

#: Signed URLs are deliberately short-lived: they are handed to a dashboard for
#: immediate rendering, not stored or shared.
SIGNED_URL_TTL_SECONDS = 300

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_PHOTO_BYTES = 8 * 1024 * 1024


class StorageError(RuntimeError):
    pass


class StorageNotConfigured(StorageError):
    pass


def object_path(awc_code: str, beneficiary_id: uuid.UUID, capture_id: uuid.UUID, ext: str) -> str:
    return f"{awc_code}/{beneficiary_id}/{capture_id}.{ext}"


def _auth_token(principal: Principal | None) -> str:
    settings = get_settings()
    if settings.storage_mode == "rls" and principal is not None and principal.token:
        return principal.token
    return settings.supabase_service_key


def _headers(principal: Principal | None) -> dict[str, str]:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {_auth_token(principal)}",
        "apikey": settings.supabase_service_key,
    }


def _require_config() -> tuple[str, str]:
    settings = get_settings()
    if not settings.storage_configured:
        raise StorageNotConfigured(
            "SUPABASE_URL / SUPABASE_SERVICE_KEY are not set; see docs/phase1-supabase-setup.md"
        )
    return settings.supabase_url.rstrip("/"), settings.supabase_storage_bucket


async def upload_photo(
    *, path: str, data: bytes, content_type: str, principal: Principal | None = None
) -> str:
    """Upload one plate photo and return its storage path."""
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise StorageError(f"unsupported content type {content_type!r}")
    if len(data) > MAX_PHOTO_BYTES:
        raise StorageError(f"photo exceeds {MAX_PHOTO_BYTES} bytes")
    base, bucket = _require_config()
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{base}/storage/v1/object/{bucket}/{path}",
            content=data,
            headers={
                **_headers(principal),
                "Content-Type": content_type,
                "x-upsert": "true",
            },
        )
    if resp.status_code >= 400:
        raise StorageError(f"upload failed ({resp.status_code}): {resp.text[:300]}")
    return path


async def create_signed_url(
    *, path: str, principal: Principal | None = None, ttl: int = SIGNED_URL_TTL_SECONDS
) -> str:
    base, bucket = _require_config()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{base}/storage/v1/object/sign/{bucket}/{path}",
            json={"expiresIn": ttl},
            headers=_headers(principal),
        )
    if resp.status_code >= 400:
        raise StorageError(f"signing failed ({resp.status_code}): {resp.text[:300]}")
    signed = resp.json().get("signedURL") or resp.json().get("signedUrl")
    if not signed:
        raise StorageError("Supabase returned no signed URL")
    return f"{base}/storage/v1{signed}" if signed.startswith("/") else signed


async def ensure_bucket() -> None:
    """Create the private bucket if it is missing. Used by the seed script."""
    base, bucket = _require_config()
    settings = get_settings()
    headers = {
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "apikey": settings.supabase_service_key,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        existing = await client.get(f"{base}/storage/v1/bucket/{bucket}", headers=headers)
        if existing.status_code == 200:
            return
        created = await client.post(
            f"{base}/storage/v1/bucket",
            json={"name": bucket, "id": bucket, "public": False},
            headers=headers,
        )
    if created.status_code >= 400 and "already exists" not in created.text.lower():
        raise StorageError(f"bucket create failed ({created.status_code}): {created.text[:300]}")
