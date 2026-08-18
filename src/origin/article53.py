"""Article 53(1)(d) training-content summary, generated from the ledger.

The AI Office published a mandatory template in July 2025 for the "sufficiently
detailed summary about the content used for training" that Article 53(1)(d)
requires of GPAI providers. This module emits that template's section structure,
populated from ORIGIN's ledger, at any instant the ledger can still reach.

Three properties are worth stating before the code, because they are why this is
defensible rather than decorative.

**A retrieval corpus is not training data.** Article 53 binds providers of
general-purpose AI models, and its subject is what a model was *trained* on.
ORIGIN's corpora are read at inference time. So the report says so, at the top,
every time it is generated. What is demonstrated here is that the ledger already
holds the fields the template asks for: the mechanism is substrate-neutral even
though the legal object is not.

**The unpopulated fields are the point.** A generator that emitted only the
sections it could fill would read as complete coverage of a template it covers
perhaps half of. ``CANNOT_POPULATE`` is therefore rendered *inside* the report
rather than omitted from it, and it is the section a supervisor should read
first.

**The instant is load-bearing.** The template asks a provider to describe the
corpus *as it stood* on a stated date. Every figure below is read at that
instant, and the report names which path answered -- storage history, which
application code cannot forge, or the bitemporal columns, which it maintains.
Those are different grades of evidence, and blurring them would defeat the
purpose of keeping the record at all.

NOT LEGAL ADVICE, and not a filing. Read the template directly before relying on
any of this. See ``docs/COMPLIANCE.md`` for the full mapping and, more usefully,
for its limits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import corpus, db

#: Section names follow the Commission template published in July 2025. They are
#: reproduced here as headings only; the template itself is the authority and
#: should be read directly rather than inferred from this rendering of it.
TEMPLATE_SECTIONS = (
    "1. General information",
    "2. List of data sources",
    "3. Relevant data processing aspects",
)

#: (template section, field, why this ledger is silent about it).
#:
#: This is the honest half of the report. Every entry is a field the template
#: asks for and ORIGIN cannot answer -- not a field ORIGIN answers partially.
#: Partial answers are marked in place, in the sections above.
CANNOT_POPULATE: tuple[tuple[str, str, str], ...] = (
    (
        "1. General information",
        "Model name, version, and identifiers",
        "ORIGIN records a corpus, not a model. Nothing here knows which model -- "
        "if any -- consumed these documents. That binding, ledger to deployed "
        "system, is the first thing a supervisor would ask for and it is outside "
        "this boundary.",
    ),
    (
        "1. General information",
        "Modalities, model size, and training compute",
        "No view of the model at all. The ledger is also text-document-only: no "
        "images, audio, video, or code.",
    ),
    (
        "2. List of data sources",
        "Data scraped or crawled from online sources",
        "Not implemented. Documents arrive through explicit ingest paths and "
        "ORIGIN never crawls, so it cannot report crawler identity, collection "
        "periods, or the domains visited.",
    ),
    (
        "2. List of data sources",
        "Volume of data in the template's units",
        "The ledger counts documents, not tokens or bytes of training text. A "
        "document count is not the figure the template asks for, and it is not "
        "offered as a substitute for it.",
    ),
    (
        "2. List of data sources",
        "User data and synthetic data",
        "No such category exists here. Every document arrives with a declared "
        "external source.",
    ),
    (
        "3. Relevant data processing aspects",
        "Rights reservations expressed at the point of access "
        "(robots.txt, TDM Reservation Protocol, ai.txt)",
        "Not implemented, and this is the most consequential gap in the report. "
        "ORIGIN reads the licence a source declares in metadata. A rightsholder "
        "who reserved TDM rights under DSM Article 4(3) in robots.txt and nowhere "
        "else is invisible to it.",
    ),
    (
        "3. Relevant data processing aspects",
        "Measures to detect and remove illegal content (CSAM, NCII)",
        "Not implemented. ORIGIN assesses rights, not content. The prohibition "
        "added by the Digital Omnibus and applying from 2 December 2026 is not "
        "addressed by anything in this system.",
    ),
    (
        "3. Relevant data processing aspects",
        "Lawfulness of access",
        "Not assessed. ORIGIN rules on what a source declares about reuse. It does "
        "not establish that the copy it read was lawfully accessible to begin with.",
    ),
    (
        "3. Relevant data processing aspects",
        "Contact point for rightsholders",
        "No intake channel exists. corpus.record_takedown handles a complaint "
        "once it has arrived by some other route, which is the second half of the "
        "obligation and not the first.",
    ),
)


@dataclass(frozen=True)
class SourceGroup:
    """One row of the template's data-source breakdown."""

    source_system: str
    document_count: int
    #: Normalised permitted-use class -> count. The derived value.
    license_classes: dict[str, int] = field(default_factory=dict)
    #: Verbatim licence string -> count. The value that was never rewritten, and
    #: therefore the one a rightsholder would recognise.
    raw_licenses: dict[str, int] = field(default_factory=dict)
    earliest_admission: datetime | None = None
    latest_admission: datetime | None = None


