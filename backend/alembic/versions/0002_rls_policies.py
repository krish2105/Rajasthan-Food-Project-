"""Row-level security: Section 10 scoping enforced by Postgres, not by handlers.

Revision ID: 0002
Revises: 0001

Why this is in the database and not only in Python
--------------------------------------------------
Section 10 says role checks must never be trusted to the client, and Section 11
asks for policies that make cross-AWC access "structurally impossible, not just
impossible via the UI". A `WHERE awc_code = :scope` in a route handler is one
forgotten clause away from a data leak, and nothing catches the omission. A
policy is applied by the planner to every statement on the table, including ones
written years from now by someone who never read Section 10.

How the claims arrive
---------------------
`app/db/session.py` runs `set_config('request.jwt.claims', ..., true)` and then
`SET LOCAL ROLE authenticated` at the start of every request transaction. Both
are transaction-scoped, so nothing leaks between pooled requests.

`app.claim()` is marked STABLE, not VOLATILE: within one statement the claims
cannot change, and STABLE lets the planner evaluate it once instead of once per
row. On a 3,700-row capture table that is the difference between an index scan
and a sequential scan.

Read vs write scope
-------------------
Reads follow the Section 10 hierarchy. Writes are narrower than reads on
purpose: only a `field_worker` may insert captures and growth entries, and only
into their own AWC. A district official can see everything in their district but
cannot fabricate a measurement in it -- which is the correct separation for an
oversight role.
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ALL_TABLES = (
    "awcs",
    "field_workers",
    "beneficiaries",
    "growth_entries",
    "plate_captures",
    "menu_items",
    "menu_compliance",
)

# Reusable scope predicates. `app.claim('app_role')` is our three-role model
# from Section 10; the Postgres role is always `authenticated`.
IS_STATE_ADMIN = "app.claim('app_role') = 'state_admin'"
IN_DISTRICT = "(app.claim('app_role') = 'district_official' AND district = app.claim('district'))"
IN_AWC = "(app.claim('app_role') = 'field_worker' AND awc_code = app.claim('awc_code'))"
READ_SCOPE = f"({IS_STATE_ADMIN} OR {IN_DISTRICT} OR {IN_AWC})"
OWN_AWC_WRITE = (
    "(app.claim('app_role') = 'field_worker' AND awc_code = app.claim('awc_code'))"
)


def upgrade() -> None:
    # Supabase projects ship with an `authenticated` role already. A plain
    # Postgres (local development, CI) does not, and every GRANT below would
    # fail without it. Creating it when absent is what lets the RLS test suite
    # run against a local database instead of burning Supabase free-tier quota
    # -- and on Supabase this branch is simply skipped.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                CREATE ROLE authenticated NOLOGIN NOINHERIT;
            END IF;
        END
        $$
        """
    )

    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute("GRANT USAGE ON SCHEMA app TO authenticated")

    # Returns NULL for every failure mode -- setting absent, empty string, or
    # unparseable JSON -- so an unauthenticated or malformed session makes every
    # policy predicate false and sees zero rows.
    #
    # The naive one-line SQL version of this function casts the setting to jsonb
    # directly. When no claims have been stamped, current_setting returns '',
    # and ''::jsonb raises "invalid input syntax for type json". That turns a
    # request that should quietly return nothing into a database error surfacing
    # as a 500 -- and a 500 that differs from an empty 200 is itself a signal
    # about which rows exist. Failing closed and silently is the correct
    # behaviour, so the cast is guarded.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.claim(key text)
        RETURNS text
        LANGUAGE plpgsql
        STABLE
        PARALLEL SAFE
        AS $$
        DECLARE
            raw text;
        BEGIN
            raw := nullif(current_setting('request.jwt.claims', true), '');
            IF raw IS NULL THEN
                RETURN NULL;
            END IF;
            BEGIN
                RETURN nullif(raw::jsonb ->> key, '');
            EXCEPTION WHEN others THEN
                RETURN NULL;
            END;
        END
        $$
        """
    )
    op.execute("GRANT EXECUTE ON FUNCTION app.claim(text) TO authenticated")

    # The `authenticated` role owns nothing, so RLS genuinely constrains it.
    # Without these grants every policy would be moot -- the role could not read
    # the tables at all, and the API would fail closed rather than scoped.
    for table in ALL_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT ON {table} TO authenticated")

    op.execute("GRANT INSERT ON plate_captures TO authenticated")
    op.execute("GRANT INSERT ON growth_entries TO authenticated")

    # --- awcs: scoped by its own primary key / district column --------------
    op.execute(
        f"""
        CREATE POLICY awcs_read ON awcs FOR SELECT TO authenticated
        USING (
            {IS_STATE_ADMIN}
            OR (app.claim('app_role') = 'district_official'
                AND district = app.claim('district'))
            OR (app.claim('app_role') = 'field_worker'
                AND awc_code = app.claim('awc_code'))
        )
        """
    )

    # --- field_workers: you may see yourself, and those you supervise -------
    # A field worker seeing the roster of another school is a small leak, but it
    # is still a leak of staff names, so the same hierarchy applies.
    op.execute(
        f"""
        CREATE POLICY field_workers_read ON field_workers FOR SELECT TO authenticated
        USING (
            {IS_STATE_ADMIN}
            OR id::text = app.claim('sub')
            OR (app.claim('app_role') = 'district_official'
                AND district = app.claim('district'))
        )
        """
    )

    # --- beneficiaries, growth_entries, plate_captures, menu_compliance -----
    for table in ("beneficiaries", "growth_entries", "plate_captures", "menu_compliance"):
        op.execute(
            f"CREATE POLICY {table}_read ON {table} FOR SELECT TO authenticated "
            f"USING ({READ_SCOPE})"
        )

    # --- menu_items: shared reference vocabulary, readable by everyone ------
    # It contains no beneficiary data -- it is the bilingual names of dal and
    # roti. Scoping it would break the offline PWA cache for no privacy gain.
    op.execute(
        "CREATE POLICY menu_items_read ON menu_items FOR SELECT TO authenticated "
        "USING (true)"
    )

    # --- Writes: field workers only, and only into their own AWC -----------
    op.execute(
        f"CREATE POLICY plate_captures_insert ON plate_captures FOR INSERT "
        f"TO authenticated WITH CHECK ({OWN_AWC_WRITE})"
    )
    op.execute(
        f"CREATE POLICY growth_entries_insert ON growth_entries FOR INSERT "
        f"TO authenticated WITH CHECK ({OWN_AWC_WRITE})"
    )
    # No UPDATE or DELETE policy is created anywhere, which means no non-owner
    # can update or delete any row. For a system of record about children that
    # is the correct default: corrections in Phase 6+ should be append-only
    # amendments with an audit trail, not silent in-place edits.


def downgrade() -> None:
    for table in ("beneficiaries", "growth_entries", "plate_captures", "menu_compliance"):
        op.execute(f"DROP POLICY IF EXISTS {table}_read ON {table}")
    op.execute("DROP POLICY IF EXISTS menu_items_read ON menu_items")
    op.execute("DROP POLICY IF EXISTS awcs_read ON awcs")
    op.execute("DROP POLICY IF EXISTS field_workers_read ON field_workers")
    op.execute("DROP POLICY IF EXISTS plate_captures_insert ON plate_captures")
    op.execute("DROP POLICY IF EXISTS growth_entries_insert ON growth_entries")
    for table in ALL_TABLES:
        op.execute(f"REVOKE ALL ON {table} FROM authenticated")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS app.claim(text)")
