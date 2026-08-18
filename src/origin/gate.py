"""The build gate: may this corpus be indexed as declared?

Every current member is ruled on against the corpus's declared use. If any
ruling blocks, the build is refused and the offending documents are recorded with
the clause that damned them — quoted, so the refusal is explainable without
re-running anything.

This is a **block, not a warning**. Warnings are not read, and a warning is
precisely how improperly licensed material reaches a shipped product. The gate's
value is that it is inconvenient.

Both verdicts are persisted to ``build_gates``. A blocked build is the most
valuable row in the database: it is the moment a rights reservation was actually
honoured, which is the evidence AI Act **Art 53(1)(c)** compliance ultimately
rests on. An unenforced policy leaves no trace distinguishable from no policy.

Concurrency matters here and is not decorative: two builds of the same corpus
running at once could each see a different member set and reach different
verdicts, and the losing verdict would still have built an index. The gate takes
a row lock on the corpus so builds of one corpus are strictly ordered, and relies
on SERIALIZABLE plus the retry logic in ``db.transaction`` for the rest.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from . import db
from .licensing import policy

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Violation:
    doc_id: str
    title: str | None
    license_raw: str | None
    license_class: str
    outcome: str
    #: Written for a human to read, because a human reads it — in the review
    #: queue and on screen in the demo.
    clause: str

    def as_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "license_raw": self.license_raw,
            "license_class": self.license_class,
            "outcome": self.outcome,
            "clause": self.clause,
        }


@dataclass(frozen=True)
class Obligation:
    doc_id: str
    license_class: str
    #: A duty that attaches but does not block — attribution, notice retention.
    #: Recorded so it can be discharged rather than forgotten.
    clause: str


@dataclass(frozen=True)
class Deferral:
    """A ruling where a human's catalogue entry overrode our classification."""

    doc_id: str
    our_class: str
    curated_licence: str
    curated_class: str
    #: True when deferring changed the outcome, which is the case worth showing:
    #: we would have blocked this document and a person's judgement unblocked it.
    changed_outcome: bool


@dataclass(frozen=True)
class GateDecision:
    gate_id: str
    corpus_name: str
    declared_use: str
    allowed: bool
    member_count: int
    violations: tuple[Violation, ...]
    obligations: tuple[Obligation, ...]
    deferrals: tuple[Deferral, ...] = ()

    @property
    def summary(self) -> str:
        if self.allowed:
            note = (
                f" ({len(self.obligations)} obligation(s) recorded)"
                if self.obligations
                else ""
            )
            return (
                f"ALLOWED — {self.member_count} documents cleared for "
                f"{self.declared_use} use{note}"
            )
        return (
            f"BLOCKED — {len(self.violations)} of {self.member_count} documents "
            f"are not permitted in a {self.declared_use} corpus"
        )


class CorpusNotFound(LookupError):
    pass