@dataclass(frozen=True)
class GateHistory:
    """What the copyright policy actually refused, and on what grounds.

    Recorded because the absence of a blocked build is not evidence of
    compliance: a corpus with no blocks either had no violations or was never
    gated, and only the gate history distinguishes those.
    """

    allowed: int = 0
    blocked: int = 0
    violations: int = 0
    #: Distinct clauses quoted at the point of refusal, most recent first.
    clauses: tuple[str, ...] = ()
    last_decision_at: datetime | None = None


@dataclass(frozen=True)
class Summary:
    corpus_name: str
    corpus_id: str
    declared_use: str
    #: The instant the corpus is described as at.
    as_of: datetime
    #: 'mvcc' | 'bitemporal' | 'current' -- which path produced membership.
    membership_source: str
    #: True when the document detail was read from the same snapshot as the
    #: membership. False means the rows are present-day and the report says so.
    detail_from_snapshot: bool
    document_count: int
    sources: tuple[SourceGroup, ...]
    gates: GateHistory
    takedown_count: int
    takedown_affected_answers: int
    generated_at: datetime


# --------------------------------------------------------------------------
# collection
# --------------------------------------------------------------------------
_DOC_COLUMNS = (
    "doc_id, source_system, source_uri, license_raw, license_class, admitted_at"
)


