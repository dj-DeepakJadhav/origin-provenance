"""Seed the two catalogue conditions the demo needs, and label them as seeded.

Two of ORIGIN's capabilities are built and tested but have nothing to act on in a
fresh DataHub instance, so they report zero and look broken:

  * **Blast radius.** `downstream_consumers` returns nothing because no asset
    consumes the corpus yet. Blocking a build therefore affects nobody, which
    undersells the whole point.
  * **Deference to curation.** `catalog_facts(...).externally_curated` is never
    true because ORIGIN wrote every scrap of metadata in the instance. The rule
    that a human steward outranks our classifier is real code that never fires.

This module creates a realistic downstream chain and one steward-curated
document so both paths exercise for real.

**Everything here is labelled as a demo fixture** — in the entity description, in
a `origin.demo_fixture` property, and with a `origin-demo-fixture` tag. Our own
demo rules say to label anything synthesised, and a seeded asset that looks
organic in a catalogue would be worse than not seeding at all: someone would
later find it and reasonably wonder what else was fabricated.

The *mechanism* being demonstrated is real. The data it chews on is planted, and
says so.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from datahub.emitter.mce_builder import (
    make_dashboard_urn,
    make_dataset_urn,
    make_tag_urn,
    make_user_urn,
)
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    AuditStampClass,
    ChangeAuditStampsClass,
    DashboardInfoClass,
    DatasetLineageTypeClass,
    DatasetPropertiesClass,
    GlobalTagsClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    SubTypesClass,
    TagAssociationClass,
    UpstreamClass,
    UpstreamLineageClass,
)

from . import config, datahub_emitter as dhe

log = logging.getLogger(__name__)

FIXTURE_TAG = "origin-demo-fixture"
FIXTURE_NOTE = (
    "DEMO FIXTURE created by `origin.cli demo seed`. Not a real asset. Exists so "
    "ORIGIN's blast-radius and steward-deference paths have something to act on."
)

#: The person who reads the downstream dashboard. A blast radius with a name in it
#: is the difference between a report and something someone acts on.
STEWARD_USER = "priya.raman"

RAG_INDEX_NAME = "support-assistant-index"
DASHBOARD_NAME = "weekly-drug-safety-review"


@dataclass(frozen=True)
class SeedResult:
    index_urn: str
    dashboard_urn: str
    curated_doc_urn: str | None
    proposals_emitted: int


def _now_stamp() -> AuditStampClass:
    # time.time() rather than a fixed value so re-seeding does not look stale.
    return AuditStampClass(
        time=int(time.time() * 1000), actor=make_user_urn(STEWARD_USER)
    )


def _fixture_tags(*extra: str) -> GlobalTagsClass:
    tags = [TagAssociationClass(tag=make_tag_urn(FIXTURE_TAG))]
    tags.extend(TagAssociationClass(tag=make_tag_urn(t)) for t in extra)
    return GlobalTagsClass(tags=tags)


def _ownership() -> OwnershipClass:
    return OwnershipClass(
        owners=[
            OwnerClass(
                owner=make_user_urn(STEWARD_USER),
                type=OwnershipTypeClass.TECHNICAL_OWNER,
            )
        ]
    )


def build_downstream_chain(corpus_name: str) -> list[MetadataChangeProposalWrapper]:
    """corpus -> RAG index -> dashboard, with a named owner on each.

    Two hops on purpose: one hop finds the index, which nobody looks at, and two
    finds the dashboard, which a person opens on a Monday morning. The second hop
    is what makes a violation feel consequential.
    """
    corpus_urn = dhe.corpus_urn(corpus_name)
    index_urn = make_dataset_urn(
        platform=dhe.ORIGIN_PLATFORM, name=RAG_INDEX_NAME, env=dhe.ENV
    )
    dashboard_urn = make_dashboard_urn(platform="superset", name=DASHBOARD_NAME)

    proposals: list[MetadataChangeProposalWrapper] = [
        # The retrieval index built from the corpus.
        MetadataChangeProposalWrapper(
            entityUrn=index_urn,
            aspect=DatasetPropertiesClass(
                name=RAG_INDEX_NAME,
                description=(
                    "Vector index served to the customer support assistant, built "
                    f"from the `{corpus_name}` corpus.\n\n{FIXTURE_NOTE}"
                ),
                customProperties={
                    "origin.demo_fixture": "true",
                    "origin.consumes_corpus": corpus_name,
                },
            ),
        ),
        MetadataChangeProposalWrapper(
            entityUrn=index_urn,
            aspect=UpstreamLineageClass(
                upstreams=[
                    UpstreamClass(
                        dataset=corpus_urn, type=DatasetLineageTypeClass.TRANSFORMED
                    )
                ]
            ),
        ),
        MetadataChangeProposalWrapper(
            entityUrn=index_urn, aspect=SubTypesClass(typeNames=["Vector Index"])
        ),
        MetadataChangeProposalWrapper(
            entityUrn=index_urn, aspect=_fixture_tags()
        ),
        MetadataChangeProposalWrapper(entityUrn=index_urn, aspect=_ownership()),
        # The thing a human actually opens.
        MetadataChangeProposalWrapper(
            entityUrn=dashboard_urn,
            aspect=DashboardInfoClass(
                title=DASHBOARD_NAME,
                description=(
                    "Adverse-event signal review, read every Monday by the drug "
                    f"safety team.\n\n{FIXTURE_NOTE}"
                ),
                lastModified=ChangeAuditStampsClass(created=_now_stamp()),
                datasets=[index_urn],
                customProperties={"origin.demo_fixture": "true"},
            ),
        ),
        MetadataChangeProposalWrapper(
            entityUrn=dashboard_urn, aspect=_fixture_tags()
        ),
        MetadataChangeProposalWrapper(entityUrn=dashboard_urn, aspect=_ownership()),
    ]
    return proposals


def build_steward_curation(
    doc_urn: str, *, curated_licence: str, existing_properties: dict[str, str]
) -> list[MetadataChangeProposalWrapper]:
    """Mark one document as human-curated, with a licence that is not ours.

    ``existing_properties`` must be the document's current customProperties.
    DatasetProperties is a whole-aspect replace, so emitting without merging would
    silently delete the provenance we already wrote — which would be a
    self-inflicted version of the exact bug this project exists to prevent.

    The curated licence key is deliberately un-namespaced (`licence`, not
    `origin.licence_raw`), because that is precisely how ORIGIN distinguishes
    metadata a person entered from metadata it generated.
    """
    merged = dict(existing_properties)
    merged["licence"] = curated_licence
    merged["curated_by"] = STEWARD_USER
    merged["origin.demo_fixture"] = "true"

    return [
        MetadataChangeProposalWrapper(
            entityUrn=doc_urn,
            aspect=DatasetPropertiesClass(
                name=existing_properties.get("origin.name") or None,
                description=(
                    f"Licence confirmed as `{curated_licence}` by {STEWARD_USER} "
                    "after reading the upstream repository, which the published "
                    f"metadata did not state.\n\n{FIXTURE_NOTE}"
                ),
                customProperties=merged,
            ),
        ),
        MetadataChangeProposalWrapper(
            entityUrn=doc_urn,
            # A tag outside our namespace: this is the signal that a human
            # touched the entity.
            aspect=_fixture_tags("reviewed-by-legal"),
        ),
        MetadataChangeProposalWrapper(entityUrn=doc_urn, aspect=_ownership()),
    ]


def _current_custom_properties(doc_urn: str) -> dict[str, str]:
    """Read a document's existing customProperties so we can merge, not clobber."""
    from datahub.ingestion.graph.client import DataHubGraph, DatahubClientConfig

    cfg = config.load()
    graph = DataHubGraph(DatahubClientConfig(server=cfg.datahub_gms_url))
    existing = graph.get_aspect(
        entity_urn=doc_urn, aspect_type=DatasetPropertiesClass
    )
    if existing is None or not existing.customProperties:
        return {}
    return dict(existing.customProperties)


