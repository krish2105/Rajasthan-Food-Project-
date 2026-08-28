"""Storage bucket and its row-level policies (Sections 7, 11, 12).

Migration 0002 made Postgres enforce scope. Without this migration Supabase
Storage enforced nothing -- `storage.objects` ships with RLS enabled and no
policies, so with STORAGE_MODE=rls, where every call carries the caller's own
JWT, the first photo upload of a demo would be refused. The bucket did not
exist either.

The object path is ``{awc_code}/{beneficiary_id}/{capture_id}.jpg``, so the
first path segment is the AWC code and is what these policies match on.

District officials are scoped through a subquery against `public.awcs` rather
than through the path, which encodes no district. The district is matched
explicitly there, and the subquery is *also* subject to the `awcs` policy from
migration 0002. The explicit filter is the one a reader can verify; the nested
policy is the layer that still holds if this one is ever edited carelessly.

The whole migration is a no-op where the `storage` schema is absent, which is
the case for the local Postgres the test suite runs against. Storage policies
are infrastructure belonging to Supabase, not to the application schema.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

BUCKET = "plate-photos"

# Written as one guarded block so a database without Supabase Storage -- the
# local Postgres used by tests -- skips it entirely rather than failing.
UPGRADE = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'storage') THEN
        RAISE NOTICE 'no storage schema; skipping Supabase Storage policies';
        RETURN;
    END IF;

    -- Private, always. These are photographs taken inside Anganwadi centres;
    -- a public bucket is a public URL for every one of them.
    INSERT INTO storage.buckets (id, name, public)
    VALUES ('{BUCKET}', '{BUCKET}', false)
    ON CONFLICT (id) DO UPDATE SET public = false;

    DROP POLICY IF EXISTS plate_photos_insert ON storage.objects;
    DROP POLICY IF EXISTS plate_photos_read ON storage.objects;

    CREATE POLICY plate_photos_insert ON storage.objects
        FOR INSERT TO authenticated
        WITH CHECK (
            bucket_id = '{BUCKET}'
            AND app.claim('app_role') = 'field_worker'
            AND (storage.foldername(name))[1] = app.claim('awc_code')
        );

    CREATE POLICY plate_photos_read ON storage.objects
        FOR SELECT TO authenticated
        USING (
            bucket_id = '{BUCKET}'
            AND (
                app.claim('app_role') = 'state_admin'
                OR (
                    app.claim('app_role') = 'field_worker'
                    AND (storage.foldername(name))[1] = app.claim('awc_code')
                )
                OR (
                    app.claim('app_role') = 'district_official'
                    AND (storage.foldername(name))[1] IN (
                        SELECT awc_code FROM public.awcs
                        WHERE district = app.claim('district')
                    )
                )
            )
        );
END
$$;
"""

DOWNGRADE = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'storage') THEN
        RETURN;
    END IF;
    DROP POLICY IF EXISTS plate_photos_insert ON storage.objects;
    DROP POLICY IF EXISTS plate_photos_read ON storage.objects;
END
$$;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    # The bucket is deliberately left in place: dropping it would delete every
    # photograph it holds, which no downgrade should do silently.
    op.execute(DOWNGRADE)