def _corpus_metadata(corpus_id: str) -> dict:
    with db.transaction() as cur:
        cur.execute(
            "SELECT corpus_id, name, declared_use FROM corpora WHERE corpus_id = %s",
            (corpus_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise LookupError(f"no corpus with id {corpus_id!r}")
    return dict(row)


def _group_documents(rows: list[dict]) -> tuple[SourceGroup, ...]:
    """Fold document rows into the template's per-source breakdown."""
    buckets: dict[str, dict] = {}
    for row in rows:
        system = row["source_system"] or "(unrecorded)"
        bucket = buckets.setdefault(
            system,
            {"count": 0, "classes": {}, "raw": {}, "earliest": None, "latest": None},
        )
        bucket["count"] += 1

        klass = row["license_class"] or "UNKNOWN"
        bucket["classes"][klass] = bucket["classes"].get(klass, 0) + 1

        raw = row["license_raw"] or "(none declared)"
        bucket["raw"][raw] = bucket["raw"].get(raw, 0) + 1

        admitted = row["admitted_at"]
        if admitted is not None:
            if bucket["earliest"] is None or admitted < bucket["earliest"]:
                bucket["earliest"] = admitted
            if bucket["latest"] is None or admitted > bucket["latest"]:
                bucket["latest"] = admitted

    return tuple(
        SourceGroup(
            source_system=system,
            document_count=b["count"],
            license_classes=dict(
                sorted(b["classes"].items(), key=lambda kv: (-kv[1], kv[0]))
            ),
            raw_licenses=dict(sorted(b["raw"].items(), key=lambda kv: (-kv[1], kv[0]))),
            earliest_admission=b["earliest"],
            latest_admission=b["latest"],
        )
        for system, b in sorted(buckets.items())
    )


def _fetch_documents(cur, doc_ids: frozenset[str]) -> list[dict]:
    if not doc_ids:
        return []
    cur.execute(
        f"SELECT {_DOC_COLUMNS} FROM documents WHERE doc_id = ANY(%s)",
        (list(doc_ids),),
    )
    return [dict(r) for r in cur.fetchall()]


def _iter_violations(raw) -> list[dict]:
    """``violations`` is JSONB and may arrive decoded or as text."""
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [v for v in raw if isinstance(v, dict)]


def _fetch_gates(cur, corpus_id: str, when: datetime) -> GateHistory:
    cur.execute(
        """
        SELECT decision, violation_count, violations, attempted_at
        FROM build_gates
        WHERE corpus_id = %s AND attempted_at <= %s
        ORDER BY attempted_at DESC
        """,
        (corpus_id, when),
    )
    rows = [dict(r) for r in cur.fetchall()]

    clauses: list[str] = []
    for row in rows:
        for violation in _iter_violations(row["violations"]):
            clause = violation.get("clause")
            if clause and clause not in clauses:
                clauses.append(clause)

    return GateHistory(
        allowed=sum(1 for r in rows if r["decision"] == "allowed"),
        blocked=sum(1 for r in rows if r["decision"] == "blocked"),
        violations=sum(r["violation_count"] or 0 for r in rows),
        clauses=tuple(clauses),
        last_decision_at=rows[0]["attempted_at"] if rows else None,
    )


def _fetch_takedowns(cur, corpus_id: str, when: datetime) -> tuple[int, int]:
    cur.execute(
        """
        SELECT t.affected_count
        FROM takedowns t
        JOIN corpus_members m
          ON m.doc_id = t.doc_id AND m.corpus_id = %s
        WHERE t.requested_at <= %s
        """,
        (corpus_id, when),
    )
    rows = cur.fetchall()
    return len(rows), sum((r["affected_count"] or 0) for r in rows)


def build_summary(corpus_id: str, when: datetime | str | None = None) -> Summary:
    """Assemble the summary for one corpus at one instant.

    ``when`` accepts an aware datetime, a negative interval such as ``'-2h'``, or
    ``None`` for the present. When storage history can reach the instant, the
    document detail is read from that same pinned snapshot so membership and
    detail cannot disagree. When it cannot, membership falls back to the
    bitemporal columns, the detail is read from the present, and
    ``detail_from_snapshot`` records that so the report can say so out loud.
    """
    meta = _corpus_metadata(corpus_id)
    generated_at = datetime.now(timezone.utc)

    if when is None:
        members = corpus.current_members(corpus_id)
        membership_source = "current"
        resolved = generated_at
        detail_from_snapshot = True
        with db.transaction() as cur:
            documents = _fetch_documents(cur, members)
            gates = _fetch_gates(cur, corpus_id, resolved)
            takedowns, affected = _fetch_takedowns(cur, corpus_id, resolved)
    else:
        membership = corpus.membership_as_of(corpus_id, when)
        members = membership.doc_ids
        membership_source = membership.source

        if membership_source == "mvcc":
            # One pinned transaction, so every figure describes a single instant
            # rather than several adjacent ones.
            detail_from_snapshot = True
            with db.read_as_of(when) as cur:
                cur.execute("SELECT now() AS resolved")
                resolved = cur.fetchone()["resolved"]
                documents = _fetch_documents(cur, members)
                gates = _fetch_gates(cur, corpus_id, resolved)
                takedowns, affected = _fetch_takedowns(cur, corpus_id, resolved)
        else:
            # membership_as_of already refused a relative interval on this path,
            # so `when` is an absolute instant by the time we reach here.
            detail_from_snapshot = False
            resolved = when if isinstance(when, datetime) else generated_at
            with db.transaction() as cur:
                documents = _fetch_documents(cur, members)
                gates = _fetch_gates(cur, corpus_id, resolved)
                takedowns, affected = _fetch_takedowns(cur, corpus_id, resolved)

    return Summary(
        corpus_name=meta["name"],
        corpus_id=str(meta["corpus_id"]),
        declared_use=meta["declared_use"],
        as_of=resolved,
        membership_source=membership_source,
        detail_from_snapshot=detail_from_snapshot,
        document_count=len(members),
        sources=_group_documents(documents),
        gates=gates,
        takedown_count=takedowns,
        takedown_affected_answers=affected,
        generated_at=generated_at,
    )


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------
#: How each membership path should be described to a reader who has to decide
#: how much weight to give the figures. The distinction is the whole point: one
#: of these is read from storage the application cannot rewrite, and the other
#: is the application's own bookkeeping.
_BASIS = {
    "mvcc": (
        "storage history (`AS OF SYSTEM TIME`)",
        "Read from the cluster's own MVCC record. Application code cannot write "
        "it, so this figure does not depend on trusting ORIGIN.",
    ),
    "bitemporal": (
        "application-maintained columns (`admitted_at` / `removed_at`)",
        "**Asserted, not verifiable.** Storage history could not reach this "
        "instant -- it predates the garbage-collection horizon -- so the answer "
        "is only as honest as this codebase. `origin verify` returns "
        "INCONCLUSIVE here, and inconclusive is not a pass.",
    ),
    "current": (
        "current membership (`removed_at IS NULL`)",
        "The present state of the ledger. No time travel was involved, so no "
        "independent corroboration is claimed.",
    ),
}


def _fmt_instant(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") if value else "--"


def render_markdown(summary: Summary) -> str:
    """The report itself.

    Markdown rather than a bespoke terminal format because this artifact's job
    is to be handed to someone -- pasted into a response to a request for
    information, or read by a reviewer who will not be running the CLI.
    """
    basis_label, basis_note = _BASIS[summary.membership_source]
    out: list[str] = []
    add = out.append

    add(f"# Training-content summary -- {summary.corpus_name}")
    add("")
    add(
        "Generated by ORIGIN from the provenance ledger. Section structure "
        "follows the\nAI Office template published in July 2025 for EU AI Act "
        "Article 53(1)(d)."
    )
    add("")
    add("> **Not legal advice, and not a filing.** Read the template directly.")
    add("")

    # --- scope -----------------------------------------------------------
    add("## Scope -- read this before the tables")
    add("")
    add(
        f"`{summary.corpus_name}` is a **retrieval corpus**: documents read at "
        "inference time.\nArticle 53(1)(d) binds providers of general-purpose AI "
        "models, and its subject is\nthe content a model was **trained** on. "
        "Those are different legal objects."
    )
    add("")
    add(
        "So this report is not an Article 53 disclosure. It demonstrates that the "
        "ledger\nholds the fields the template asks for, against the data ORIGIN "
        "could lawfully\nobtain. The mechanism is substrate-neutral; the "
        "obligation is not."
    )
    add("")

    # --- evidentiary basis ----------------------------------------------
    add("## Evidentiary basis")
    add("")
    add("| | |")
    add("|---|---|")
    add(f"| Corpus described as at | `{_fmt_instant(summary.as_of)}` |")
    add(f"| Declared use | `{summary.declared_use}` |")
    add(f"| Membership derived from | {basis_label} |")
    add(
        "| Document detail | "
        + (
            "same pinned snapshot"
            if summary.detail_from_snapshot
            else "**present-day rows** -- storage history could not reach the instant"
        )
        + " |"
    )
    add(f"| Report generated at | `{_fmt_instant(summary.generated_at)}` |")
    add(f"| Corpus id | `{summary.corpus_id}` |")
    add("")
    add(basis_note)
    add("")

    # --- 1 ---------------------------------------------------------------
    add(f"## {TEMPLATE_SECTIONS[0]}")
    add("")
    add(
        "The template's general-information fields are almost entirely about the "
        "model.\nORIGIN has no view of a model, so most of this section appears "
        "under\n[fields this ledger cannot populate](#fields-this-ledger-cannot-populate)."
    )
    add("")
    add(f"- **Corpus**: `{summary.corpus_name}`")
    add(f"- **Declared use**: `{summary.declared_use}` -- an *unverified input*.")
    add(f"- **Documents at this instant**: {summary.document_count}")
    add("")

    # --- 2 ---------------------------------------------------------------
    add(f"## {TEMPLATE_SECTIONS[1]}")
    add("")
    if not summary.sources:
        add("_No documents in the corpus at this instant._")
        add("")
    else:
        add("| Source | Documents | Permitted-use classes | First admitted | Last admitted |")
        add("|---|---:|---|---|---|")
        for group in summary.sources:
            classes = ", ".join(
                f"{name} ({count})" for name, count in group.license_classes.items()
            )
            add(
                f"| `{group.source_system}` | {group.document_count} | {classes} "
                f"| {_fmt_instant(group.earliest_admission)} "
                f"| {_fmt_instant(group.latest_admission)} |"
            )
        add("")
        add("### Verbatim licence strings")
        add("")
        add(
            "The template asks about licensing status. The classes above are "
            "ORIGIN's\n*derived* reading; these are the strings the sources "
            "actually declared, stored\nunmodified so a rightsholder can "
            "recognise their own terms."
        )
        add("")
        add("| Source | Declared licence | Documents |")
        add("|---|---|---:|")
        for group in summary.sources:
            for raw, count in group.raw_licenses.items():
                add(f"| `{group.source_system}` | {raw} | {count} |")
        add("")

    # --- 3 ---------------------------------------------------------------
    add(f"## {TEMPLATE_SECTIONS[2]}")
    add("")
    add("### Copyright policy and its enforcement point")
    add("")
    add(
        "The policy is the permitted-use matrix in "
        "`src/origin/licensing/policy.py`, and it\nis enforced at admission by "
        "`src/origin/gate.py`. An unrecognised licence **blocks**\nrather than "
        "passing with a warning, and genuinely arguable cases return `REVIEW`\n"
        "rather than a verdict."
    )
    add("")
    add("| | |")
    add("|---|---:|")
    add(f"| Build attempts allowed | {summary.gates.allowed} |")
    add(f"| Build attempts blocked | {summary.gates.blocked} |")
    add(f"| Violations recorded | {summary.gates.violations} |")
    add(f"| Most recent decision | `{_fmt_instant(summary.gates.last_decision_at)}` |")
    add("")
    if summary.gates.allowed == 0 and summary.gates.blocked == 0:
        add(
            "**No gate decisions are recorded for this corpus at this instant.** "
            "That is not\nevidence of compliance: a corpus with no blocks either "
            "had no violations or was\nnever gated, and only the gate history "
            "distinguishes those two."
        )
        add("")
    if summary.gates.clauses:
        add("### Grounds actually given for refusal")
        add("")
        add(
            "Quoted as recorded at the point of refusal, so the decision is "
            "explainable\nwithout re-running anything."
        )
        add("")
        for clause in summary.gates.clauses:
            add(f"- {clause}")
        add("")

    add("### Rights reservations and rightsholder complaints")
    add("")
    add(f"- Takedowns affecting this corpus: **{summary.takedown_count}**")
    add(
        f"- Past answers those takedowns reached: "
        f"**{summary.takedown_affected_answers}**"
    )
    add("")
    add(
        "Takedown is a *soft* delete. Hard-deleting would destroy the evidence "
        "the system\nexists to keep, and once garbage collection ran, MVCC could "
        "not recover it\neither -- the action that feels most like compliance "
        "would defeat it."
    )
    add("")
    add(
        "**Reservations expressed at the point of access are not covered.** See "
        "below."
    )
    add("")

    # --- the honest half -------------------------------------------------
    add("## Fields this ledger cannot populate")
    add("")
    add(
        "Listed rather than omitted, because a report showing only what it can "
        "fill reads\nas complete coverage of a template it covers roughly half "
        "of."
    )
    add("")
    for section in TEMPLATE_SECTIONS:
        entries = [e for e in CANNOT_POPULATE if e[0] == section]
        if not entries:
            continue
        add(f"### {section}")
        add("")
        for _, field_name, why in entries:
            add(f"- **{field_name}** -- {why}")
        add("")

    add("## What a supervisor would still have to request")
    add("")
    add(
        "Nothing in this report establishes that the corpus described is the "
        "corpus the\nsystem actually served from. That binding -- ledger to "
        "deployed index -- is outside\nORIGIN's boundary and would have to be "
        "evidenced separately. It is the first\nquestion worth asking of any "
        "provenance claim, including this one."
    )
    add("")

    return "\n".join(out)


def to_dict(summary: Summary) -> dict:
    """JSON-serialisable form, for a caller that wants the figures not the prose."""
    return {
        "corpus": {
            "name": summary.corpus_name,
            "corpus_id": summary.corpus_id,
            "declared_use": summary.declared_use,
            "declared_use_is_verified": False,
        },
        "as_of": summary.as_of.isoformat(),
        "generated_at": summary.generated_at.isoformat(),
        "evidentiary_basis": {
            "membership_source": summary.membership_source,
            "detail_from_same_snapshot": summary.detail_from_snapshot,
            "verifiable": summary.membership_source == "mvcc",
        },
        "scope": {
            "corpus_kind": "retrieval",
            "note": (
                "A retrieval corpus is not training data. Article 53(1)(d) binds "
                "GPAI providers in respect of training content."
            ),
        },
        "document_count": summary.document_count,
        "sources": [
            {
                "source_system": g.source_system,
                "document_count": g.document_count,
                "license_classes": g.license_classes,
                "raw_licenses": g.raw_licenses,
                "earliest_admission": _fmt_instant(g.earliest_admission),
                "latest_admission": _fmt_instant(g.latest_admission),
            }
            for g in summary.sources
        ],
        "gates": {
            "allowed": summary.gates.allowed,
            "blocked": summary.gates.blocked,
            "violations": summary.gates.violations,
            "clauses": list(summary.gates.clauses),
            "last_decision_at": _fmt_instant(summary.gates.last_decision_at),
        },
        "takedowns": {
            "count": summary.takedown_count,
            "affected_answers": summary.takedown_affected_answers,
        },
        "cannot_populate": [
            {"section": section, "field": name, "why": why}
            for section, name, why in CANNOT_POPULATE
        ],
    }
