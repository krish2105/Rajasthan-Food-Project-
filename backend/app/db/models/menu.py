"""PM POSHAN menu vocabulary and daily compliance (Section 5).

Deviation D4: `menu_items` is a real table so the JSONB item lists reference
bilingual records with a stable code, instead of embedding raw English strings a
Hindi-first UI cannot render. `ifct_code` is nullable now and populated in
Phase 2, when the IFCT 2017 nutrition lookup arrives.

`menu_compliance` is the Gadchiroli-precedent feature: prescribed five items,
served four. Phase 1 stores and serves these rows; Phase 2 computes them from
plate captures.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = uuid_pk()
    code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    name_hi: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    # Populated in Phase 2 from IFCT 2017 (Section 4). Nullable until then.
    ifct_code: Mapped[str | None] = mapped_column(String(32))
    created_at = created_at_col()


class MenuCompliance(Base):
    __tablename__ = "menu_compliance"

    id = uuid_pk()
    awc_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("awcs.awc_code", ondelete="CASCADE"), nullable=False
    )
    district: Mapped[str] = mapped_column(String(64), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    prescribed_items: Mapped[list] = mapped_column(JSONB, nullable=False)
    detected_items: Mapped[list] = mapped_column(JSONB, nullable=False)
    compliance_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    flag_reason: Mapped[str | None] = mapped_column(Text)
    created_at = created_at_col()

    __table_args__ = (
        CheckConstraint(
            "compliance_pct IS NULL OR (compliance_pct >= 0 AND compliance_pct <= 100)",
            name="ck_compliance_pct_range",
        ),
        # A flagged day with no stated reason is useless to the officer who has
        # to follow it up, so the schema refuses one.
        CheckConstraint(
            "flagged = false OR flag_reason IS NOT NULL",
            name="ck_compliance_flag_has_reason",
        ),
        UniqueConstraint("awc_code", "date", name="uq_compliance_awc_date"),
        Index("ix_compliance_awc_date", "awc_code", "date"),
        Index("ix_compliance_district_date", "district", "date"),
    )
