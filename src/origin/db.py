"""CockroachDB access: connections, retries, and point-in-time reads.

Two things here are load-bearing for the rest of the project:

``transaction()``  retries on serialization failures. Under SERIALIZABLE
isolation the database will refuse conflicting transactions rather than let
them interleave incorrectly, and the client is expected to retry. Code that
does not retry appears to work until it is under concurrency, which is when it
matters. See https://www.cockroachlabs.com/docs/stable/transaction-retry-error-reference

``as_of_system_time()``  builds the point-in-time clause. AS OF SYSTEM TIME
cannot be parameterized — the timestamp is part of the query plan, not a bound
value — so it must be interpolated. Everything that reaches interpolation here
is validated first; see ``_as_of_literal``.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import TypeVar
from urllib.parse import parse_qs, urlsplit

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row

from . import config

log = logging.getLogger(__name__)

# CockroachDB returns this SQLSTATE when a transaction must be retried.
SERIALIZATION_FAILURE = "40001"

MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 0.05

T = TypeVar("T")


class SerializationRetriesExhausted(RuntimeError):
    """Repeated serialization conflicts. Sustained contention, not a blip."""

# Only these interval shapes may be interpolated into AS OF SYSTEM TIME.
# e.g. "-30s", "-2h", "-7d". Anything else is rejected rather than escaped,
# because there is no legitimate reason for it to be anything else.
_INTERVAL_PATTERN = re.compile(r"^-\d+(?:\.\d+)?(?:us|ms|s|m|h|d)$")


class TimeTravelBeyondRetention(RuntimeError):
    """The requested timestamp is older than the garbage-collection window.

    This is the honest failure mode of MVCC time travel and the reason ORIGIN
    also keeps explicit admitted_at/removed_at columns. Callers that need an
    unbounded horizon should use the bitemporal path in ``corpus.py`` instead of
    widening the GC window indefinitely.
    """


class TimeTravelBeforeSchema(RuntimeError):
    """The schema did not exist yet at the requested instant.

    Encountered for real: reading as of a moment before the migration ran gives
    ``database "origin" does not exist``. That is not a bug — MVCC rewinds the
    catalog as faithfully as it rewinds the rows, so at that instant there was
    genuinely no such database.

    Worth stating plainly rather than swallowing, because it is evidence the
    time travel is real rather than a timestamp filter over current rows.
    """


#: sslmode values that require a CA bundle to validate the server certificate.
_VERIFYING_MODES = frozenset({"verify-full", "verify-ca"})


def _tls_overrides(url: str) -> dict[str, str]:
    """Supply a CA bundle when the URL asks for verification but names no roots.

    CockroachDB Cloud hands you a connection string ending in
    ``sslmode=verify-full`` and nothing else. libpq then looks for a bundle at
    ``%APPDATA%\\postgresql\\root.crt`` (or ``~/.postgresql/root.crt``), which
    on a fresh machine does not exist — so the connection fails with "root
    certificate file does not exist" and the obvious-looking fix is to downgrade
    sslmode, which turns verification *off*.

    ``sslrootcert=system`` is the documented alternative but does not work with
    libpq's bundled OpenSSL on Windows, which has no CA store: it fails with
    "certificate verify failed", which reads like a bad certificate rather than
    a missing trust store.

    CockroachDB Cloud certificates are publicly trusted, so certifi's bundle
    validates them. Passing it as a connection *keyword* rather than editing the
    URI also sidesteps libpq's URI parser, which rejects unencoded spaces — and
    a repository path containing a space is not the user's problem to solve.

    An explicit ``sslrootcert`` in the URL is always respected; this only fills
    a gap.
    """
    query = parse_qs(urlsplit(url).query)
    sslmode = (query.get("sslmode") or [""])[0].strip().lower()
    sslrootcert = (query.get("sslrootcert") or [""])[0].strip()

    if sslmode not in _VERIFYING_MODES:
        return {}
    # "system" is honoured on platforms where it works; we only override it when
    # it cannot work, which we cannot detect portably — so treat it as unset.
    if sslrootcert and sslrootcert.lower() != "system":
        return {}

    try:
        import certifi
    except ImportError:  # pragma: no cover - certifi is a declared dependency
        log.warning(
            "sslmode=%s requested but certifi is not installed; leaving CA "
            "resolution to libpq",
            sslmode,
        )
        return {}

    return {"sslrootcert": certifi.where()}


def connect() -> psycopg.Connection:
    """Open a new connection. Caller owns closing it.

    Verification is never silently weakened: if the URL says ``verify-full``,
    the connection verifies. See ``_tls_overrides``.
    """
    cfg = config.load()
    url = cfg.require_database()
    return psycopg.connect(url, row_factory=dict_row, **_tls_overrides(url))


@contextmanager
def transaction(
    conn: psycopg.Connection | None = None,
) -> Iterator[psycopg.Cursor]:
    """Run a transaction. Yields a cursor; commits on clean exit, rolls back on error.

    **This does not retry**, and it cannot. An earlier version tried, by wrapping
    the ``yield`` in a retry loop — which is invalid: a ``@contextmanager``
    generator must yield exactly once, so the first real serialization failure
    produced ``RuntimeError: generator didn't stop`` instead of a retry. The
    caller's body lives outside the generator, so a context manager has no way to
    run it again.

    That was not a cosmetic bug. Retry-on-40001 was a stated production property
    and it never worked; it stayed hidden until a test finally created genuine
    contention.

    For code that must survive contention, use ``run_in_transaction``, which takes
    the body as a callable and can therefore actually replay it.
    """
    owns_connection = conn is None
    connection = conn if conn is not None else connect()
    try:
        with connection.transaction():
            with connection.cursor() as cur:
                yield cur
    finally:
        if owns_connection:
            connection.close()


def run_in_transaction(
    body: Callable[[psycopg.Cursor], T],
    *,
    max_retries: int = MAX_RETRIES,
) -> T:
    """Run ``body`` in a transaction, retrying on serialization failure.

    Under SERIALIZABLE the database refuses conflicting transactions rather than
    interleaving them incorrectly, and the client is expected to retry. Code that
    does not appears to work until it is under concurrency, which is exactly when
    it matters.

    ``body`` receives a cursor and **must be idempotent on replay**: it may be
    called more than once. Do not put non-database side effects in it — writing a
    file or calling an API inside a retried body will happen twice.

    Returns whatever ``body`` returns.

    See https://www.cockroachlabs.com/docs/stable/transaction-retry-error-reference
    """
    last_error: Exception | None = None
    connection = connect()
    try:
        for attempt in range(max_retries):
            try:
                with connection.transaction():
                    with connection.cursor() as cur:
                        return body(cur)
            except pg_errors.SerializationFailure as exc:
                last_error = exc
                if attempt == max_retries - 1:
                    break
                # Exponential backoff with a deliberate cap. Contention here is
                # expected and correct — the gate serialises builds of one corpus.
                backoff = BASE_BACKOFF_SECONDS * (2**attempt)
                log.warning(
                    "serialization failure (attempt %d/%d), retrying in %.3fs",
                    attempt + 1,
                    max_retries,
                    backoff,
                )
                time.sleep(backoff)

        raise SerializationRetriesExhausted(
            f"transaction failed after {max_retries} attempts due to repeated "
            "serialization conflicts. This means sustained contention, not a "
            "transient blip — look at what else is writing the same rows."
        ) from last_error
    finally:
        connection.close()


def _as_of_literal(when: datetime | str) -> str:
    """Validate and render a timestamp for AS OF SYSTEM TIME.

    Accepts an aware datetime, or a negative interval string like '-2h'.
    Rejects everything else — this value is interpolated into SQL, so the
    validation is the security boundary.
    """
    if isinstance(when, datetime):
        if when.tzinfo is None:
            raise ValueError(
                "naive datetime rejected: pass an aware datetime so the "
                "instant is unambiguous"
            )
        # Allow up to 10 seconds of clock skew tolerance between local client and DB server clocks
        if when > datetime.now(timezone.utc) + timedelta(seconds=10):
            raise ValueError("cannot read as of a future timestamp")
        # ISO-8601 with offset, quoted as a string literal. The value is fully
        # constrained by datetime's own formatting, so it cannot carry SQL.
        return f"'{when.isoformat()}'"

    if isinstance(when, str):
        candidate = when.strip()
        if not _INTERVAL_PATTERN.match(candidate):
            raise ValueError(
                f"invalid AS OF SYSTEM TIME interval {when!r}; expected a "
                "negative interval such as '-30s', '-2h' or '-7d'"
            )
        return f"'{candidate}'"

    raise TypeError(f"expected datetime or interval string, got {type(when)!r}")


def as_of_system_time(when: datetime | str) -> str:
    """Return an ``AS OF SYSTEM TIME`` clause for the given instant.

    Compose it into a query immediately after the table reference::

        clause = as_of_system_time(ts)
        cur.execute(f"SELECT doc_id FROM corpus_members {clause} WHERE ...")

    The interpolation is safe because ``_as_of_literal`` accepts only aware
    datetimes and a narrow interval grammar.
    """
    return f"AS OF SYSTEM TIME {_as_of_literal(when)}"


@contextmanager
def read_as_of(when: datetime | str) -> Iterator[psycopg.Cursor]:
    """A read-only cursor pinned to a past instant for the whole transaction.

    Preferred over per-statement clauses when several reads must agree with each
    other: pinning the transaction guarantees every statement sees the same
    snapshot, rather than several adjacent ones.

    Raises ``TimeTravelBeyondRetention`` if the instant predates the GC window,
    so the caller can fall back to the bitemporal path instead of receiving a
    confusing database error.
    """
    literal = _as_of_literal(when)
    conn = connect()
    # psycopg3 opens an implicit transaction on first execute, which makes an
    # explicit BEGIN fail with "there is already a transaction in progress".
    # Autocommit hands transaction control back to us, which is required because
    # only `BEGIN AS OF SYSTEM TIME` pins a whole transaction to one instant --
    # per-statement clauses would let adjacent reads land on different snapshots.
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            try:
                cur.execute("BEGIN AS OF SYSTEM TIME " + literal)
            except psycopg.Error as exc:
                raise _translate_time_travel_error(exc, when) from exc

            try:
                yield cur
            except psycopg.Error as exc:
                # Retention and catalog errors surface on the *first statement
                # that resolves a descriptor*, not on BEGIN — so translating
                # only around BEGIN leaves a raw InternalError reaching callers.
                raise _translate_time_travel_error(exc, when) from exc
            finally:
                # A read-only snapshot transaction has nothing to commit, and
                # rolling back avoids holding the snapshot any longer. The
                # transaction may already be aborted, in which case ROLLBACK is
                # still correct but must not mask the original error.
                try:
                    cur.execute("ROLLBACK")
                except psycopg.Error:  # pragma: no cover - cleanup only
                    log.debug("rollback after failed snapshot read", exc_info=True)
    finally:
        conn.close()


def _translate_time_travel_error(
    exc: psycopg.Error, when: datetime | str
) -> Exception:
    """Turn a driver error from a snapshot read into something actionable.

    Returns the exception to raise rather than raising it, so callers keep the
    original as ``__cause__``.
    """
    if isinstance(exc, (pg_errors.InvalidCatalogName, pg_errors.UndefinedTable)):
        return TimeTravelBeforeSchema(
            f"cannot read as of {when!r}: the schema did not exist yet at that "
            "instant. MVCC rewinds the catalog as well as the rows, so this is a "
            "true answer about the past rather than a malfunction. Choose an "
            "instant after the migration ran."
        )

    message = str(exc).lower()
    if (
        "must be after" in message
        or "replica gc threshold" in message
        or "batch timestamp" in message
        or "garbage collection" in message
        or "before cluster creation" in message
        or "gc.ttlseconds" in message
    ):
        return TimeTravelBeyondRetention(
            f"cannot read as of {when!r}: older than the garbage-collection "
            "window. Note that raising gc.ttlseconds on ORIGIN's own tables is "
            "not sufficient — resolving a table descriptor also reads system "
            "ranges, which keep their own (shorter) TTL, so the effective MVCC "
            "horizon is the smaller of the two. Use the bitemporal path "
            "(corpus.membership_as_of with prefer_mvcc=False) for older "
            "instants; it has no horizon."
        )

    return exc


def cluster_logical_timestamp(cur: psycopg.Cursor) -> str:
    """The current transaction's commit timestamp, as the cluster sees it.

    This is the evidentiary anchor written into ``admitted_txn``: it comes from
    the database's own clock inside the committing transaction, not from
    application time, and it is therefore consistent with the MVCC history that
    ``read_as_of`` queries.
    """
    cur.execute("SELECT cluster_logical_timestamp()::STRING AS ts")
    row = cur.fetchone()
    if row is None:  # pragma: no cover - the function always returns a row
        raise RuntimeError("cluster_logical_timestamp() returned no row")
    return row["ts"]


def vector_literal(values: list[float]) -> str:
    """Render an embedding for a VECTOR column.

    psycopg has no native adapter for CockroachDB's VECTOR type, so the value is
    passed as its text form and cast in SQL::

        cur.execute("... VALUES (%s::VECTOR)", (vector_literal(embedding),))
    """
    if not values:
        raise ValueError("refusing to build an empty vector literal")
    return "[" + ",".join(repr(float(v)) for v in values) + "]"
