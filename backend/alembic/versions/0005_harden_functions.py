"""Harden security-relevant functions flagged by the Supabase database linter.

Two findings, both on functions rather than tables.

`app.claim` is called by every row-level security policy in migration 0002, so
it sits inside the authorisation boundary. It was created without a fixed
`search_path`, which means the schemas it resolves names through depend on the
caller's setting. Pinning it removes a class of shadowing attack against the
one function every policy depends on. pg_catalog is always searched implicitly,
so an empty path still resolves the built-ins the body uses.

`public.rls_auto_enable` is not ours -- Supabase creates it when a project
enables "automatic RLS" at creation. It is SECURITY DEFINER and lands in the
API-exposed `public` schema, so both `anon` and `authenticated` can invoke it
over PostgREST. Nothing in this application calls it; the event trigger that
uses it runs as the owner. Revoking EXECUTE keeps the protection and removes
the remote surface. Guarded by an existence check, because the function is
absent on projects created without that option.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER FUNCTION app.claim(text) SET search_path = ''")

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public' AND p.proname = 'rls_auto_enable'
            ) THEN
                REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM PUBLIC;
                REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM anon;
                REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM authenticated;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER FUNCTION app.claim(text) RESET search_path")
    # The grants on rls_auto_enable are deliberately not restored: re-exposing
    # a SECURITY DEFINER function to anon is not a state worth being able to
    # return to.
