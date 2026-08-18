"""DataHub aspect and URN construction — no GMS required.

The builders are pure so this is testable without standing up DataHub, which is
the slowest component in the stack. What matters here:

  * URNs must be **deterministic**, or re-emitting duplicates entities instead
    of updating them.
  * The raw licence string must survive verbatim into customProperties. The
    normalised class is our reading; the raw string is the evidence.
  * Corpus lineage must name exactly the current members, because that edge is
    the knowledge DataHub cannot obtain any other way.
"""

from __future__ import annotations

import pytest

from origin import datahub_emitter as dhe
from origin.gate import GateDecision, Obligation, Violation


def facts(
    doc_id="hf:squad",
    source_system="huggingface",
    license_raw="cc-by-sa-4.0",
    license_class="COPYLEFT",
    admitted_txn="1785963280.870692132",
):
    return dhe.DocumentFacts(
        doc_id=doc_id,
        source_system=source_system,
        source_uri=f"https://huggingface.co/datasets/{doc_id[3:]}",
        title=doc_id[3:],
        license_raw=license_raw,
        license_class=license_class,
        content_hash="a" * 64,
        admitted_at="2026-08-05T20:55:52.267838+00:00",
        admitted_txn=admitted_txn,
    )


def aspect_of(proposals, cls):
    """The single proposal carrying an aspect of the given class."""
    matches = [p for p in proposals if isinstance(p.aspect, cls)]
    assert len(matches) == 1, f"expected one {cls.__name__}, got {len(matches)}"
    return matches[0].aspect


class TestUrns:
    def test_document_urn_is_deterministic(self):
        assert dhe.document_urn(facts()) == dhe.document_urn(facts())

    def test_document_urn_strips_our_internal_prefix(self):
        """`hf:` is ORIGIN's bookkeeping; leaking it makes the entity name wrong."""
        urn = dhe.document_urn(facts(doc_id="hf:squad"))
        assert "squad" in urn
        assert "hf:squad" not in urn

    def test_document_urn_includes_the_source_platform(self):
        assert "huggingface" in dhe.document_urn(facts())

    def test_document_urn_survives_an_id_without_the_prefix(self):
        urn = dhe.document_urn(facts(doc_id="squad"))
        assert "squad" in urn

    def test_owner_slash_name_ids_are_preserved(self):
        """The common HuggingFace shape: hf:owner/name -> owner/name."""
        urn = dhe.document_urn(facts(doc_id="hf:openai/gsm8k"))
        assert "openai/gsm8k" in urn
        assert "hf:" not in urn

    def test_a_colon_after_a_path_separator_is_not_stripped(self):
        """Only a leading source tag is bookkeeping; a colon inside the id is
        part of the identifier and must survive."""
        urn = dhe.document_urn(facts(doc_id="owner/name:v2"))
        assert "owner/name:v2" in urn

    def test_corpus_urn_uses_the_origin_platform(self):
        urn = dhe.corpus_urn("hub-commercial")
        assert dhe.ORIGIN_PLATFORM in urn
        assert "hub-commercial" in urn

    def test_different_documents_get_different_urns(self):
        assert dhe.document_urn(facts(doc_id="hf:a")) != dhe.document_urn(
            facts(doc_id="hf:b")
        )


class TestDocumentProposals:
    def test_raw_licence_is_preserved_verbatim(self):
        """Our classification is an opinion; the raw string is the evidence."""
        from datahub.metadata.schema_classes import DatasetPropertiesClass

        raw = "Creative Commons Attribution-ShareAlike 4.0 (see LICENSE)"
        props = aspect_of(
            dhe.build_document_proposals(facts(license_raw=raw)),
            DatasetPropertiesClass,
        )
        assert props.customProperties["origin.licence_raw"] == raw

    def test_missing_licence_is_recorded_explicitly(self):
        from datahub.metadata.schema_classes import DatasetPropertiesClass

        props = aspect_of(
            dhe.build_document_proposals(
                facts(license_raw=None, license_class="UNKNOWN")
            ),
            DatasetPropertiesClass,
        )
        assert props.customProperties["origin.licence_raw"] == "(none declared)"
        assert props.customProperties["origin.licence_class"] == "UNKNOWN"

    def test_commit_timestamp_reaches_the_catalogue(self):
        """The evidentiary anchor should be discoverable without ORIGIN."""
        from datahub.metadata.schema_classes import DatasetPropertiesClass

        props = aspect_of(
            dhe.build_document_proposals(facts()), DatasetPropertiesClass
        )
        assert props.customProperties["origin.admitted_txn"]

    def test_absent_commit_timestamp_is_omitted_not_blank(self):
        from datahub.metadata.schema_classes import DatasetPropertiesClass

        props = aspect_of(
            dhe.build_document_proposals(facts(admitted_txn=None)),
            DatasetPropertiesClass,
        )
        assert "origin.admitted_txn" not in props.customProperties

    def test_licence_class_becomes_a_namespaced_tag(self):
        from datahub.metadata.schema_classes import GlobalTagsClass

        tags = aspect_of(
            dhe.build_document_proposals(facts(license_class="NONCOMMERCIAL")),
            GlobalTagsClass,
        )
        assert len(tags.tags) == 1
        tag = tags.tags[0].tag
        assert "origin-licence-noncommercial" in tag

    def test_licence_class_becomes_a_glossary_term(self):
        from datahub.metadata.schema_classes import GlossaryTermsClass

        terms_aspect = aspect_of(
            dhe.build_document_proposals(facts(license_class="NONCOMMERCIAL")),
            GlossaryTermsClass,
        )
        assert len(terms_aspect.terms) == 1
        term_urn = terms_aspect.terms[0].urn
        assert "LicenceClass.NONCOMMERCIAL" in term_urn

    def test_every_proposal_targets_the_same_urn(self):
        proposals = dhe.build_document_proposals(facts())
        urns = {p.entityUrn for p in proposals}
        assert len(urns) == 1


