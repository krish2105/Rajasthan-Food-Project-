"""Follow-up records against a flagged menu-compliance day.

Section 15 draws the line this table sits on: "this system flags and documents;
it does not itself fix menu non-compliance or food quality -- the intervention
still requires a human administrative response". Recording that response is
documenting it, which is squarely inside what this system is for. Performing it
is not, and nothing here tries to.

Append-only, deliberately. A follow-up is never edited or deleted; a correction
is another row. Migration 0003 grants INSERT and SELECT and no UPDATE or DELETE,
so that is enforced by the database rather than by convention. For a record of
what an official did about a flagged kitchen, an edit history that can be
rewritten is worth less than no history at all.

Several follow-ups may exist for one flagged day. That is the trail: visited on
Tuesday, escalated on Friday.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, uuid_pk

#: What an officer actually did. A closed list, because free text cannot be
#: counted and a District Collector asking "how many flags were acted on" needs
#: a number rather than a pile of prose.
OUTCOMES = ("visited", "contacted", "no_action_needed", "escalated")


class FollowUp(Base):
    __tablename__ = "follow_ups"

    id = uuid_pk()
    compliance_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("menu_compliance.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Denormalised for RLS scoping, same reasoning as everywhere else: a policy
    # that needs a subquery runs per row.
    awc_code: Mapped[str] = mapped_column(String(32), nullable=False)
    district: Mapped[str] = mapped_column(String(64), nullable=False)

    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    recorded_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("field_workers.id", ondelete="SET NULL")
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('visited','contacted','no_action_needed','escalated')",
            name="ck_follow_ups_outcome",
        ),
        # An outcome of "no action needed" without a reason is the one case
        # where a note genuinely matters: it is the officer overruling a flag,
        # and the next person to read the record needs to know why.
        CheckConstraint(
            "outcome <> 'no_action_needed' OR (note IS NOT NULL AND length(trim(note)) > 0)",
            name="ck_follow_ups_no_action_needs_reason",
        ),
        Index("ix_follow_ups_compliance", "compliance_id"),
        Index("ix_follow_ups_district_recorded", "district", "recorded_at"),
    )
