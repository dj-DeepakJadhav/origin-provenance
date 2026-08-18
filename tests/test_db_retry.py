"""Serialization-failure retry.

Regression guard for a defect that survived seven commits. ``transaction()`` used
to wrap its ``yield`` in a retry loop, which is invalid for a ``@contextmanager``:
the generator must yield exactly once, so the first genuine serialization failure
raised ``RuntimeError: generator didn't stop`` instead of retrying. Retry-on-40001
was a stated production property that had never once worked, and it stayed hidden
until a test finally produced real contention.

The retry now lives in ``run_in_transaction``, which takes the body as a callable
and can therefore actually replay it. These tests drive the retry loop with a fake
connection so they need no cluster and no luck.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from psycopg import errors as pg_errors

from origin import db


class FlakyConnection:
    """Fails with SerializationFailure for the first ``fail_times`` attempts."""

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.attempts = 0
        self.closed = False

    def transaction(self):
        connection = self

        class _Txn:
            def __enter__(self):
                connection.attempts += 1
                return self

            def __exit__(self, exc_type, exc, tb):
                if connection.attempts <= connection.fail_times:
                    raise pg_errors.SerializationFailure("simulated 40001")
                return False

        return _Txn()

    def cursor(self):
        cursor = MagicMock()
        cursor.__enter__ = lambda s: cursor
        cursor.__exit__ = lambda s, *a: False
        return cursor

    def close(self):
        self.closed = True


@pytest.fixture
def no_sleep(monkeypatch):
    """Backoff is real in production and pointless in tests."""
    monkeypatch.setattr(db.time, "sleep", lambda _s: None)


class TestRunInTransaction:
    def test_succeeds_without_retry_when_there_is_no_conflict(
        self, monkeypatch, no_sleep
    ):
        conn = FlakyConnection(fail_times=0)
        monkeypatch.setattr(db, "connect", lambda: conn)

        result = db.run_in_transaction(lambda cur: "done")

        assert result == "done"
        assert conn.attempts == 1
        assert conn.closed, "the connection must be closed even on the happy path"

    def test_retries_and_eventually_succeeds(self, monkeypatch, no_sleep):
        """The behaviour that never worked before."""
        conn = FlakyConnection(fail_times=2)
        monkeypatch.setattr(db, "connect", lambda: conn)

        calls: list[int] = []

        def body(cur):
            calls.append(1)
            return "committed"

        assert db.run_in_transaction(body) == "committed"
        assert conn.attempts == 3, "expected two failures then a success"
        assert len(calls) == 3, "the body must actually be replayed"

    def test_gives_up_after_max_retries_with_an_actionable_error(
        self, monkeypatch, no_sleep
    ):
        conn = FlakyConnection(fail_times=99)
        monkeypatch.setattr(db, "connect", lambda: conn)

        with pytest.raises(db.SerializationRetriesExhausted, match="contention"):
            db.run_in_transaction(lambda cur: "never", max_retries=3)

        assert conn.attempts == 3

    def test_original_error_is_preserved_as_the_cause(self, monkeypatch, no_sleep):
        conn = FlakyConnection(fail_times=99)
        monkeypatch.setattr(db, "connect", lambda: conn)

        with pytest.raises(db.SerializationRetriesExhausted) as caught:
            db.run_in_transaction(lambda cur: None, max_retries=2)

        assert isinstance(caught.value.__cause__, pg_errors.SerializationFailure)

    def test_connection_is_closed_even_when_retries_are_exhausted(
        self, monkeypatch, no_sleep
    ):
        conn = FlakyConnection(fail_times=99)
        monkeypatch.setattr(db, "connect", lambda: conn)

        with pytest.raises(db.SerializationRetriesExhausted):
            db.run_in_transaction(lambda cur: None, max_retries=2)

        assert conn.closed

    def test_a_non_serialization_error_is_not_retried(self, monkeypatch, no_sleep):
        """Retrying a genuine bug would just run it repeatedly."""
        conn = FlakyConnection(fail_times=0)
        monkeypatch.setattr(db, "connect", lambda: conn)

        def body(cur):
            raise ValueError("a real bug, not contention")

        with pytest.raises(ValueError, match="a real bug"):
            db.run_in_transaction(body)

        assert conn.attempts == 1
        assert conn.closed

    def test_backoff_grows_between_attempts(self, monkeypatch):
        """Exponential, so sustained contention does not become a hot loop."""
        conn = FlakyConnection(fail_times=3)
        monkeypatch.setattr(db, "connect", lambda: conn)
        slept: list[float] = []
        monkeypatch.setattr(db.time, "sleep", lambda s: slept.append(s))

        db.run_in_transaction(lambda cur: "ok")

        assert len(slept) == 3
        assert slept == sorted(slept), f"backoff must not shrink: {slept}"
        assert slept[-1] > slept[0]


class TestTransactionIsHonestAboutNotRetrying:
    def test_transaction_does_not_swallow_a_serialization_failure(
        self, monkeypatch
    ):
        """It must propagate, not produce 'generator didn't stop'.

        That RuntimeError was the visible symptom of the old broken retry, and it
        masked the real error — so an operator saw a contextlib internal instead
        of a database conflict.
        """
        conn = FlakyConnection(fail_times=1)
        monkeypatch.setattr(db, "connect", lambda: conn)

        with pytest.raises(pg_errors.SerializationFailure):
            with db.transaction() as cur:
                del cur

        assert conn.attempts == 1
        assert conn.closed
