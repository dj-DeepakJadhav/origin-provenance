"""SQL comment stripping and statement splitting.

Naive splitting on ';' corrupts any statement containing a semicolon or double
dash inside a string literal. Our schema has none today, but a migrator that
silently mangles SQL fails at the worst possible moment, so the behaviour is
pinned here.
"""

from __future__ import annotations

from pathlib import Path

from origin.migrate import SQL_DIR, split_statements, strip_comments


class TestStripComments:
    def test_removes_line_comments(self):
        assert "comment" not in strip_comments("SELECT 1; -- a comment\nSELECT 2;")

    def test_keeps_the_sql_around_a_comment(self):
        out = strip_comments("SELECT 1; -- note\nSELECT 2;")
        assert "SELECT 1" in out
        assert "SELECT 2" in out

    def test_preserves_double_dash_inside_a_string_literal(self):
        sql = "SELECT 'a -- not a comment' AS x;"
        assert "not a comment" in strip_comments(sql)

    def test_preserves_escaped_quotes(self):
        sql = "SELECT 'it''s fine -- really';"
        out = strip_comments(sql)
        assert "it''s fine -- really" in out

    def test_comment_at_end_without_newline(self):
        assert "SELECT 1" in strip_comments("SELECT 1; -- trailing")


class TestSplitStatements:
    def test_splits_on_semicolons(self):
        assert split_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]

    def test_ignores_semicolons_inside_literals(self):
        statements = split_statements("SELECT 'a;b' AS x; SELECT 2;")
        assert len(statements) == 2
        assert "a;b" in statements[0]

    def test_handles_a_missing_trailing_semicolon(self):
        assert split_statements("SELECT 1") == ["SELECT 1"]

    def test_drops_empty_statements(self):
        assert split_statements("SELECT 1;;;  ; SELECT 2;") == [
            "SELECT 1",
            "SELECT 2",
        ]

    def test_comment_only_input_yields_nothing(self):
        assert split_statements("-- just a comment\n-- another\n") == []

    def test_empty_input(self):
        assert split_statements("") == []

    def test_multiline_statement_stays_together(self):
        sql = "CREATE TABLE t (\n  a INT,\n  b STRING\n);"
        statements = split_statements(sql)
        assert len(statements) == 1
        assert "CREATE TABLE t" in statements[0]


class TestRealSchemaFiles:
    """Parse the actual migrations. Catches a schema edit that breaks splitting."""

    def test_sql_directory_is_found(self):
        assert SQL_DIR.is_dir(), f"expected migrations at {SQL_DIR}"

    def test_migration_files_are_discovered_in_order(self):
        """Assert the properties that matter, not an exact filename list.

        The first version of this test hardcoded the list and broke the moment a
        migration was added — which made the suite punish schema changes instead
        of protecting them.
        """
        files = sorted(SQL_DIR.glob("[0-9][0-9][0-9]_*.sql"))
        names = [f.name for f in files]

        assert names, "no migrations discovered"
        assert names[0] == "001_schema.sql", "the core schema must apply first"

        prefixes = [int(n[:3]) for n in names]
        assert prefixes == sorted(prefixes), "glob ordering must be numeric"
        assert len(set(prefixes)) == len(prefixes), (
            f"duplicate migration numbers in {names} — two files with the same "
            "prefix apply in an undefined order"
        )
        assert prefixes == list(range(1, len(prefixes) + 1)), (
            f"migration numbers must be contiguous from 001, got {prefixes}; a "
            "gap usually means a file was renamed or lost"
        )

    def test_every_migration_parses(self):
        for path in sorted(SQL_DIR.glob("[0-9][0-9][0-9]_*.sql")):
            statements = split_statements(path.read_text(encoding="utf-8"))
            assert statements, f"{path.name} produced no statements"

    def test_core_schema_splits_into_plausible_statements(self):
        sql = (SQL_DIR / "001_schema.sql").read_text(encoding="utf-8")
        statements = split_statements(sql)
        # CREATE DATABASE, SET, and nine CREATE TABLEs.
        assert len(statements) >= 10
        creates = [s for s in statements if s.upper().startswith("CREATE TABLE")]
        assert len(creates) >= 8, f"only found {len(creates)} CREATE TABLE statements"

    def test_no_statement_retains_a_comment_marker(self):
        for name in ["001_schema.sql", "002_vector_index.sql"]:
            sql = (SQL_DIR / name).read_text(encoding="utf-8")
            for statement in split_statements(sql):
                assert "--" not in statement, (
                    f"comment leaked into a statement in {name}: {statement[:80]}"
                )

    def test_ttl_literal_survives_splitting(self):
        """`ttl_expire_after = '30 days'` must stay attached to its statement."""
        sql = (SQL_DIR / "001_schema.sql").read_text(encoding="utf-8")
        ttl = [s for s in split_statements(sql) if "ttl_expire_after" in s]
        assert len(ttl) == 1
        assert "retrieval_log" in ttl[0]

    def test_vector_index_file_has_the_expected_statements(self):
        sql = (SQL_DIR / "002_vector_index.sql").read_text(encoding="utf-8")
        statements = split_statements(sql)
        assert any("VECTOR INDEX" in s.upper() for s in statements)
        assert sum(1 for s in statements if "CONFIGURE ZONE" in s.upper()) == 2
