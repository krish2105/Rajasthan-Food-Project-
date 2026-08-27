"""Growth measurements and their WHO classification (Section 5, Section 6.4).

Deviation D1 lives here. Section 5's draft carried only `whz_score`, which is
undefined above 60 months, so `baz_score` (BMI-for-age) and `standard_used` are
added. `standard_used` is NOT NULL on purpose: every stored z-score must be
traceable to the reference that produced it, otherwise a future reader cannot
tell a legitimately-NULL index from a missing computation.

Deviation D2 adds `classification_detail`, because a child can be stunted and
underweight simultaneously and Section 5's single TEXT column cannot say so.

Nothing in this table is ever written by a model. The columns are populated by
`app/growth/assess.py`, which is pure arithmetic over vendored WHO tables.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk

STANDARDS = ("who_2006_0_60m", "who_2007_5_19y")
CLASSIFICATIONS = ("normal", "MAM", "SAM", "stunted", "underweight")


class GrowthEntry(Base):
    __tablename__ = "growth_entries"

    id = uuid_pk()
    beneficiary_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("beneficiaries.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Denormalised for RLS scoping, same reasoning as beneficiaries.district.
    awc_code: Mapped[str] = mapped_column(String(32), nullable=False)
    district: Mapped[str] = mapped_column(String(64), nullable=False)

    recorded_at: Mapped[date] = mapped_column(Date, nullable=False)
    height_cm: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    weight_kg: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)

    age_months: Mapped[int] = mapped_column(Integer, nullable=False)
    standard_used: Mapped[str] = mapped_column(String(24), nullable=False)  # D1

    waz_score: Mapped[float | None] = mapped_column(Numeric(4, 2))
    haz_score: Mapped[float | None] = mapped_column(Numeric(4, 2))
    whz_score: Mapped[float | None] = mapped_column(Numeric(4, 2))
    baz_score: Mapped[float | None] = mapped_column(Numeric(4, 2))  # D1
    bmi: Mapped[float | None] = mapped_column(Numeric(5, 2))

    classification: Mapped[str] = mapped_column(String(16), nullable=False)
    classification_detail: Mapped[dict] = mapped_column(JSONB, nullable=False)  # D2
    #: WHO Anthro implausible-value flags. Empty list for a clean measurement.
    #: Stored so a flagged row stays identifiable in analysis and in any export.
    data_quality_flags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")

    recorded_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("field_workers.id", ondelete="SET NULL")
    )
    created_at = created_at_col()

    __table_args__ = (
        CheckConstraint(
            "standard_used IN ('who_2006_0_60m','who_2007_5_19y')",
            name="ck_growth_standard_used",
        ),
        CheckConstraint(
            "classification IN ('normal','MAM','SAM','stunted','underweight')",
            name="ck_growth_classification",
        ),
        # D1 as an enforced invariant, not just a convention: weight-for-height
        # must never be populated under the 5-19y reference (WHO does not define
        # it there), and BMI-for-age must never be populated under the 0-60m one.
        CheckConstraint(
            "(standard_used = 'who_2006_0_60m' AND baz_score IS NULL)"
            " OR (standard_used = 'who_2007_5_19y' AND whz_score IS NULL)",
            name="ck_growth_index_matches_standard",
        ),
        CheckConstraint("height_cm > 0 AND weight_kg > 0", name="ck_growth_positive"),
        CheckConstraint("age_months >= 0", name="ck_growth_age_nonneg"),
        # One measurement per child per day: ICDS records monthly, so a repeat
        # on the same date is a double-entry, not a legitimate second reading.
        UniqueConstraint("beneficiary_id", "recorded_at", name="uq_growth_beneficiary_date"),
        Index("ix_growth_beneficiary_recorded", "beneficiary_id", "recorded_at"),
        Index("ix_growth_awc_code", "awc_code"),
        Index("ix_growth_district", "district"),
        Index("ix_growth_classification", "classification"),
    )