def seed(
    *,
    corpus_name: str,
    curate_doc_id: str | None = None,
    curated_licence: str = "cc-by-4.0",
) -> SeedResult:
    """Create the downstream chain and, optionally, one curated document."""
    proposals = build_downstream_chain(corpus_name)

    curated_urn: str | None = None
    if curate_doc_id:
        facts = dhe.DocumentFacts(
            doc_id=curate_doc_id,
            source_system="huggingface",
            source_uri="",
            title=None,
            license_raw=None,
            license_class="UNKNOWN",
            content_hash="",
            admitted_at="",
            admitted_txn=None,
        )
        curated_urn = dhe.document_urn(facts)
        existing = _current_custom_properties(curated_urn)
        if not existing:
            log.warning(
                "%s is not in the catalogue yet — run `datahub sync` first, or "
                "the curation will create a bare entity with no provenance",
                curate_doc_id,
            )
        proposals.extend(
            build_steward_curation(
                curated_urn,
                curated_licence=curated_licence,
                existing_properties=existing,
            )
        )

    sent = dhe.emit(proposals)

    return SeedResult(
        index_urn=make_dataset_urn(
            platform=dhe.ORIGIN_PLATFORM, name=RAG_INDEX_NAME, env=dhe.ENV
        ),
        dashboard_urn=make_dashboard_urn(platform="superset", name=DASHBOARD_NAME),
        curated_doc_urn=curated_urn,
        proposals_emitted=sent,
    )
