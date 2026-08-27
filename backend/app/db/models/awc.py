"""Anganwadi centre / Ashram school master record.

Deviation D3. Section 5 uses `awc_code` as a bare string in four tables with no
master record behind it. That leaves nowhere to put the centre's name, its type,
or its coordinates -- all of which the dashboard phases need, and none of which
belong duplicated on every beneficiary row.

Bilingual columns (D5) are here rather than in a frontend string table because
the Phase 3 Field PWA is offline-first: a Hindi/English toggle must not require
a network round-trip, so both languages ship in the same cached payload.
"""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col

CENTRE_TYPES = ("anganwadi", "ashram_school")


class AWC(Base):
    __tablename__ = "awcs"

    awc_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name_en: Mapped[str] = mapped_column(String(160), nullable=False)
    name_hi: Mapped[str] = mapped_column(String(160), nullable=False)
    # Drives which WHO reference the children here will mostly need, and which
    # PM POSHAN menu cycle applies.
    centre_type: Mapped[str] = mapped_column(String(20), nullable=False)
    district: Mapped[str] = mapped_column(String(64), nullable=False)
    district_hi: Mapped[str] = mapped_column(String(64), nullable=False)
    block: Mapped[str] = mapped_column(String(64), nullable=False)
    block_hi: Mapped[str] = mapped_column(String(64), nullable=False)
    # Real coordinates, so the Phase 5 district map is not fiction.
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at = created_at_col()

    __table_args__ = (
        CheckConstraint("centre_type IN ('anganwadi','ashram_school')", name="ck_awcs_centre_type"),
        Index("ix_awcs_district", "district"),
    )
