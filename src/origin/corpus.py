"""Corpus membership over time, and the questions that only history can answer.

The central capability: *what was in this corpus at a given instant, and which
answers used a document that must now come out?*

Membership is derivable two independent ways, and ORIGIN uses both on purpose:

  **MVCC** (``AS OF SYSTEM TIME``) reads the rows as the cluster actually stored
  them at that instant. Application code cannot forge it. Bounded by the
  garbage-collection window.

  **Bitemporal** (``admitted_at`` / ``removed_at``) is unbounded and survives GC,
  but it is application-maintained and therefore only as honest as this module.

Neither alone is evidence. Agreement between them is. ``verify_integrity``
compares them, and a mismatch means the bitemporal record has been altered
outside the ledger's own writes — which is exactly the thing an auditor is
looking for.

Regulatory shape, for the reader who wants it: point-in-time membership is what
EU AI Act **Art 53(1)(d)** asks for when it requires a training-content summary
carrying a stated date and version history, and the atomicity in
``record_answer`` is the record-keeping property **Art 12** is after. Both are
mapped, with their limits — including the fact that a retrieval corpus is not
training data — in docs/COMPLIANCE.md.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from . import db

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Membership:
    doc_ids: frozenset[str]
    #: "mvcc" or "bitemporal" — recorded because it changes how much the answer
    #: is worth. An answer from MVCC is unforgeable; one from the columns is
    #: trustworthy only if this module is.
    source: str
    as_of: datetime | str

    def __len__(self) -> int:
        return len(self.doc_ids)


@dataclass(frozen=True)
class IntegrityResult:
    consistent: bool
    mvcc_only: frozenset[str] = field(default_factory=frozenset)
    bitemporal_only: frozenset[str] = field(default_factory=frozenset)
    #: Set when MVCC could not reach back far enough, in which case the check is
    #: inconclusive rather than passing. Silence here would be a false all-clear.
    skipped_reason: str | None = None

    @property
    def conclusive(self) -> bool:
        return self.skipped_reason is None


@dataclass(frozen=True)
class AffectedAnswer:
    answer_id: str
    asked_at: datetime
    asked_by: str | None
    question: str
    rank: int | None


def create_corpus(
    *,
    name: str,
    declared_use: str,
    description: str | None = None,
) -> str:
    """Create a corpus, or return the existing one with this name.

    ``declared_use`` is what the build gate enforces against, so it is validated
    here rather than trusted. A corpus with a nonsense declared use would block
    every document at gate time, which reads as a licence problem rather than a
    configuration mistake.
    """
    from .licensing.policy import DECLARED_USES

    use = (declared_use or "").strip().lower()
    if use not in DECLARED_USES:
        raise ValueError(
            f"declared_use must be one of {', '.join(DECLARED_USES)}, got "
            f"{declared_use!r}"
        )

    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO corpora (name, declared_use, description)
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO NOTHING
            RETURNING corpus_id
            """,
            (name, use, description),
        )
        row = cur.fetchone()
        if row is not None:
            return str(row["corpus_id"])

        # Already existed. Return its id, but do not silently repurpose a corpus
        # that was declared for a different use — that would change what the gate
        # enforces without anyone asking for it.
        cur.execute(
            "SELECT corpus_id, declared_use FROM corpora WHERE name = %s",
            (name,),
        )
        existing = cur.fetchone()
        if existing["declared_use"] != use:
            raise ValueError(
                f"corpus {name!r} already exists with declared_use="
                f"{existing['declared_use']!r}, refusing to change it to {use!r}. "
                "Create a differently-named corpus instead."
            )
        return str(existing["corpus_id"])


def list_corpora() -> list[dict]:
    """All corpora with their current member counts."""
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT c.corpus_id, c.name, c.declared_use, c.created_at,
                   count(m.doc_id) FILTER (WHERE m.removed_at IS NULL) AS members
            FROM corpora c
            LEFT JOIN corpus_members m ON m.corpus_id = c.corpus_id
            GROUP BY c.corpus_id, c.name, c.declared_use, c.created_at
            ORDER BY c.name
            """
        )
        return [dict(r) for r in cur.fetchall()]


def resolve_corpus(name_or_id: str) -> str:
    """Accept either a corpus name or its UUID, return the UUID."""
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT corpus_id FROM corpora
            WHERE name = %s OR corpus_id::STRING = %s
            """,
            (name_or_id, name_or_id),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"no corpus named or identified by {name_or_id!r}")
        return str(row["corpus_id"])


