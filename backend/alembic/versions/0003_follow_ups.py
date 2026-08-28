"""Follow-up records against flagged compliance days (Section 15).

Revision ID: 0003
Revises: 0002

Append-only by construction: INSERT and SELECT are granted, UPDATE and DELETE
are not. This matches the decision in 0002 that no non-owner role may edit any
record in this system, and it matters more here than elsewhere -- a record of
what an official did about a flagged kitchen is worth nothing if it can be
rewritten afterwards.

Scoping follows Section 10. A district official reads and writes follow-ups
within their own district; a state admin reads everything and writes nothing,
because they are not the person who visited the centre. A field worker sees
none of it: this is an oversight record about their own kitchen, and putting it
in front of them changes what gets photographed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

IN_DISTRICT = (
    "(app.claim('app_role') = 'district_official' "
    "AND district = app.claim('district'))"
)
IS_STATE_ADMIN = "app.claim('app_role') = 'state_admin'"


def upgrade() -> None:
    op.create_table(
        "follow_ups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("compliance_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("menu_compliance.id", ondelete="CASCADE"), nullable=False),
        sa.Column("awc_code", sa.String(32), nullable=False),
        sa.Column("district", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("recorded_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("field_workers.id", ondelete="SET NULL")),
        sa.Column("recorded_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('visited','contacted','no_action_needed','escalated')",
            name="ck_follow_ups_outcome",
        ),
        sa.CheckConstraint(
            "outcome <> 'no_action_needed' OR (note IS NOT NULL AND length(trim(note)) > 0)",
            name="ck_follow_ups_no_action_needs_reason",
        ),
    )
    op.create_index("ix_follow_ups_compliance", "follow_ups", ["compliance_id"])
    op.create_index("ix_follow_ups_district_recorded", "follow_ups", ["district", "recorded_at"])

    op.execute("ALTER TABLE follow_ups ENABLE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT, INSERT ON follow_ups TO authenticated")

    op.execute(
        f"""
        CREATE POLICY follow_ups_read ON follow_ups FOR SELECT TO authenticated
        USING ({IS_STATE_ADMIN} OR {IN_DISTRICT})
        """
    )
    # Only the district official writes. A state admin reading a district's
    # follow-ups is oversight; a state admin recording one would be claiming to
    # have visited a centre they did not.
    op.execute(
        f"""
        CREATE POLICY follow_ups_insert ON follow_ups FOR INSERT TO authenticated
        WITH CHECK ({IN_DISTRICT})
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS follow_ups_insert ON follow_ups")
    op.execute("DROP POLICY IF EXISTS follow_ups_read ON follow_ups")
    op.execute("REVOKE ALL ON follow_ups FROM authenticated")
    op.drop_table("follow_ups")
