"""Tests for DATABASE_URL normalisation.

Each case here is a mistake that actually reached a terminal during
deployment, not a hypothetical. The value of this module is that a wrong
connection string produces one actionable sentence instead of an
`ArgumentError` raised forty frames inside SQLAlchemy.
"""

from __future__ import annotations

import pytest

from app.db.url import DatabaseUrlError, normalise_database_url, redact

_HOST = "aws-0-ap-south-1.pooler.supabase.com:5432/postgres"
GOOD = f"postgresql://postgres.abcdef:s3cret@{_HOST}"
ASYNC = f"postgresql+asyncpg://postgres.abcdef:s3cret@{_HOST}"


class TestAccepted:
    def test_rewrites_supabase_scheme_to_asyncpg(self):
        # Supabase hands out postgresql://; this app needs the asyncpg driver.
        assert normalise_database_url(GOOD) == ASYNC

    def test_leaves_an_already_correct_url_alone(self):
        assert normalise_database_url(ASYNC) == ASYNC

    def test_unwraps_the_psql_command_supabase_displays(self):
        # The Connect dialog shows a ready-to-run `psql "..."` line, and
        # copying the whole line is how this arrived broken in practice.
        assert normalise_database_url(f'psql "{GOOD}"') == ASYNC
        assert normalise_database_url(f"psql '{GOOD}'") == ASYNC
        assert normalise_database_url(f"psql {GOOD}") == ASYNC

    def test_strips_surrounding_quotes_and_whitespace(self):
        assert normalise_database_url(f"  '{GOOD}'  ") == ASYNC

    def test_preserves_a_password_containing_an_at_sign(self):
        url = "postgresql://postgres.abc:p@ss:word@host.supabase.com:5432/postgres"
        assert normalise_database_url(url).endswith("@host.supabase.com:5432/postgres")
        assert "p@ss:word" in normalise_database_url(url)


class TestRefused:
    def test_empty_names_the_variable(self):
        with pytest.raises(DatabaseUrlError, match="DATABASE_URL is not set"):
            normalise_database_url("")

    def test_whitespace_only_is_treated_as_empty(self):
        with pytest.raises(DatabaseUrlError, match="not set"):
            normalise_database_url("   ")

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql+asyncpg://postgres.<project-ref>:<password>@host:5432/postgres",
            "postgresql://postgres.abc:[YOUR-PASSWORD]@host:5432/postgres",
            "postgresql://postgres.abc:[YOUR_PASSWORD]@host:5432/postgres",
        ],
    )
    def test_unfilled_placeholders_are_refused(self, url):
        # These parse cleanly, connect to nothing, and fail much later with a
        # message about authentication rather than about the placeholder.
        with pytest.raises(DatabaseUrlError, match="placeholder"):
            normalise_database_url(url)

    def test_transaction_pooler_is_refused(self):
        # Port 6543 does not guarantee SET LOCAL survives, which would silently
        # disable every RLS policy -- a system that starts cleanly and enforces
        # nothing. Refusing is the only safe behaviour.
        with pytest.raises(DatabaseUrlError, match="transaction pooler"):
            normalise_database_url(GOOD.replace(":5432", ":6543"))

    def test_non_postgres_string_is_refused(self):
        with pytest.raises(DatabaseUrlError, match="does not look like"):
            normalise_database_url("my database")

    def test_mysql_url_is_refused(self):
        with pytest.raises(DatabaseUrlError, match="does not look like"):
            normalise_database_url("mysql://user:pw@host:3306/db")


class TestRedaction:
    def test_password_is_masked(self):
        assert "s3cret" not in redact(GOOD)
        assert "***" in redact(GOOD)

    def test_host_and_user_survive_so_the_error_is_still_useful(self):
        masked = redact(GOOD)
        assert "postgres.abcdef" in masked
        assert "aws-0-ap-south-1.pooler.supabase.com" in masked

    @pytest.mark.parametrize(
        "url_template",
        [
            # Both of these messages quote the offending URL back to the
            # operator, so both must mask the password first.
            "postgresql://postgres.<ref>:{secret}@host:5432/postgres",
            "mysql://postgres.abc:{secret}@host:3306/postgres",
        ],
    )
    def test_messages_that_quote_the_url_never_leak_the_password(self, url_template):
        secret = "hunter2-do-not-print"
        with pytest.raises(DatabaseUrlError) as caught:
            normalise_database_url(url_template.format(secret=secret))
        assert "Got:" in str(caught.value), "this path should quote the URL back"
        assert secret not in str(caught.value)
