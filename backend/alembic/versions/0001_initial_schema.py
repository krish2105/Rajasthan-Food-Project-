"""Initial schema: Section 5 data model plus deviations D1-D5.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TABLES = (
    "awcs",
    "field_workers",
    "beneficiaries",
    "growth_entries",
    "plate_captures",
    "menu_items",
    "menu_compliance",
)


def upgrade() -> None:
    # gen_random_uuid() ships with Postgres 13+, but pgcrypto is what Supabase
    # projects historically relied on. Enabling it is idempotent and cheap.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "awcs",
        sa.Column("awc_code", sa.String(32), primary_key=True),
        sa.Column("name_en", sa.String(160), nullable=False),
        sa.Column("name_hi", sa.String(160), nullable=False),
        sa.Column("centre_type", sa.String(20), nullable=False),
        sa.Column("district", sa.String(64), nullable=False),
        sa.Column("district_hi", sa.String(64), nullable=False),
        sa.Column("block", sa.String(64), nullable=False),
        sa.Column("block_hi", sa.String(64), nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6)),
        sa.Column("longitude", sa.Numeric(9, 6)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("centre_type IN ('anganwadi','ashram_school')", name="ck_awcs_centre_type"),
    )
    op.create_index("ix_awcs_district", "awcs", ["district"])

    op.create_table(
        "field_workers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("phone", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("awc_code", sa.String(32), sa.ForeignKey("awcs.awc_code", ondelete="RESTRICT")),
        sa.Column("district", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "role IN ('field_worker','district_official','state_admin')",
            name="ck_field_workers_role",
        ),
        sa.CheckConstraint(
            "(role = 'field_worker' AND awc_code IS NOT NULL AND district IS NOT NULL)"
            " OR (role = 'district_official' AND awc_code IS NULL AND district IS NOT NULL)"
            " OR (role = 'state_admin' AND awc_code IS NULL)",
            name="ck_field_workers_scope_matches_role",
        ),
    )
    op.create_index("ix_field_workers_awc_code", "field_workers", ["awc_code"])
    op.create_index("ix_field_workers_district", "field_workers", ["district"])

    op.create_table(
        "beneficiaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("poshan_tracker_id", sa.String(64), unique=True),
        sa.Column("awc_code", sa.String(32), sa.ForeignKey("awcs.awc_code", ondelete="RESTRICT"), nullable=False),
        sa.Column("district", sa.String(64), nullable=False),
        sa.Column("block", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("dob", sa.Date, nullable=False),
        sa.Column("gender", sa.String(1), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("gender IN ('M','F','O')", name="ck_beneficiaries_gender"),
        sa.CheckConstraint("dob <= CURRENT_DATE", name="ck_beneficiaries_dob_not_future"),
    )
    op.create_index("ix_beneficiaries_awc_code", "beneficiaries", ["awc_code"])
    op.create_index("ix_beneficiaries_district", "beneficiaries", ["district"])
    op.execute("CREATE INDEX ix_beneficiaries_name_lower ON beneficiaries (lower(name))")

    op.create_table(
        "growth_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("beneficiary_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("beneficiaries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("awc_code", sa.String(32), nullable=False),
        sa.Column("district", sa.String(64), nullable=False),
        sa.Column("recorded_at", sa.Date, nullable=False),
        sa.Column("height_cm", sa.Numeric(5, 2), nullable=False),
        sa.Column("weight_kg", sa.Numeric(5, 2), nullable=False),
        sa.Column("age_months", sa.Integer, nullable=False),
        sa.Column("standard_used", sa.String(24), nullable=False),
        sa.Column("waz_score", sa.Numeric(4, 2)),
        sa.Column("haz_score", sa.Numeric(4, 2)),
        sa.Column("whz_score", sa.Numeric(4, 2)),
        sa.Column("baz_score", sa.Numeric(4, 2)),
        sa.Column("bmi", sa.Numeric(5, 2)),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("classification_detail", postgresql.JSONB, nullable=False),
        sa.Column("data_quality_flags", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("recorded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("field_workers.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("standard_used IN ('who_2006_0_60m','who_2007_5_19y')", name="ck_growth_standard_used"),
        sa.CheckConstraint("classification IN ('normal','MAM','SAM','stunted','underweight')", name="ck_growth_classification"),
        sa.CheckConstraint(
            "(standard_used = 'who_2006_0_60m' AND baz_score IS NULL)"
            " OR (standard_used = 'who_2007_5_19y' AND whz_score IS NULL)",
            name="ck_growth_index_matches_standard",
        ),
        sa.CheckConstraint("height_cm > 0 AND weight_kg > 0", name="ck_growth_positive"),
        sa.CheckConstraint("age_months >= 0", name="ck_growth_age_nonneg"),
        sa.UniqueConstraint("beneficiary_id", "recorded_at", name="uq_growth_beneficiary_date"),
    )
    op.create_index("ix_growth_beneficiary_recorded", "growth_entries", ["beneficiary_id", "recorded_at"])
    op.create_index("ix_growth_awc_code", "growth_entries", ["awc_code"])
    op.create_index("ix_growth_district", "growth_entries", ["district"])
    op.create_index("ix_growth_classification", "growth_entries", ["classification"])

    op.create_table(
        "plate_captures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("beneficiary_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("beneficiaries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("awc_code", sa.String(32), nullable=False),
        sa.Column("district", sa.String(64), nullable=False),
        sa.Column("photo_url", sa.Text, nullable=False),
        sa.Column("meal_type", sa.String(16), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sync_status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("ai_food_items", postgresql.JSONB),
        sa.Column("ai_calories", sa.Numeric(6, 1)),
        sa.Column("ai_protein_g", sa.Numeric(5, 1)),
        sa.Column("ai_carbs_g", sa.Numeric(5, 1)),
        sa.Column("ai_model_version", sa.String(64)),
        sa.Column("ai_error", sa.Text),
        sa.Column("field_worker_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("field_workers.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("meal_type IN ('breakfast','lunch','thr')", name="ck_captures_meal_type"),
        sa.CheckConstraint("sync_status IN ('pending','synced','failed')", name="ck_captures_sync_status"),
    )
    op.create_index("ix_captures_beneficiary_captured", "plate_captures", ["beneficiary_id", "captured_at"])
    op.create_index("ix_captures_awc_captured", "plate_captures", ["awc_code", "captured_at"])
    op.create_index("ix_captures_district", "plate_captures", ["district"])
    op.create_index("ix_captures_sync_status", "plate_captures", ["sync_status"])

    op.create_table(
        "menu_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(48), nullable=False, unique=True),
        sa.Column("name_en", sa.String(120), nullable=False),
        sa.Column("name_hi", sa.String(120), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("ifct_code", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "menu_compliance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("awc_code", sa.String(32), sa.ForeignKey("awcs.awc_code", ondelete="CASCADE"), nullable=False),
        sa.Column("district", sa.String(64), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("prescribed_items", postgresql.JSONB, nullable=False),
        sa.Column("detected_items", postgresql.JSONB, nullable=False),
        sa.Column("compliance_pct", sa.Numeric(5, 2)),
        sa.Column("flagged", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("flag_reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("compliance_pct IS NULL OR (compliance_pct >= 0 AND compliance_pct <= 100)", name="ck_compliance_pct_range"),
        sa.CheckConstraint("flagged = false OR flag_reason IS NOT NULL", name="ck_compliance_flag_has_reason"),
        sa.UniqueConstraint("awc_code", "date", name="uq_compliance_awc_date"),
    )
    op.create_index("ix_compliance_awc_date", "menu_compliance", ["awc_code", "date"])
    op.create_index("ix_compliance_district_date", "menu_compliance", ["district", "date"])


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
