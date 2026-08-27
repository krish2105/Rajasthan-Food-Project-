"""Field worker / official accounts (Section 5, Section 10).

Phase 1 authenticates these via a dev-only token endpoint. Phase 6 replaces the
identity source with phone OTP; this table already holds the phone number that
flow will use, so no migration is needed then.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_col, uuid_pk

ROLES = ("field_worker", "district_official", "state_admin")


class FieldWorker(Base):
    __tablename__ = "field_workers"

    id = uuid_pk()
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    # NULL for district and state roles -- their scope is the district column.
    awc_code: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("awcs.awc_code", ondelete="RESTRICT")
    )
    district: Mapped[str | None] = mapped_column(String(64))
    created_at = created_at_col()

    __table_args__ = (
        CheckConstraint(
            "role IN ('field_worker','district_official','state_admin')",
            name="ck_field_workers_role",
        ),
        # A field worker without an AWC would have no scope at all; a state
        # admin with one would imply a scope that is then ignored. Both are
        # configuration bugs that RLS cannot catch, so the schema catches them.
        CheckConstraint(
            "(role = 'field_worker' AND awc_code IS NOT NULL AND district IS NOT NULL)"
            " OR (role = 'district_official' AND awc_code IS NULL AND district IS NOT NULL)"
            " OR (role = 'state_admin' AND awc_code IS NULL)",
            name="ck_field_workers_scope_matches_role",
        ),
        Index("ix_field_workers_awc_code", "awc_code"),
        Index("ix_field_workers_district", "district"),
    )