def evaluate_build(
    corpus_id: str,
    *,
    attempted_by: str = "cli",
    curated_licences: dict[str, str] | None = None,
) -> GateDecision:
    """Rule on whether ``corpus_id`` may be indexed, and record the attempt.

    Both outcomes are recorded. A blocked build is the most valuable row in the
    database — it is the moment a licence violation was prevented, and it is what
    an auditor asks to see.

    ``curated_licences`` maps ``doc_id`` to a licence string a human recorded in
    the catalogue (see ``datahub_context.curated_licences``). Where one exists it
    **overrides** our classification, because we are inferring from a metadata
    string and a data steward who typed it in was not. Every override is recorded
    as a ``Deferral`` so the decision remains explainable — silently substituting
    one licence for another would be worse than not deferring at all.
    """
    from .providers.local import classify_license_text

    overrides = curated_licences or {}

    # run_in_transaction, not the `transaction()` context manager, because this is
    # where contention actually happens: FOR UPDATE below serialises concurrent
    # builds of one corpus, so a serialization failure is expected under load and
    # must be retried rather than surfaced. The body is pure database work, so
    # replaying it is safe — a failed attempt rolls back entirely, including the
    # build_gates row.
    def _body(cur):
        # FOR UPDATE serialises builds of this corpus against each other. Without
        # it, concurrent builds could disagree about the member set and the loser
        # would still have produced an index.
        cur.execute(
            """
            SELECT corpus_id, name, declared_use
            FROM corpora WHERE corpus_id = %s
            FOR UPDATE
            """,
            (corpus_id,),
        )
        corpus = cur.fetchone()
        if corpus is None:
            raise CorpusNotFound(f"no corpus with id {corpus_id!r}")

        declared_use = corpus["declared_use"]

        cur.execute(
            """
            SELECT d.doc_id, d.title, d.license_raw, d.license_class
            FROM corpus_members m
            JOIN documents d ON d.doc_id = m.doc_id
            WHERE m.corpus_id = %s AND m.removed_at IS NULL
            ORDER BY d.doc_id
            """,
            (corpus_id,),
        )
        members = cur.fetchall()

        violations: list[Violation] = []
        obligations: list[Obligation] = []
        deferrals: list[Deferral] = []

        for member in members:
            license_class = member["license_class"] or "UNKNOWN"
            effective_raw = member["license_raw"]

            curated = overrides.get(member["doc_id"])
            if curated:
                curated_class, _ = classify_license_text(curated)
                our_ruling = policy.evaluate(license_class, declared_use)
                their_ruling = policy.evaluate(curated_class, declared_use)
                deferrals.append(
                    Deferral(
                        doc_id=member["doc_id"],
                        our_class=license_class,
                        curated_licence=curated,
                        curated_class=curated_class,
                        changed_outcome=(
                            our_ruling.blocks_build != their_ruling.blocks_build
                        ),
                    )
                )
                license_class = curated_class
                effective_raw = f"{curated} (curated in catalogue)"

            ruling = policy.evaluate(license_class, declared_use)

            if ruling.blocks_build:
                violations.append(
                    Violation(
                        doc_id=member["doc_id"],
                        title=member["title"],
                        license_raw=effective_raw,
                        license_class=license_class,
                        outcome=ruling.outcome.value,
                        clause=ruling.clause,
                    )
                )
            elif ruling.outcome is policy.Outcome.OBLIGATION:
                obligations.append(
                    Obligation(
                        doc_id=member["doc_id"],
                        license_class=license_class,
                        clause=ruling.clause,
                    )
                )

        allowed = not violations
        decision = "allowed" if allowed else "blocked"

        cur.execute(
            """
            INSERT INTO build_gates
                (corpus_id, attempted_by, decision, member_count,
                 violation_count, violations)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING gate_id
            """,
            (
                corpus_id,
                attempted_by,
                decision,
                len(members),
                len(violations),
                json.dumps([v.as_dict() for v in violations]),
            ),
        )
        gate_id = cur.fetchone()["gate_id"]

        if allowed:
            log.info(
                "build allowed for corpus %s (%d documents)",
                corpus["name"],
                len(members),
            )
        else:
            log.warning(
                "build BLOCKED for corpus %s: %d violation(s)",
                corpus["name"],
                len(violations),
            )

        return GateDecision(
            gate_id=str(gate_id),
            corpus_name=corpus["name"],
            declared_use=declared_use,
            allowed=allowed,
            member_count=len(members),
            violations=tuple(violations),
            obligations=tuple(obligations),
            deferrals=tuple(deferrals),
        )

    return db.run_in_transaction(_body)


def gate_history(corpus_id: str, limit: int = 20) -> list[dict]:
    """Recent build attempts for a corpus, newest first."""
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT gate_id, attempted_at, attempted_by, decision,
                   member_count, violation_count, violations
            FROM build_gates
            WHERE corpus_id = %s
            ORDER BY attempted_at DESC
            LIMIT %s
            """,
            (corpus_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]