class TestCorpusProposals:
    def test_lineage_names_every_member(self):
        from datahub.metadata.schema_classes import UpstreamLineageClass

        members = [facts(doc_id=f"hf:ds-{i}") for i in range(4)]
        lineage = aspect_of(
            dhe.build_corpus_proposals(
                corpus_name="c", declared_use="commercial", member_facts=members
            ),
            UpstreamLineageClass,
        )
        assert len(lineage.upstreams) == 4
        expected = {dhe.document_urn(m) for m in members}
        assert {u.dataset for u in lineage.upstreams} == expected

    def test_no_lineage_aspect_for_an_empty_corpus(self):
        """Emitting empty lineage would assert the corpus has no sources, which
        is a different claim from having no members yet."""
        from datahub.metadata.schema_classes import UpstreamLineageClass

        proposals = dhe.build_corpus_proposals(
            corpus_name="c", declared_use="commercial", member_facts=[]
        )
        assert not [
            p for p in proposals if isinstance(p.aspect, UpstreamLineageClass)
        ]

    def test_declared_use_and_member_count_are_recorded(self):
        from datahub.metadata.schema_classes import DatasetPropertiesClass

        props = aspect_of(
            dhe.build_corpus_proposals(
                corpus_name="c",
                declared_use="research",
                member_facts=[facts(), facts(doc_id="hf:other")],
            ),
            DatasetPropertiesClass,
        )
        assert props.customProperties["origin.declared_use"] == "research"
        assert props.customProperties["origin.member_count"] == "2"

    def test_no_build_tag_without_a_decision(self):
        from datahub.metadata.schema_classes import GlobalTagsClass

        proposals = dhe.build_corpus_proposals(
            corpus_name="c", declared_use="commercial", member_facts=[facts()]
        )
        assert not [p for p in proposals if isinstance(p.aspect, GlobalTagsClass)]


class TestGateVerdictInTheGraph:
    def _blocked(self):
        return GateDecision(
            gate_id="11111111-2222-3333-4444-555555555555",
            corpus_name="hub-commercial",
            declared_use="commercial",
            allowed=False,
            member_count=25,
            violations=(
                Violation(
                    doc_id="hf:huggingface/documentation-images",
                    title="documentation-images",
                    license_raw="cc-by-nc-4.0",
                    license_class="NONCOMMERCIAL",
                    outcome="block",
                    clause="Licence states non-commercial use only.",
                ),
            ),
            obligations=(
                Obligation(
                    doc_id="hf:openai/gsm8k",
                    license_class="PERMISSIVE",
                    clause="Licence notice must be retained.",
                ),
            ),
        )

    def test_blocked_build_is_tagged_and_counted(self):
        from datahub.metadata.schema_classes import (
            DatasetPropertiesClass,
            GlobalTagsClass,
        )

        proposals = dhe.build_corpus_proposals(
            corpus_name="hub-commercial",
            declared_use="commercial",
            member_facts=[facts()],
            decision=self._blocked(),
        )
        props = aspect_of(proposals, DatasetPropertiesClass)
        assert props.customProperties["origin.build_decision"] == "blocked"
        assert props.customProperties["origin.violation_count"] == "1"
        assert props.customProperties["origin.obligation_count"] == "1"
        assert props.customProperties["origin.gate_id"]

        tags = aspect_of(proposals, GlobalTagsClass)
        assert "origin-build-blocked" in tags.tags[0].tag

    def test_blocked_documents_are_named_in_the_catalogue(self):
        from datahub.metadata.schema_classes import DatasetPropertiesClass

        props = aspect_of(
            dhe.build_corpus_proposals(
                corpus_name="c",
                declared_use="commercial",
                member_facts=[facts()],
                decision=self._blocked(),
            ),
            DatasetPropertiesClass,
        )
        assert "documentation-images" in props.customProperties[
            "origin.blocked_documents"
        ]

    def test_allowed_build_is_tagged_allowed(self):
        from datahub.metadata.schema_classes import GlobalTagsClass

        allowed = GateDecision(
            gate_id="abc",
            corpus_name="c",
            declared_use="commercial",
            allowed=True,
            member_count=2,
            violations=(),
            obligations=(),
        )
        tags = aspect_of(
            dhe.build_corpus_proposals(
                corpus_name="c",
                declared_use="commercial",
                member_facts=[facts()],
                decision=allowed,
            ),
            GlobalTagsClass,
        )
        assert "origin-build-allowed" in tags.tags[0].tag

    def test_blocked_document_list_is_capped(self):
        """A property with 500 ids is unreadable in the UI."""
        from datahub.metadata.schema_classes import DatasetPropertiesClass

        many = tuple(
            Violation(
                doc_id=f"hf:doc-{i}",
                title=None,
                license_raw=None,
                license_class="UNKNOWN",
                outcome="block",
                clause="unknown",
            )
            for i in range(50)
        )
        decision = GateDecision(
            gate_id="g",
            corpus_name="c",
            declared_use="commercial",
            allowed=False,
            member_count=50,
            violations=many,
            obligations=(),
        )
        props = aspect_of(
            dhe.build_corpus_proposals(
                corpus_name="c",
                declared_use="commercial",
                member_facts=[facts()],
                decision=decision,
            ),
            DatasetPropertiesClass,
        )
        listed = props.customProperties["origin.blocked_documents"].split(", ")
        assert len(listed) == 10
        assert props.customProperties["origin.violation_count"] == "50"
