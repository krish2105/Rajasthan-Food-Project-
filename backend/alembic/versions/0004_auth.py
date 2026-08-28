"""Phone-OTP sign-in and refresh tokens (Sections 4, 10, 11).

Revision ID: 0004
Revises: 0003

Both tables get row-level security enabled and no policies whatsoever, which
denies the `authenticated` role everything. That is deliberate rather than an
oversight: the authentication flow runs before a caller has an identity and uses
the owner connection, so nothing reaching these tables through a request session
has any business seeing a one-time code or somebody else's refresh token.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "otp_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("delivery_status", sa.String(32)),
        sa.Column("delivery_detail", sa.Text),
    )
    op.create_index("ix_otp_codes_phone_created", "otp_codes", ["phone", "created_at"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("worker_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("field_workers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_reason", sa.String(32)),
        sa.Column("replaced_by", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_refresh_tokens_worker", "refresh_tokens", ["worker_id"])
    op.create_index("ix_refresh_tokens_expires", "refresh_tokens", ["expires_at"])

    # RLS on, no policies, no grants: the authenticated role can reach neither
    # table at all. The auth flow uses the owner connection by necessity.
    for table in ("otp_codes", "refresh_tokens"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("refresh_tokens")
    op.drop_table("otp_codes")
