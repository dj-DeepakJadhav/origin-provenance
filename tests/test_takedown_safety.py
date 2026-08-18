"""A takedown must survive the next scheduled ingest.

The defect this pins: `ingest` re-admits anything still present at the source,
and `_ensure_membership` clears `removed_at` on conflict. Together they silently
resurrected a document that had been withdrawn after a rights complaint. A
nightly job would have undone every takedown, and nothing would have said so.
"""

from __future__ import annotations

import uuid

import pytest

from origin import corpus, db, ledger

pytestmark = pytest.mark.needs_cluster


@pytest.fixture
def scratch():
    name = f"td-{uuid.uuid4().hex[:12]}"
    corpus_id = corpus.create_corpus(name=name, declared_use="commercial")
    doc_id = f"test:td-{uuid.uuid4().hex[:8]}"
    yield corpus_id, doc_id

    with db.transaction() as cur:
        cur.execute("DELETE FROM answer_attributions WHERE doc_id = %s", (doc_id,))
        cur.execute("DELETE FROM takedowns WHERE doc_id = %s", (doc_id,))
        cur.execute("DELETE FROM corpus_members WHERE corpus_id = %s", (corpus_id,))
        cur.execute("DELETE FROM build_gates WHERE corpus_id = %s", (corpus_id,))
        cur.execute("DELETE FROM answers WHERE corpus_id = %s", (corpus_id,))
        cur.execute("DELETE FROM corpora WHERE corpus_id = %s", (corpus_id,))
        cur.execute("DELETE FROM documents WHERE doc_id = %s", (doc_id,))


def admit(corpus_id: str, doc_id: str, **overrides):
    payload = dict(
        corpus_id=corpus_id,
        doc_id=doc_id,
        source_uri="https://example.invalid/source",
        source_system="test",
        content=b"withdrawn content",
        title="withdrawn",
        license_raw="MIT",
        storage_key=f"test/{doc_id.replace(':', '_')}.txt",
    )
    payload.update(overrides)
    return ledger.admit_document(**payload)


class TestTakedownSurvivesReingest:
    def test_reingest_is_refused_after_a_takedown(self, scratch):
        corpus_id, doc_id = scratch
        admit(corpus_id, doc_id)
        corpus.record_takedown(
            doc_id=doc_id, requested_by="legal", reason="rights complaint"
        )
        assert doc_id not in corpus.current_members(corpus_id)

        result = admit(corpus_id, doc_id)

        assert result.refused_takedown is True
        assert result.newly_admitted is False
        assert result.determination.license_class == "WITHDRAWN"
        assert "rights complaint" in result.determination.rationale
        assert doc_id not in corpus.current_members(corpus_id), (
            "the document must still be out of the corpus after a re-ingest"
        )

    def test_refusal_names_who_took_it_down(self, scratch):
        corpus_id, doc_id = scratch
        admit(corpus_id, doc_id)
        corpus.record_takedown(
            doc_id=doc_id, requested_by="dpo@example.invalid", reason="GDPR erasure"
        )
        result = admit(corpus_id, doc_id)
        assert "dpo@example.invalid" in result.determination.rationale
        assert result.determination.decided_by == "policy:takedown"

    def test_explicit_readmission_is_allowed(self, scratch):
        """Reinstating a document must be possible, but deliberate."""
        corpus_id, doc_id = scratch
        admit(corpus_id, doc_id)
        corpus.record_takedown(
            doc_id=doc_id, requested_by="legal", reason="disputed"
        )

        result = admit(corpus_id, doc_id, allow_readmission=True)

        assert result.refused_takedown is False
        assert doc_id in corpus.current_members(corpus_id)

    def test_attribution_survives_the_whole_cycle(self, scratch):
        """Removal must never erase what the document was already used for."""
        corpus_id, doc_id = scratch
        admit(corpus_id, doc_id)
        corpus.record_answer(
            corpus_id=corpus_id,
            question="what is this?",
            answer_text="an answer",
            retrieved=[(doc_id, 0.8)],
            model_version="test",
            asked_by="pytest",
        )
        corpus.record_takedown(
            doc_id=doc_id, requested_by="legal", reason="complaint"
        )
        admit(corpus_id, doc_id)  # refused

        assert len(corpus.takedown_impact(doc_id)) == 1

    def test_a_clean_document_is_unaffected(self, scratch):
        """The guard must not block ordinary re-ingestion."""
        corpus_id, doc_id = scratch
        first = admit(corpus_id, doc_id)
        second = admit(corpus_id, doc_id)
        assert first.newly_admitted is True
        assert second.refused_takedown is False
        assert doc_id in corpus.current_members(corpus_id)
