"""Retrieval and answering, with attribution written atomically.

This is the part that makes the rest matter. Without an answer there is nothing
to attribute, and "which past answers used this document?" has no subject.

Two properties are deliberate:

**Only current members are retrievable.** The query joins ``corpus_members`` and
filters ``removed_at IS NULL``, so a document removed by a takedown stops
influencing answers immediately. Filtering after retrieval would be a bug you
could not see: the answer would still be shaped by material that was supposed to
be gone.

**The answer and its attributions commit together.** ``corpus.record_answer``
writes both in one transaction. An answer whose sources are unknown is exactly
the thing ORIGIN exists to prevent, so it must be impossible to produce one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from . import config, corpus, db
from .providers import Provider, get_provider

log = logging.getLogger(__name__)

DEFAULT_TOP_K = 4

#: Characters of each retrieved document shown in an extractive answer.
SNIPPET_CHARS = 320


@dataclass(frozen=True)
class Hit:
    doc_id: str
    title: str | None
    source_uri: str
    license_class: str
    license_raw: str | None
    similarity: float
    snippet: str


@dataclass(frozen=True)
class Answer:
    answer_id: str
    question: str
    text: str
    hits: tuple[Hit, ...]
    model_version: str
    #: True when no model was available and the answer was assembled from the
    #: retrieved text. Surfaced to the caller and printed in the CLI, because an
    #: extractive answer presented as a generated one is a lie about provenance.
    extractive: bool
    #: Members with no embedding, and therefore unreachable by this query.
    #: Reported rather than ignored: a silently short candidate set looks like a
    #: correct answer over the whole corpus.
    unembedded_members: int


def _unembedded_count(cur, corpus_id: str) -> int:
    cur.execute(
        """
        SELECT count(*) AS n
        FROM corpus_members m
        JOIN documents d ON d.doc_id = m.doc_id
        WHERE m.corpus_id = %s AND m.removed_at IS NULL AND d.embedding IS NULL
        """,
        (corpus_id,),
    )
    return int(cur.fetchone()["n"])


def search(
    corpus_id: str,
    question: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    provider: Provider | None = None,
) -> tuple[list[Hit], int]:
    """Nearest current members of the corpus. Returns (hits, unembedded_count)."""
    active = provider or get_provider()
    vector = db.vector_literal(active.embed(question))

    with db.transaction() as cur:
        unembedded = _unembedded_count(cur, corpus_id)

        cur.execute(
            """
            SELECT d.doc_id, d.title, d.source_uri, d.license_class,
                   d.license_raw,
                   d.embedding <=> %s::VECTOR AS distance
            FROM corpus_members m
            JOIN documents d ON d.doc_id = m.doc_id
            WHERE m.corpus_id = %s
              AND m.removed_at IS NULL
              AND d.embedding IS NOT NULL
            ORDER BY distance ASC
            LIMIT %s
            """,
            (vector, corpus_id, top_k),
        )
        rows = cur.fetchall()

    hits: list[Hit] = []
    from .storage import get_store

    store = get_store()
    for row in rows:
        snippet = ""
        # The blob may be absent if storage was cleared independently of the
        # ledger. That is a degraded answer, not a failed one.
        try:
            key = _storage_key_for(row["doc_id"])
            snippet = store.get(key).decode("utf-8", errors="replace")[
                :SNIPPET_CHARS
            ]
        except (KeyError, ValueError, OSError):
            log.debug("no stored body for %s", row["doc_id"])

        hits.append(
            Hit(
                doc_id=row["doc_id"],
                title=row["title"],
                source_uri=row["source_uri"],
                license_class=row["license_class"] or "UNKNOWN",
                license_raw=row["license_raw"],
                similarity=1.0 - float(row["distance"]),
                snippet=snippet,
            )
        )
    return hits, unembedded


def _storage_key_for(doc_id: str) -> str:
    """Reconstruct the storage key the ingester used.

    Mirrors ``cli.cmd_ingest``. Duplicated deliberately rather than stored: the
    key is derivable, and a stored key is one more thing that can disagree with
    reality.
    """
    head, separator, tail = doc_id.partition(":")
    if separator and tail and "/" not in head:
        return f"huggingface/{tail.replace('/', '__')}.md"
    return f"huggingface/{doc_id.replace('/', '__')}.md"


def _extractive_answer(question: str, hits: list[Hit]) -> str:
    """Assemble an answer from retrieved text, with no model involved."""
    if not hits:
        return (
            "No documents in this corpus matched the question. Nothing was "
            "retrieved, so there is nothing to attribute."
        )

    lines = [
        f"Extractive answer to: {question}",
        "",
        "Assembled from the retrieved documents below. No language model was "
        "used — this deployment is running the offline provider.",
        "",
    ]
    for index, hit in enumerate(hits, start=1):
        lines.append(f"[{index}] {hit.title or hit.doc_id}  ({hit.license_class})")
        if hit.snippet:
            collapsed = " ".join(hit.snippet.split())
            lines.append(f"    {collapsed}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _generated_answer(
    question: str, hits: list[Hit], provider: Provider
) -> tuple[str, str]:
    """Ask the model, grounded in the retrieved documents."""
    context = "\n\n".join(
        f"[{i}] {h.title or h.doc_id}\n{' '.join(h.snippet.split())}"
        for i, h in enumerate(hits, start=1)
    )
    prompt = (
        "Answer the question using only the numbered sources below. Cite the "
        "sources you use as [1], [2] and so on. If the sources do not contain "
        "the answer, say so plainly rather than guessing.\n\n"
        f"Question: {question}\n\nSources:\n{context}"
    )
    completion = provider.complete(prompt, max_tokens=700)
    return completion.text, completion.model_version


def prepare_answer(
    corpus_id: str,
    question: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    provider: Provider | None = None,
) -> tuple[str, list[Hit], str, bool, int]:
    """Retrieve documents and synthesize an answer without writing to the ledger."""
    active = provider or get_provider()
    hits, unembedded = search(corpus_id, question, top_k=top_k, provider=active)

    if active.supports_generation and hits:
        text, model_version = _generated_answer(question, hits, active)
        extractive = False
    else:
        text = _extractive_answer(question, hits)
        model_version = f"{active.name} (extractive)"
        extractive = True

    return text, hits, model_version, extractive, unembedded


def ask(
    corpus_id: str,
    question: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    asked_by: str | None = None,
    provider: Provider | None = None,
) -> Answer:
    """Retrieve, answer, and record the attribution — atomically.

    The attribution write is not optional and not deferred. If it fails, the
    answer is not recorded either, because an unattributable answer is precisely
    the artefact this project exists to make impossible.
    """
    text, hits, model_version, extractive, unembedded = prepare_answer(
        corpus_id=corpus_id,
        question=question,
        top_k=top_k,
        provider=provider,
    )

    answer_id = corpus.record_answer(
        corpus_id=corpus_id,
        question=question,
        answer_text=text,
        retrieved=[(h.doc_id, h.similarity) for h in hits],
        model_version=model_version,
        asked_by=asked_by,
    )

    if unembedded:
        log.warning(
            "%d current member(s) have no embedding and could not be retrieved; "
            "re-run ingest to backfill",
            unembedded,
        )

    return Answer(
        answer_id=answer_id,
        question=question,
        text=text,
        hits=tuple(hits),
        model_version=model_version,
        extractive=extractive,
        unembedded_members=unembedded,
    )


def provenance(answer_id: str) -> list[dict]:
    """The recorded sources of one answer, in retrieval order.

    This is the click-through in the demo: an answer resolves to exact documents,
    each with the licence it was admitted under.
    """
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT att.rank, att.similarity, d.doc_id, d.title, d.source_uri,
                   d.license_raw, d.license_class, d.datahub_urn, d.content_hash
            FROM answer_attributions att
            JOIN documents d ON d.doc_id = att.doc_id
            WHERE att.answer_id = %s
            ORDER BY att.rank
            """,
            (answer_id,),
        )
        return [dict(row) for row in cur.fetchall()]
