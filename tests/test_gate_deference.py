"""The gate deferring to a human's catalogue entry.

The behaviour: where a data steward recorded a licence in DataHub, that overrides
ORIGIN's classification — because we infer from a metadata string and a person who
read the upstream repository did not.

Two properties are load-bearing:

  **Every override is recorded** as a ``Deferral``. Silently substituting one
  licence for another would be worse than not deferring at all: the gate's value
  is that its decisions are explainable.

  **Deference can only make the outcome *more* permissive by way of a human**, not
  by way of our own metadata. The circularity guard lives in
  ``datahub_context.curated_licences``, which reads only un-namespaced keys; this
  file covers the gate's half.
"""

from __future__ import annotations

import uuid

import pytest

from origin import corpus, db, gate

pytestmark = pytest.mark.needs_cluster


@pytest.fixture
def scratch():
    name = f"def-{uuid.uuid4().hex[:12]}"
    corpus_id = corpus.create_corpus(name=name, declared_use="commercial")
    created: list[str] = []
    yield corpus_id, created

    with db.transaction() as cur:
        for doc_id in created:
            cur.execute("DELETE FROM takedowns WHERE doc_id = %s", (doc_id,))
        cur.execute("DELETE FROM corpus_members WHERE corpus_id = %s", (corpus_id,))
        cur.execute("DELETE FROM build_gates WHERE corpus_id = %s", (corpus_id,))
        cur.execute("DELETE FROM corpora WHERE corpus_id = %s", (corpus_id,))
        for doc_id in created:
            cur.execute("DELETE FROM documents WHERE doc_id = %s", (doc_id,))


def admit(corpus_id: str, created: list[str], licence: str | None) -> str:
    from origin import ledger

    doc_id = f"test:def-{uuid.uuid4().hex[:8]}"
    created.append(doc_id)
    ledger.admit_document(
        corpus_id=corpus_id,
        doc_id=doc_id,
        source_uri="https://example.invalid/x",
        source_system="test",
        content=b"body",
        title="doc",
        license_raw=licence,
        storage_key=f"test/{doc_id.replace(':', '_')}.txt",
    )
    return doc_id


class TestDeference:
    def test_curated_licence_unblocks_an_unknown_document(self, scratch):
        """The headline case: we would refuse, a steward's entry permits."""
        corpus_id, created = scratch
        doc_id = admit(corpus_id, created, None)  # -> UNKNOWN -> BLOCK

        without = gate.evaluate_build(corpus_id, attempted_by="pytest")
        assert without.allowed is False

        with_curation = gate.evaluate_build(
            corpus_id,
            attempted_by="pytest",
            curated_licences={doc_id: "cc-by-4.0"},
        )
        assert with_curation.allowed is True
        assert with_curation.violations == ()

    def test_the_override_is_recorded(self, scratch):
        corpus_id, created = scratch
        doc_id = admit(corpus_id, created, None)

        decision = gate.evaluate_build(
            corpus_id,
            attempted_by="pytest",
            curated_licences={doc_id: "cc-by-4.0"},
        )
        assert len(decision.deferrals) == 1
        deferral = decision.deferrals[0]
        assert deferral.doc_id == doc_id
        assert deferral.our_class == "UNKNOWN"
        assert deferral.curated_licence == "cc-by-4.0"
        assert deferral.curated_class == "ATTRIBUTION"
        assert deferral.changed_outcome is True

    def test_deference_that_changes_nothing_is_still_recorded(self, scratch):
        """An override agreeing with us is not interesting, but hiding it would
        make the record incomplete."""
        corpus_id, created = scratch
        doc_id = admit(corpus_id, created, "MIT")

        decision = gate.evaluate_build(
            corpus_id,
            attempted_by="pytest",
            curated_licences={doc_id: "Apache-2.0"},
        )
        assert len(decision.deferrals) == 1
        assert decision.deferrals[0].changed_outcome is False
        assert decision.allowed is True

    def test_curation_can_also_make_things_stricter(self, scratch):
        """Deference is not a rubber stamp: a steward who records a
        non-commercial licence blocks a document we would have permitted."""
        corpus_id, created = scratch
        doc_id = admit(corpus_id, created, "MIT")  # PERMISSIVE -> allowed

        assert gate.evaluate_build(corpus_id, attempted_by="pytest").allowed is True

        decision = gate.evaluate_build(
            corpus_id,
            attempted_by="pytest",
            curated_licences={doc_id: "cc-by-nc-4.0"},
        )
        assert decision.allowed is False
        assert decision.deferrals[0].changed_outcome is True
        assert decision.violations[0].license_class == "NONCOMMERCIAL"

    def test_violation_shows_the_curated_licence_not_the_original(self, scratch):
        """A reviewer must see which value the ruling was actually made on."""
        corpus_id, created = scratch
        doc_id = admit(corpus_id, created, "MIT")

        decision = gate.evaluate_build(
            corpus_id,
            attempted_by="pytest",
            curated_licences={doc_id: "cc-by-nc-4.0"},
        )
        assert "cc-by-nc-4.0" in decision.violations[0].license_raw
        assert "curated" in decision.violations[0].license_raw

    def test_no_curation_means_no_deferrals(self, scratch):
        corpus_id, created = scratch
        admit(corpus_id, created, "MIT")
        assert gate.evaluate_build(corpus_id, attempted_by="pytest").deferrals == ()

    def test_curation_for_an_unrelated_document_is_ignored(self, scratch):
        corpus_id, created = scratch
        admit(corpus_id, created, None)

        decision = gate.evaluate_build(
            corpus_id,
            attempted_by="pytest",
            curated_licences={"test:not-in-this-corpus": "MIT"},
        )
        assert decision.deferrals == ()
        assert decision.allowed is False

    def test_an_unrecognised_curated_licence_still_fails_closed(self, scratch):
        """Deferring to a human does not disable the fail-closed rule: if their
        entry is not a licence we recognise, it is still UNKNOWN."""
        corpus_id, created = scratch
        doc_id = admit(corpus_id, created, "MIT")

        decision = gate.evaluate_build(
            corpus_id,
            attempted_by="pytest",
            curated_licences={doc_id: "ask Bob in legal"},
        )
        assert decision.deferrals[0].curated_class == "UNKNOWN"
        assert decision.allowed is False
