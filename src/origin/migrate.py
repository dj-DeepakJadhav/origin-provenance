"""Schema migration with per-statement reporting.

``sql/002_vector_index.sql`` is *expected* to partially fail on some CockroachDB
Cloud plans — vector-index DDL varies by version, and zone configuration is
restricted on Basic/Serverless. That is survivable (the bitemporal columns carry
the long horizon without it), but only if the operator can see exactly which
statements applied. A migrator that reports "done" after swallowing three errors
is worse than no migrator.

So statements are applied individually, each outcome is recorded, and the
summary distinguishes *applied*, *skipped as already-present*, and *failed*.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg

from . import db

log = logging.getLogger(__name__)

SQL_DIR = Path(__file__).resolve().parent.parent.parent / "sql"

#: Errors that mean "this already exists", which is success on a re-run.
_ALREADY_EXISTS = re.compile(
    r"already exists|duplicate (object|column)", re.IGNORECASE
)


@dataclass(frozen=True)
class StatementResult:
    ordinal: int
    #: First line of the statement, for identifying it in output without
    #: dumping the whole thing.
    preview: str
    status: str  # applied | skipped | failed
    error: str | None = None


@dataclass(frozen=True)
class FileResult:
    path: Path
    statements: tuple[StatementResult, ...]

    @property
    def applied(self) -> int:
        return sum(1 for s in self.statements if s.status == "applied")

    @property
    def skipped(self) -> int:
        return sum(1 for s in self.statements if s.status == "skipped")

    @property
    def failed(self) -> tuple[StatementResult, ...]:
        return tuple(s for s in self.statements if s.status == "failed")

    @property
    def ok(self) -> bool:
        return not self.failed


def strip_comments(sql: str) -> str:
    """Remove ``--`` line comments, leaving string literals intact.

    Naive comment stripping corrupts any literal containing a double dash. Our
    schema does not have one today, but a migrator that silently mangles SQL is
    the kind of bug that surfaces at the worst possible time.
    """
    out: list[str] = []
    in_string = False
    i = 0
    while i < len(sql):
        char = sql[i]

        if in_string:
            out.append(char)
            if char == "'":
                # '' is an escaped quote inside a literal, not a terminator.
                if i + 1 < len(sql) and sql[i + 1] == "'":
                    out.append(sql[i + 1])
                    i += 2
                    continue
                in_string = False
            i += 1
            continue

        if char == "'":
            in_string = True
            out.append(char)
            i += 1
            continue

        if char == "-" and i + 1 < len(sql) and sql[i + 1] == "-":
            # Skip to end of line, preserving the newline as a separator.
            newline = sql.find("\n", i)
            if newline == -1:
                break
            i = newline
            continue

        out.append(char)
        i += 1

    return "".join(out)


def split_statements(sql: str) -> list[str]:
    """Split SQL on semicolons that are not inside string literals."""
    cleaned = strip_comments(sql)
    statements: list[str] = []
    current: list[str] = []
    in_string = False
    i = 0

    while i < len(cleaned):
        char = cleaned[i]

        if in_string:
            current.append(char)
            if char == "'":
                if i + 1 < len(cleaned) and cleaned[i + 1] == "'":
                    current.append(cleaned[i + 1])
                    i += 2
                    continue
                in_string = False
            i += 1
            continue

        if char == "'":
            in_string = True
            current.append(char)
            i += 1
            continue

        if char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            i += 1
            continue

        current.append(char)
        i += 1

    trailing = "".join(current).strip()
    if trailing:
        statements.append(trailing)

    return statements


def _preview(statement: str, width: int = 72) -> str:
    collapsed = " ".join(statement.split())
    if len(collapsed) <= width:
        return collapsed
    return collapsed[: width - 1] + "…"


def apply_file(conn: psycopg.Connection, path: Path) -> FileResult:
    """Apply one SQL file, statement by statement.

    Each statement gets its own transaction so one failure does not abort the
    rest — which is the entire point for ``002``, where the vector index may
    apply while the zone configuration is rejected.
    """
    sql = path.read_text(encoding="utf-8")
    results: list[StatementResult] = []

    for ordinal, statement in enumerate(split_statements(sql), start=1):
        preview = _preview(statement)
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(statement)
            results.append(StatementResult(ordinal, preview, "applied"))
            log.info("applied [%d] %s", ordinal, preview)
        except psycopg.Error as exc:
            message = str(exc).strip()
            if _ALREADY_EXISTS.search(message):
                results.append(StatementResult(ordinal, preview, "skipped"))
                log.info("already present [%d] %s", ordinal, preview)
            else:
                results.append(
                    StatementResult(ordinal, preview, "failed", error=message)
                )
                log.warning("FAILED [%d] %s -- %s", ordinal, preview, message)

    return FileResult(path=path, statements=tuple(results))


def migrate(sql_dir: Path | None = None) -> list[FileResult]:
    """Apply every ``NNN_*.sql`` file in order.

    Returns a result per file. Callers decide what to do about failures; this
    function does not raise on them, because a partial apply of ``002`` is an
    expected and acceptable outcome that the operator must be told about rather
    than protected from.
    """
    directory = sql_dir or SQL_DIR
    files = sorted(directory.glob("[0-9][0-9][0-9]_*.sql"))
    if not files:
        raise FileNotFoundError(f"no migration files found in {directory}")

    results: list[FileResult] = []
    # One connection for the whole run, but each statement is its own
    # transaction. Autocommit lets DDL that cannot run inside an explicit
    # transaction still succeed.
    conn = db.connect()
    try:
        for path in files:
            results.append(apply_file(conn, path))
    finally:
        conn.close()

    return results
