"""What ORIGIN knows about one admitted document.

This lived in ``datahub_emitter`` until the Lambda deployment made the coupling
expensive. ``DocumentFacts`` is a *ledger* concept — it mirrors a row of the
provenance record — and nothing about it is specific to any catalogue. Keeping
it here means the API can describe a document without importing ``acryl-datahub``
(34 MB before its transitive closure, against a 250 MB unzipped Lambda limit).

``datahub_emitter`` re-exports this name, so ``dhe.DocumentFacts`` keeps working
everywhere it is already used.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentFacts:
    """What the emitter needs about one document. Mirrors the ledger row."""

    doc_id: str
    source_system: str
    source_uri: str
    title: str | None
    license_raw: str | None
    license_class: str
    content_hash: str
    admitted_at: str
    admitted_txn: str | None
