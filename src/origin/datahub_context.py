"""Read from DataHub, using the official Agent Context Kit.

ORIGIN's README claims DataHub tells us what exists and how it connects. Until
this module, only the write half of that was true — the catalogue was a sink we
pushed metadata into and never consulted. That was both a hole in the story and a
missed opportunity, because the catalogue frequently knows things our classifier
cannot.

Three things we ask the graph:

**Does the catalogue already know this dataset?** A human-curated licence or owner
in DataHub should outrank our automated classification. We are guessing from a
metadata string; a data steward who typed it in was not.

**Who depends on this corpus?** Downstream lineage turns "13 documents blocked"
into "13 blocked, and these consumers are affected". A blast radius with names in
it is the difference between a compliance report and something someone acts on.

**What did we conclude, in the catalogue's own words?** Audit findings are saved
back as a DataHub document, so the reasoning lives where the data lives rather
than only in our ledger.

Uses ``datahub-agent-context`` (the Agent Context Kit), which bundles the same
tool surface as the DataHub MCP server. Verified working against a **self-hosted
OSS quickstart**, not only DataHub Cloud — the documentation leans on Cloud
endpoints, so that was worth establishing.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from . import config

log = logging.getLogger(__name__)


class DataHubUnavailable(RuntimeError):
    """The catalogue could not be reached or answered.

    Raised rather than swallowed, but callers are expected to degrade: ORIGIN's
    ledger is the record of record, and a catalogue outage must not stop a
    document being admitted or a gate being enforced.
    """


@dataclass(frozen=True)
class CatalogFact:
    """What the catalogue already knows about a dataset."""

    urn: str
    name: str | None
    description: str | None
    #: Any licence value in the catalogue, including one ORIGIN itself wrote.
    #: Useful for display; NOT usable as evidence about ORIGIN.
    existing_licence: str | None
    #: A licence recorded under a NON-namespaced key, i.e. by something other
    #: than ORIGIN. This is the only value the gate may defer to — deferring to
    #: `origin.licence_raw` would mean deferring to ourselves and calling it
    #: human judgement.
    curated_licence: str | None
    tags: tuple[str, ...]
    owners: tuple[str, ...]
    #: True when this entity carries metadata that did NOT come from ORIGIN.
    #: That is the interesting case: someone else curated it, so their value
    #: should be preferred over our classifier's guess.
    externally_curated: bool


@dataclass(frozen=True)
class Consumer:
    urn: str
    name: str | None
    entity_type: str | None
    sub_type: str | None


@contextmanager
def client_context() -> Iterator[None]:
    """Register a DataHub client for the duration of the block.

    The Agent Context Kit resolves its client from a contextvar, so tools are
    called as plain functions once this is active. The token is reset on exit so
    nothing leaks between operations.
    """
    cfg = config.load()
    try:
        from datahub.sdk import DataHubClient
        from datahub_agent_context import reset_client, set_client
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise DataHubUnavailable(
            "datahub-agent-context is not installed; run "
            "pip install -e '.[dev]'"
        ) from exc

    try:
        client = DataHubClient(server=cfg.datahub_gms_url, token=cfg.datahub_token)
    except Exception as exc:
        raise DataHubUnavailable(
            f"could not build a DataHub client for {cfg.datahub_gms_url}: {exc}"
        ) from exc

    token = set_client(client)
    try:
        yield
    finally:
        reset_client(token)


def _first_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (list, tuple)):
        for item in value:
            found = _first_string(item)
            if found:
                return found
    return None


def _extract_custom_properties(properties: Any) -> dict[str, str]:
    """Normalise customProperties, which arrives as a list of key/value dicts."""
    if not isinstance(properties, dict):
        return {}
    raw = properties.get("customProperties")
    result: dict[str, str] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            result[str(key)] = str(value)
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, dict) and "key" in item:
                result[str(item["key"])] = str(item.get("value", ""))
    return result


def catalog_facts(urns: list[str]) -> dict[str, CatalogFact]:
    """What the catalogue already knows about these entities.

    Returns only entities that exist. A URN we have never emitted simply will not
    appear, which is not an error — it means the catalogue has nothing to add.
    """
    if not urns:
        return {}

    from datahub_agent_context.mcp_tools import get_entities

    try:
        records = get_entities(urns=urns)
    except Exception as exc:
        raise DataHubUnavailable(f"get_entities failed: {exc}") from exc

    facts: dict[str, CatalogFact] = {}
    for record in records or []:
        if not isinstance(record, dict):
            continue
        urn = record.get("urn")
        if not urn:
            continue

        properties = record.get("properties") or {}
        custom = _extract_custom_properties(properties)

        tag_urns: list[str] = []
        tags_field = record.get("tags")
        if isinstance(tags_field, dict):
            for association in tags_field.get("tags") or []:
                if isinstance(association, dict):
                    tag = association.get("tag")
                    if isinstance(tag, dict):
                        tag = tag.get("urn")
                    if isinstance(tag, str):
                        tag_urns.append(tag)

        owner_urns: list[str] = []
        ownership = record.get("ownership")
        if isinstance(ownership, dict):
            for owner in ownership.get("owners") or []:
                if isinstance(owner, dict):
                    who = owner.get("owner")
                    if isinstance(who, dict):
                        who = who.get("urn")
                    if isinstance(who, str):
                        owner_urns.append(who)

        # Anything not written by us. Our own keys are namespaced `origin.`, and
        # our tags with `origin-`, so anything else came from elsewhere.
        foreign_properties = [k for k in custom if not k.startswith("origin.")]
        foreign_tags = [t for t in tag_urns if "origin-" not in t]

        # Only un-namespaced keys can be somebody else's entry.
        curated = custom.get("licence") or custom.get("license")

        facts[urn] = CatalogFact(
            urn=urn,
            name=record.get("name"),
            description=_first_string(properties.get("description")),
            existing_licence=curated or custom.get("origin.licence_raw"),
            curated_licence=curated,
            tags=tuple(tag_urns),
            owners=tuple(owner_urns),
            externally_curated=bool(
                foreign_properties or foreign_tags or owner_urns
            ),
        )
    return facts


def curated_licences(
    members: list[Any],
) -> dict[str, str]:
    """Licences a human recorded in the catalogue, keyed by our ``doc_id``.

    Only entries that are **externally curated** count — metadata ORIGIN wrote is
    not evidence about ORIGIN. Our own keys are namespaced ``origin.`` and our
    tags ``origin-``, so an un-namespaced ``licence`` property alongside an owner
    or foreign tag is a person's entry.

    Returned so the gate can defer to it. Reporting curation without acting on it
    would be a claim we do not honour.
    """
    from . import datahub_emitter as dhe

    urn_to_doc = {dhe.document_urn(m): m.doc_id for m in members}
    if not urn_to_doc:
        return {}

    facts = catalog_facts(list(urn_to_doc))
    curated: dict[str, str] = {}
    for urn, fact in facts.items():
        if not fact.externally_curated:
            continue
        licence = fact.curated_licence
        if not licence:
            continue
        doc_id = urn_to_doc.get(urn)
        if doc_id:
            curated[doc_id] = licence
    return curated


def downstream_consumers(urn: str, *, max_hops: int = 2) -> list[Consumer]:
    """Who depends on this asset.

    Turns a violation count into a blast radius. `max_hops=2` by default because
    one hop finds the immediate reader and two finds the dashboard behind it,
    which is usually the thing a person actually notices.
    """
    from datahub_agent_context.mcp_tools import get_lineage

    try:
        result = get_lineage(
            urn=urn, upstream=False, max_hops=max_hops, max_results=50
        )
    except Exception as exc:
        raise DataHubUnavailable(f"get_lineage failed: {exc}") from exc

    consumers: list[Consumer] = []
    block = (result or {}).get("downstreams") or {}
    for entry in block.get("searchResults") or block.get("results") or []:
        entity = entry.get("entity") if isinstance(entry, dict) else None
        if not isinstance(entity, dict):
            continue
        sub_types = entity.get("subTypes") or {}
        type_names = (
            sub_types.get("typeNames") if isinstance(sub_types, dict) else None
        )
        consumers.append(
            Consumer(
                urn=entity.get("urn", ""),
                name=entity.get("name"),
                entity_type=entity.get("type"),
                sub_type=_first_string(type_names),
            )
        )
    return consumers


def upstream_count(urn: str) -> int:
    """How many upstreams the catalogue records for this asset.

    Used as an independent check on our own emit: if the ledger says a corpus has
    24 members and the graph reports a different number, one of them is wrong and
    it is worth knowing which.
    """
    from datahub_agent_context.mcp_tools import get_lineage

    try:
        result = get_lineage(urn=urn, upstream=True, max_hops=1, max_results=1)
    except Exception as exc:
        raise DataHubUnavailable(f"get_lineage failed: {exc}") from exc
    block = (result or {}).get("upstreams") or {}
    total = block.get("total")
    return int(total) if isinstance(total, int) else 0


def save_audit_document(
    *,
    corpus_urn: str,
    corpus_name: str,
    title: str,
    body: str,
) -> str | None:
    """Save the licence audit into DataHub as a Decision document.

    This is the strongest form of contribution back to the graph available to us:
    not a tag or a property, but the reasoning itself, attached to the asset and
    searchable by anyone who never heard of ORIGIN.

    Returns the document URN, or None if the instance does not support documents
    (the feature is newer than some deployments) — a missing document must not
    fail an audit.
    """
    from datahub_agent_context.mcp_tools import save_document

    try:
        result = save_document(
            document_type="Decision",
            title=title,
            content=body,
            related_assets=[corpus_urn],
            topics=["licensing", "ai-governance", "provenance"],
        )
    except Exception as exc:
        log.warning(
            "could not save the audit document to DataHub (%s); the ledger "
            "remains the record of record",
            exc,
        )
        return None

    if isinstance(result, dict):
        return result.get("urn") or result.get("documentUrn")
    return None


def tag_licence_classes(
    *, entity_urns_by_class: dict[str, list[str]]
) -> dict[str, int]:
    """Attach glossary terms for licence classes, alongside the existing tags.

    A licence class is a business concept, not a label, so a glossary term models
    it more honestly than a flat tag — and DataHub's own guidance treats the
    glossary as the place shared vocabulary belongs.

    Returns a count of entities updated per class. Failures are reported per
    class rather than aborting: a glossary that is missing one term should still
    gain the others.
    """
    from datahub_agent_context.mcp_tools import add_glossary_terms

    applied: dict[str, int] = {}
    for licence_class, urns in entity_urns_by_class.items():
        if not urns:
            continue
        term_urn = f"urn:li:glossaryTerm:origin.licence.{licence_class.lower()}"
        try:
            add_glossary_terms(term_urns=[term_urn], entity_urns=urns)
            applied[licence_class] = len(urns)
        except Exception as exc:
            log.warning(
                "could not attach glossary term %s to %d entity(ies): %s",
                term_urn,
                len(urns),
                exc,
            )
    return applied
