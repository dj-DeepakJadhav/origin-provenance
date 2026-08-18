"""Database helpers that do not need a database.

``_as_of_literal`` is a security boundary: its output is interpolated into SQL
because AS OF SYSTEM TIME cannot be parameterized. So the rejection cases are
the important ones.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from origin import db


class TestAsOfLiteral:
    @pytest.mark.parametrize(
        "interval", ["-30s", "-2h", "-7d", "-100ms", "-1.5h", "-500us", "-15m"]
    )
    def test_accepts_negative_intervals(self, interval):
        assert db._as_of_literal(interval) == f"'{interval}'"

    @pytest.mark.parametrize(
        "hostile",
        [
            "-1h'; DROP TABLE documents; --",
            "'; SELECT 1; --",
            "now()",
            "-1h OR 1=1",
            "1h",  # missing sign
            "-1",  # missing unit
            "-1y",  # unsupported unit
            "",
            "   ",
            "--1h",
            "-1h; --",
        ],
    )
    def test_rejects_anything_else(self, hostile):
        """Reject rather than escape. There is no valid reason for these."""
        with pytest.raises(ValueError):
            db._as_of_literal(hostile)

    def test_accepts_aware_datetime(self):
        when = datetime(2026, 7, 3, 14, 22, 7, tzinfo=timezone.utc)
        literal = db._as_of_literal(when)
        assert literal.startswith("'2026-07-03T14:22:07")
        assert literal.endswith("'")

    def test_rejects_naive_datetime(self):
        """A naive timestamp is ambiguous, and ambiguity is not evidence."""
        with pytest.raises(ValueError, match="naive datetime"):
            db._as_of_literal(datetime(2026, 7, 3, 14, 22, 7))

    def test_rejects_future_timestamp(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        with pytest.raises(ValueError, match="future"):
            db._as_of_literal(future)

    def test_rejects_wrong_type(self):
        with pytest.raises(TypeError):
            db._as_of_literal(1234)  # type: ignore[arg-type]


class TestAsOfSystemTime:
    def test_builds_a_clause(self):
        assert db.as_of_system_time("-2h") == "AS OF SYSTEM TIME '-2h'"

    def test_propagates_validation_failure(self):
        with pytest.raises(ValueError):
            db.as_of_system_time("garbage")


class TestVectorLiteral:
    def test_renders_bracketed_list(self):
        assert db.vector_literal([1.0, -0.5, 0.25]) == "[1.0,-0.5,0.25]"

    def test_coerces_ints_to_floats(self):
        assert db.vector_literal([1, 2]) == "[1.0,2.0]"

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            db.vector_literal([])
