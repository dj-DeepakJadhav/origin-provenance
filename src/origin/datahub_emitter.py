"""Write ORIGIN's findings back into the DataHub context graph.

This is the contribution half of the relationship. DataHub tells us what exists
and how it connects; ORIGIN tells DataHub something it could not know on its own:

  * **Lineage from corpus to source documents.** A corpus is a derived asset. Its
    upstreams are the exact documents that were members when it was built. That
    edge does not exist anywhere else — the Hub knows nothing about our corpus,
    and our ledger is invisible to the catalogue.
  * **Licence classification.** The raw string stays verbatim in
    ``customProperties``; the normalised permitted-use class becomes a tag, so it
    is filterable and searchable across the whole catalogue rather than trapped
    in our database.
  * **The build verdict.** Whether the corpus was allowed or refused, with the
    violation count, attached to the corpus entity.

Construction is separated from transmission on purpose: ``build_*`` functions are
pure and return proposals, ``emit`` sends them. That keeps the aspect and URN
logic unit-testable without a running GMS, which matters because a DataHub
instance is the slowest part of this stack to stand up.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from datahub.emitter.mce_builder import make_dataset_urn, make_tag_urn, make_term_urn
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    AuditStampClass,
    DatasetLineageTypeClass,
    DatasetPropertiesClass,
    GlobalTagsClass,
    GlossaryTermAssociationClass,
    GlossaryTermsClass,
    SubTypesClass,
    TagAssociationClass,
    UpstreamClass,
    UpstreamLineageClass,
)

from . import config, db
# Re-exported deliberately: `dhe.DocumentFacts` is used across the CLI, the demo
# seeder and the tests. It is defined in facts.py so the API can build one
# without importing acryl-datahub. See origin/facts.py.
from .facts import DocumentFacts
from .gate import GateDecision

__all__ = ["DocumentFacts"]

log = logging.getLogger(__name__)

#: Platform under which ORIGIN's own derived assets appear. Deliberately not a
#: real warehouse: a corpus is not a table, and pretending otherwise would put
#: misleading entities in someone's catalogue.
ORIGIN_PLATFORM = "origin"

ENV = "PROD"

#: Tag prefixes. Namespaced so it is obvious in the DataHub UI which tags were
#: written by this tool rather than by a human or another ingestion source.
LICENCE_TAG_PREFIX = "origin-licence"
BUILD_TAG_PREFIX = "origin-build"




def document_urn(facts: DocumentFacts) -> str:
    """Stable URN for a source document.

    Derived from the source system and the document's own identifier so that
    re-emitting updates the same entity instead of creating a second one.

    The ledger namespaces every ``doc_id`` with a short source tag — ``hf:`` for
    HuggingFace — and that is our bookkeeping, not part of the dataset's
    identity, so leaking it into the catalogue would make the entity name wrong.
    The tag is *not* derivable from the platform name ("hf" vs "huggingface"), so
    strip by the convention instead: a leading ``token:`` where the token
    contains no path separator.
    """
    name = facts.doc_id
    head, separator, tail = name.partition(":")
    if separator and tail and "/" not in head:
        name = tail
    return make_dataset_urn(platform=facts.source_system, name=name, env=ENV)


def corpus_urn(corpus_name: str) -> str:
    return make_dataset_urn(platform=ORIGIN_PLATFORM, name=corpus_name, env=ENV)


def build_document_proposals(
    facts: DocumentFacts,
) -> list[MetadataChangeProposalWrapper]:
    """Properties, licence tag and subtype for one document."""
    urn = document_urn(facts)

    # The raw licence string is preserved verbatim. A regulator asking "what did
    # the licence actually say?" wants the original bytes, not our tidy reading
    # of them - so the normalised class goes in a separate field.
    custom_properties = {
        "origin.licence_raw": facts.license_raw or "(none declared)",
        "origin.licence_class": facts.license_class,
        "origin.content_hash": facts.content_hash,
        "origin.admitted_at": facts.admitted_at,
        "origin.source_uri": facts.source_uri,
    }
    if facts.admitted_txn:
        # The cluster's own commit timestamp. This is the evidentiary anchor, and
        # putting it in the catalogue means the audit trail is discoverable by
        # someone who has never heard of ORIGIN.
        custom_properties["origin.admitted_txn"] = facts.admitted_txn

    return [
        MetadataChangeProposalWrapper(
            entityUrn=urn,
            aspect=DatasetPropertiesClass(
                name=facts.title or facts.doc_id,
                description=(
                    f"Licence as declared by the source: "
                    f"{facts.license_raw or '(none declared)'}. "
                    f"Classified by ORIGIN as {facts.license_class}."
                ),
                externalUrl=facts.source_uri,
                customProperties=custom_properties,
            ),
        ),
        MetadataChangeProposalWrapper(
            entityUrn=urn,
            aspect=GlobalTagsClass(
                tags=[
                    TagAssociationClass(
                        tag=make_tag_urn(
                            f"{LICENCE_TAG_PREFIX}-{facts.license_class.lower()}"
                        )
                    )
                ]
            ),
        ),
        MetadataChangeProposalWrapper(
            entityUrn=urn,
            aspect=GlossaryTermsClass(
                terms=[
                    GlossaryTermAssociationClass(
                        urn=make_term_urn(
                            f"LicenceClass.{facts.license_class.upper()}"
                        )
                    )
                ],
                auditStamp=AuditStampClass(
                    time=0,
                    actor="urn:li:corpuser:origin-agent",
                ),
            ),
        ),
        MetadataChangeProposalWrapper(
            entityUrn=urn,
            aspect=SubTypesClass(typeNames=["Corpus Document"]),
        ),
    ]


def build_corpus_proposals(
    *,
    corpus_name: str,
    declared_use: str,
    member_facts: Iterable[DocumentFacts],
    decision: GateDecision | None = None,
) -> list[MetadataChangeProposalWrapper]:
    """Properties, upstream lineage and build verdict for a corpus.

    The lineage is the valuable part: it records which documents the corpus was
    actually built from, which is knowledge that exists nowhere else.
    """
    urn = corpus_urn(corpus_name)
    members = list(member_facts)

    custom_properties = {
        "origin.declared_use": declared_use,
        "origin.member_count": str(len(members)),
    }

    description_parts = [
        f"AI document corpus declared for {declared_use} use.",
        f"{len(members)} member document(s).",
    ]

    if decision is not None:
        custom_properties["origin.build_decision"] = (
            "allowed" if decision.allowed else "blocked"
        )
        custom_properties["origin.violation_count"] = str(len(decision.violations))
        custom_properties["origin.obligation_count"] = str(
            len(decision.obligations)
        )
        custom_properties["origin.gate_id"] = decision.gate_id
        if decision.violations:
            # Enough to act on without opening ORIGIN, capped so the property
            # stays readable in the UI.
            custom_properties["origin.blocked_documents"] = ", ".join(
                v.doc_id for v in decision.violations[:10]
            )
        description_parts.append(decision.summary)

    proposals = [
        MetadataChangeProposalWrapper(
            entityUrn=urn,
            aspect=DatasetPropertiesClass(
                name=corpus_name,
                description=" ".join(description_parts),
                customProperties=custom_properties,
            ),
        ),
        MetadataChangeProposalWrapper(
            entityUrn=urn,
            aspect=SubTypesClass(typeNames=["AI Corpus"]),
        ),
    ]

    if members:
        proposals.append(
            MetadataChangeProposalWrapper(
                entityUrn=urn,
                aspect=UpstreamLineageClass(
                    upstreams=[
                        UpstreamClass(
                            dataset=document_urn(facts),
                            type=DatasetLineageTypeClass.TRANSFORMED,
                        )
                        for facts in members
                    ]
                ),
            )
        )

    if decision is not None:
        status = "allowed" if decision.allowed else "blocked"
        proposals.append(
            MetadataChangeProposalWrapper(
                entityUrn=urn,
                aspect=GlobalTagsClass(
                    tags=[
                        TagAssociationClass(
                            tag=make_tag_urn(f"{BUILD_TAG_PREFIX}-{status}")
                        )
                    ]
                ),
            )
        )

    return proposals


def load_member_facts(corpus_id: str) -> list[DocumentFacts]:
    """Read the current members of a corpus as emitter input."""
    with db.transaction() as cur:
        cur.execute(
            """
            SELECT d.doc_id, d.source_system, d.source_uri, d.title,
                   d.license_raw, d.license_class, d.content_hash,
                   d.admitted_at, d.admitted_txn
            FROM corpus_members m
            JOIN documents d ON d.doc_id = m.doc_id
            WHERE m.corpus_id = %s AND m.removed_at IS NULL
            ORDER BY d.doc_id
            """,
            (corpus_id,),
        )
        return [
            DocumentFacts(
                doc_id=row["doc_id"],
                source_system=row["source_system"],
                source_uri=row["source_uri"],
                title=row["title"],
                license_raw=row["license_raw"],
                license_class=row["license_class"] or "UNKNOWN",
                content_hash=row["content_hash"],
                admitted_at=row["admitted_at"].isoformat(),
                admitted_txn=row["admitted_txn"],
            )
            for row in cur.fetchall()
        ]


def _emitter():
    cfg = config.load()
    from datahub.emitter.rest_emitter import DatahubRestEmitter

    return DatahubRestEmitter(
        gms_server=cfg.datahub_gms_url, token=cfg.datahub_token
    )


def emit(proposals: list[MetadataChangeProposalWrapper]) -> int:
    """Send proposals to DataHub. Returns the number emitted.

    Emission is not wrapped in a transaction because DataHub has none. If it
    fails partway the catalogue is left partially updated, which is why the
    ledger — not the catalogue — remains the record of record. Re-running is
    safe: every URN is deterministic, so a second pass overwrites rather than
    duplicates.
    """
    emitter = _emitter()
    sent = 0
    try:
        for proposal in proposals:
            emitter.emit(proposal)
            sent += 1
    finally:
        # Report partial progress rather than losing it in the exception.
        if sent < len(proposals):
            log.warning(
                "emitted %d of %d proposals before stopping", sent, len(proposals)
            )
        emitter.flush()
    return sent


def record_urns(
    *, corpus_id: str, corpus_name: str, members: list[DocumentFacts]
) -> None:
    """Store the emitted URNs back in the ledger.

    Without this the two systems know about each other only by convention. With
    it, a ledger row can be resolved to its catalogue entity and vice versa,
    which is what makes the provenance chain navigable from either end.
    """
    with db.transaction() as cur:
        cur.execute(
            "UPDATE corpora SET datahub_urn = %s WHERE corpus_id = %s",
            (corpus_urn(corpus_name), corpus_id),
        )
        for facts in members:
            cur.execute(
                "UPDATE documents SET datahub_urn = %s WHERE doc_id = %s",
                (document_urn(facts), facts.doc_id),
            )


def sync_corpus(
    *,
    corpus_id: str,
    corpus_name: str,
    declared_use: str,
    decision: GateDecision | None = None,
) -> tuple[int, int]:
    """Emit a corpus and all its members. Returns (documents, proposals)."""
    members = load_member_facts(corpus_id)

    proposals: list[MetadataChangeProposalWrapper] = []
    for facts in members:
        proposals.extend(build_document_proposals(facts))
    proposals.extend(
        build_corpus_proposals(
            corpus_name=corpus_name,
            declared_use=declared_use,
            member_facts=members,
            decision=decision,
        )
    )

    sent = emit(proposals)
    record_urns(corpus_id=corpus_id, corpus_name=corpus_name, members=members)
    return len(members), sent
