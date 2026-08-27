"""Plate capture upload and retrieval (Sections 5, 7, 8, 12).

Phase 2 added inference, but only *after* the response is sent. The ordering is
Section 7's and it is the point of the whole design:

    photo -> Storage  ->  row written 'pending'  ->  RESPONSE RETURNS
                                                 ->  background: infer, update row

A field worker never waits for a model, and a rate limit or an outage leaves the
row 'failed' with a reason and the photograph intact, not lost. `POST
/captures/{id}/reprocess` re-runs a failed one; without it a transient free-tier
failure would strand a capture permanently, which Section 7's retry-safe
requirement does not allow.

Section 12: these are photographs of plates. There is no endpoint here, and must
never be one, that stores an image of a child.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import select

from app.ai import tasks as ai_tasks
from app.api.deps import CurrentPrincipal, ScopedSession, require_role
from app.config import get_settings
from app.core.principal import Role
from app.db.models import Beneficiary, PlateCapture
from app.db.models.plate_capture import MEAL_TYPES
from app.schemas.common import Page
from app.schemas.entities import PlateCaptureOut
from app.storage import supabase_storage as storage

#: Spelled as a literal: Starlette renamed its 422 constant, and pinning to
#: either spelling breaks on the other version.
HTTP_422 = 422

router = APIRouter(prefix="/captures", tags=["captures"])

_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


async def _with_signed_url(row: PlateCapture, principal: CurrentPrincipal) -> PlateCaptureOut:
    out = PlateCaptureOut.model_validate(row)
    try:
        out.photo_signed_url = await storage.create_signed_url(
            path=row.photo_url, principal=principal
        )
    except storage.StorageError:
        # A dashboard that renders rows without thumbnails is far better than
        # one that 500s because Storage is briefly unreachable. The path is
        # still returned, so the image can be fetched later.
        out.photo_signed_url = None
    return out


@router.post(
    "",
    response_model=PlateCaptureOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(Role.FIELD_WORKER))],
)
async def create_capture(
    session: ScopedSession,
    principal: CurrentPrincipal,
    background: BackgroundTasks,
    beneficiary_id: uuid.UUID = Form(...),
    meal_type: str = Form(...),
    captured_at: datetime | None = Form(default=None),
    photo: UploadFile = File(...),
) -> PlateCaptureOut:
    if meal_type not in MEAL_TYPES:
        raise HTTPException(
            status_code=HTTP_422,
            detail=f"meal_type must be one of {MEAL_TYPES}",
        )
    content_type = (photo.content_type or "").split(";")[0].strip()
    if content_type not in _EXT:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"unsupported image type {content_type!r}",
        )

    child = (
        await session.execute(select(Beneficiary).where(Beneficiary.id == beneficiary_id))
    ).scalar_one_or_none()
    if child is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="beneficiary not found")

    data = await photo.read()
    if not data:
        raise HTTPException(status_code=HTTP_422, detail="empty photo")

    capture_id = uuid.uuid4()
    # The path's first segment is the AWC code taken from the *child record*,
    # not from the request, and that segment is what the Storage RLS policy
    # matches. A client cannot steer an upload into another school's folder.
    path = storage.object_path(child.awc_code, child.id, capture_id, _EXT[content_type])
    try:
        await storage.upload_photo(
            path=path, data=data, content_type=content_type, principal=principal
        )
    except storage.StorageNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except storage.StorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    row = PlateCapture(
        id=capture_id,
        beneficiary_id=child.id,
        awc_code=child.awc_code,
        district=child.district,
        photo_url=path,
        meal_type=meal_type,
        captured_at=captured_at or datetime.now(UTC),
        sync_status="pending",  # Phase 2 moves this to 'synced' or 'failed'
        field_worker_id=uuid.UUID(principal.worker_id) if principal.worker_id else None,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)

    # Queued, not awaited. Everything above has already committed the evidence;
    # nothing below can take the capture away.
    settings = get_settings()
    if settings.ai_enabled and settings.ai_configured:
        background.add_task(ai_tasks.process_capture, row.id)

    return await _with_signed_url(row, principal)


@router.post(
    "/{capture_id}/reprocess",
    response_model=PlateCaptureOut,
    dependencies=[Depends(require_role(Role.FIELD_WORKER, Role.DISTRICT_OFFICIAL))],
)
async def reprocess_capture(
    capture_id: uuid.UUID,
    session: ScopedSession,
    principal: CurrentPrincipal,
    background: BackgroundTasks,
) -> PlateCaptureOut:
    """Re-queue a capture whose inference failed.

    Section 7 requires the pipeline to be retry-safe. Free-tier rate limits are
    a routine, transient condition rather than an exceptional one, so there has
    to be a way to pick a capture back up; otherwise one busy afternoon
    permanently strands a day's evidence.

    RLS decides visibility: a worker can only reprocess a capture they can see,
    and an out-of-scope id is a 404 like everywhere else.
    """
    row = (
        await session.execute(select(PlateCapture).where(PlateCapture.id == capture_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if row.sync_status == "synced":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="capture is already processed; nothing to reprocess",
        )

    settings = get_settings()
    if not (settings.ai_enabled and settings.ai_configured):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI pipeline is not enabled or not configured",
        )

    background.add_task(ai_tasks.process_capture, row.id)
    return await _with_signed_url(row, principal)


@router.get("", response_model=Page[PlateCaptureOut])
async def list_captures(
    session: ScopedSession,
    principal: CurrentPrincipal,
    beneficiary_id: uuid.UUID | None = None,
    awc_code: str | None = None,
    sync_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[PlateCaptureOut]:
    stmt = select(PlateCapture).order_by(PlateCapture.captured_at.desc())
    if beneficiary_id:
        stmt = stmt.where(PlateCapture.beneficiary_id == beneficiary_id)
    if awc_code:
        stmt = stmt.where(PlateCapture.awc_code == awc_code)
    if sync_status:
        stmt = stmt.where(PlateCapture.sync_status == sync_status)
    rows = list((await session.execute(stmt.limit(limit + 1))).scalars().all())
    has_more = len(rows) > limit
    items = [await _with_signed_url(r, principal) for r in rows[:limit]]
    return Page[PlateCaptureOut](items=items, has_more=has_more)


@router.get("/{capture_id}", response_model=PlateCaptureOut)
async def get_capture(
    capture_id: uuid.UUID, session: ScopedSession, principal: CurrentPrincipal
) -> PlateCaptureOut:
    row = (
        await session.execute(select(PlateCapture).where(PlateCapture.id == capture_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return await _with_signed_url(row, principal)