def current_members(corpus_id: str) -> frozenset[str]:
    """Documents currently in the corpus."""
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT doc_id FROM corpus_members
            WHERE corpus_id = %s AND removed_at IS NULL
            """,
            (corpus_id,),
        )
        return frozenset(r["doc_id"] for r in cur.fetchall())


def membership_as_of(
    corpus_id: str,
    when: datetime | str,
    *,
    prefer_mvcc: bool = True,
) -> Membership:
    """Corpus membership at a past instant.

    Tries MVCC first when ``prefer_mvcc``, because that answer cannot be forged.
    Falls back to the bitemporal columns when the instant predates the GC window,
    and records which path produced the answer so callers can weigh it.
    """
    if prefer_mvcc:
        try:
            with db.read_as_of(when) as cur:
                cur.execute(
                    """
                    SELECT doc_id FROM corpus_members
                    WHERE corpus_id = %s AND removed_at IS NULL
                    """,
                    (corpus_id,),
                )
                return Membership(
                    doc_ids=frozenset(r["doc_id"] for r in cur.fetchall()),
                    source="mvcc",
                    as_of=when,
                )
        except db.TimeTravelBeyondRetention:
            log.info(
                "instant %r predates the GC window; using the bitemporal path",
                when,
            )
        except db.TimeTravelBeforeSchema:
            # The catalog did not exist then, so storage history cannot answer.
            # The bitemporal columns still can: no rows satisfy admitted_at <=
            # that instant, which is the correct answer of "nothing".
            log.info(
                "instant %r predates the schema; using the bitemporal path",
                when,
            )

    if not isinstance(when, datetime):
        raise ValueError(
            "the bitemporal path needs an absolute instant, not the relative "
            f"interval {when!r}. Pass a timezone-aware datetime."
        )

    with db.transaction() as cur:
        cur.execute(
            """
            SELECT doc_id FROM corpus_members
            WHERE corpus_id = %s
              AND admitted_at <= %s
              AND (removed_at IS NULL OR removed_at > %s)
            """,
            (corpus_id, when, when),
        )
        return Membership(
            doc_ids=frozenset(r["doc_id"] for r in cur.fetchall()),
            source="bitemporal",
            as_of=when,
        )


def verify_integrity(corpus_id: str, when: datetime) -> IntegrityResult:
    """Cross-check the bitemporal record against MVCC history.

    A mismatch means ``corpus_members`` was modified outside the ledger's own
    write path. That is a detected tamper, not a rounding error, and it is
    reported rather than reconciled.
    """
    try:
        mvcc = membership_as_of(corpus_id, when, prefer_mvcc=True)
    except (db.TimeTravelBeyondRetention, db.TimeTravelBeforeSchema) as exc:
        return IntegrityResult(
            consistent=False,
            skipped_reason=str(exc),
        )

    if mvcc.source != "mvcc":
        return IntegrityResult(
            consistent=False,
            skipped_reason="MVCC path unavailable; check is inconclusive",
        )

    bitemporal = membership_as_of(corpus_id, when, prefer_mvcc=False)

    mvcc_only = mvcc.doc_ids - bitemporal.doc_ids
    bitemporal_only = bitemporal.doc_ids - mvcc.doc_ids

    if mvcc_only or bitemporal_only:
        log.error(
            "ledger integrity mismatch at %s: %d only in MVCC, %d only in columns",
            when,
            len(mvcc_only),
            len(bitemporal_only),
        )

    return IntegrityResult(
        consistent=not (mvcc_only or bitemporal_only),
        mvcc_only=mvcc_only,
        bitemporal_only=bitemporal_only,
    )


def record_answer_tx(
    cur,
    *,
    corpus_id: str,
    question: str,
    answer_text: str,
    retrieved: list[tuple[str, float]],
    model_version: str,
    asked_by: str | None = None,
) -> str:
    """Record an answer and what it was built from onto an existing cursor.

    Used directly by the agent loop so answer, attributions, and conversation
    turns commit in one transaction.
    """
    cur.execute(
        """
        INSERT INTO answers
            (corpus_id, question, answer_text, model_version, asked_by)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING answer_id
        """,
        (corpus_id, question, answer_text, model_version, asked_by),
    )
    answer_id = cur.fetchone()["answer_id"]

    for rank, (doc_id, similarity) in enumerate(retrieved, start=1):
        cur.execute(
            """
            INSERT INTO answer_attributions
                (answer_id, doc_id, rank, similarity)
            VALUES (%s, %s, %s, %s)
            """,
            (answer_id, doc_id, rank, similarity),
        )

    return str(answer_id)


def record_answer(
    *,
    corpus_id: str,
    question: str,
    answer_text: str,
    retrieved: list[tuple[str, float]],
    model_version: str,
    asked_by: str | None = None,
) -> str:
    """Record an answer and what it was built from, atomically.

    The answer row and its attribution rows commit together. That is the whole
    guarantee: an answer with no attributions is impossible, and attributions
    without an answer are impossible. Without it, "which documents did this use?"
    degrades from a fact to a reconstruction.
    """
    with db.transaction() as cur:
        return record_answer_tx(
            cur,
            corpus_id=corpus_id,
            question=question,
            answer_text=answer_text,
            retrieved=retrieved,
            model_version=model_version,
            asked_by=asked_by,
        )


def takedown_impact(doc_id: str) -> list[AffectedAnswer]:
    """Which past answers used this document?

    The question ORIGIN exists to answer, and the one that is unanswerable at
    essentially every organisation running retrieval today. It is a single
    indexed reverse lookup here only because the attribution was written
    atomically with the answer in the first place.
    """
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT a.answer_id, a.asked_at, a.asked_by, a.question, att.rank
            FROM answer_attributions att
            JOIN answers a ON a.answer_id = att.answer_id
            WHERE att.doc_id = %s
            ORDER BY a.asked_at DESC
            """,
            (doc_id,),
        )
        return [
            AffectedAnswer(
                answer_id=str(r["answer_id"]),
                asked_at=r["asked_at"],
                asked_by=r["asked_by"],
                question=r["question"],
                rank=r["rank"],
            )
            for r in cur.fetchall()
        ]


