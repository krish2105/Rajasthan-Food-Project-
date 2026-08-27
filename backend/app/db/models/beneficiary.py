"""Beneficiary registry (Section 5).

Section 12 governs this table: it deliberately references an external Poshan
Tracker ID rather than creating a parallel identity store, and it holds no
photograph, no biometric and no guardian contact -- the minimum that lets a
plate photo be attributed to a child who already exists in Raj-Poshan.
"""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk


class Beneficiary(Base):
    __tablename__ = "beneficiaries"

    id = uuid_pk()
    # Nullable until NIC/WCD integration is confirmed (Section 2's caveat).
    poshan_tracker_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    awc_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("awcs.awc_code", ondelete="RESTRICT"), nullable=False
    )
    # Denormalised from awcs so district-scoped RLS is a column comparison
    # rather than a subquery on every row. Kept honest by a trigger-free
    # invariant: the seed and the API both source it from the AWC record.
    district: Mapped[str] = mapped_column(String(64), nullable=False)
    block: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    dob: Mapped[date] = mapped_column(Date, nullable=False)
    gender: Mapped[str] = mapped_column(String(1), nullable=False)
    created_at = created_at_col()

    __table_args__ = (
        CheckConstraint("gender IN ('M','F','O')", name="ck_beneficiaries_gender"),
        CheckConstraint("dob <= CURRENT_DATE", name="ck_beneficiaries_dob_not_future"),
        Index("ix_beneficiaries_awc_code", "awc_code"),
        Index("ix_beneficiaries_district", "district"),
        Index("ix_beneficiaries_name_trgm", sa.text("lower(name)")),
    )
