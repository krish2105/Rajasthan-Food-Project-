"""Plate photo captures -- the new thing this system adds (Section 5).

All `ai_*` columns are NULL in Phase 1 by design. Phase 2 fills them from the
Gemini/Groq pipeline; `ai_model_version` exists from day one so every estimate
is attributable to the model that produced it (Section 6.5's audit trail).

`sync_status` is the server-side half of the Section 7 offline queue: a capture
arrives as 'pending', and the Phase 2 background task moves it to 'synced' or
'failed'. A failed AI call must never lose the photo, so the row is written
before any inference is attempted.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk

MEAL_TYPES = ("breakfast", "lunch", "thr")
SYNC_STATES = ("pending", "synced", "failed")


class PlateCapture(Base):
    __tablename__ = "plate_captures"

    id = uuid_pk()
    beneficiary_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("beneficiaries.id", ondelete="CASCADE"),
        nullable=False,
    )
    awc_code: Mapped[str] = mapped_column(String(32), nullable=False)
    district: Mapped[str] = mapped_column(String(64), nullable=False)

    # Storage object path, always '{awc_code}/{beneficiary_id}/{capture_id}.jpg'.
    # The leading path segment is what the Storage RLS policy matches on, so the
    # convention is load-bearing rather than cosmetic.
    photo_url: Mapped[str] = mapped_column(Text, nullable=False)
    meal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sync_status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")

    # --- Phase 2 (AI pipeline) fills everything below ----------------------
    ai_food_items: Mapped[dict | None] = mapped_column(JSONB)
    ai_calories: Mapped[float | None] = mapped_column(Numeric(6, 1))
    ai_protein_g: Mapped[float | None] = mapped_column(Numeric(5, 1))
    ai_carbs_g: Mapped[float | None] = mapped_column(Numeric(5, 1))
    ai_model_version: Mapped[str | None] = mapped_column(String(64))
    ai_error: Mapped[str | None] = mapped_column(Text)

    field_worker_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("field_workers.id", ondelete="SET NULL")
    )
    created_at = created_at_col()

    __table_args__ = (
        CheckConstraint("meal_type IN ('breakfast','lunch','thr')", name="ck_captures_meal_type"),
        CheckConstraint(
            "sync_status IN ('pending','synced','failed')", name="ck_captures_sync_status"
        ),
        Index("ix_captures_beneficiary_captured", "beneficiary_id", "captured_at"),
        Index("ix_captures_awc_captured", "awc_code", "captured_at"),
        Index("ix_captures_district", "district"),
        Index("ix_captures_sync_status", "sync_status"),
    )