def record_takedown(
    *,
    doc_id: str,
    requested_by: str,
    reason: str,
) -> tuple[str, list[AffectedAnswer]]:
    """Remove a document from every corpus and account for its past use.

    Removal is a soft delete. Hard-deleting would destroy the record we exist to
    keep, and once GC ran, MVCC could not recover it either — so the one action
    that feels most like compliance would actually defeat it.

    The impact list is snapshotted onto the takedown row rather than recomputed
    on demand, because the answer to "what was affected" must not drift after the
    fact.
    """
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO takedowns (doc_id, requested_by, reason)
            VALUES (%s, %s, %s)
            RETURNING takedown_id
            """,
            (doc_id, requested_by, reason),
        )
        takedown_id = cur.fetchone()["takedown_id"]

        cur.execute(
            """
            SELECT a.answer_id, a.asked_at, a.asked_by, a.question, att.rank
            FROM answer_attributions att
            JOIN answers a ON a.answer_id = att.answer_id
            WHERE att.doc_id = %s
            ORDER BY a.asked_at DESC
            """,
            (doc_id,),
        )
        affected = [
            AffectedAnswer(
                answer_id=str(r["answer_id"]),
                asked_at=r["asked_at"],
                asked_by=r["asked_by"],
                question=r["question"],
                rank=r["rank"],
            )
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            UPDATE corpus_members
            SET removed_at = now(), removal_reason = 'takedown', removal_ref = %s
            WHERE doc_id = %s AND removed_at IS NULL
            """,
            (takedown_id, doc_id),
        )

        cur.execute(
            """
            UPDATE takedowns
            SET affected_answers = %s, affected_count = %s, resolved_at = now()
            WHERE takedown_id = %s
            """,
            (
                json.dumps(
                    [
                        {
                            "answer_id": a.answer_id,
                            "asked_at": a.asked_at.isoformat(),
                            "asked_by": a.asked_by,
                            "question": a.question,
                        }
                        for a in affected
                    ]
                ),
                len(affected),
                takedown_id,
            ),
        )

        return str(takedown_id), affected
