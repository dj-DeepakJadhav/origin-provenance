"""Integration tests against a live CockroachDB cluster.

Skipped automatically when DATABASE_URL is unset, so the suite stays runnable
with no infrastructure.

These exist because two defects in this area were invisible to unit tests and
only surfaced on a real cluster:

  1. ``read_as_of`` never worked. psycopg3 opens an implicit transaction on
     first execute, so the explicit ``BEGIN AS OF SYSTEM TIME`` failed with
     "there is already a transaction in progress". Nothing that mocks the driver
     would have caught it.

  2. Reading as of an instant before the migration ran returns
     ``database "origin" does not exist`` — MVCC rewinds the catalog as well as
     the rows. Correct behaviour, but it needed handling rather than a traceback.

Both are pinned below.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from origin import corpus, db, gate, ledger

pytestmark = pytest.mark.needs_cluster


@pytest.fixture
def temp_corpus():
    """A uniquely-named commercial corpus, removed afterwards.

    Named with a uuid so concurrent runs cannot collide, and cleaned up in
    dependency order because corpus_members references both sides.
    """
    name = f"test-{uuid.uuid4().hex[:12]}"
    corpus_id = corpus.create_corpus(
        name=name, declared_use="commercial", description="integration test"
    )
    yield corpus_id, name

    with db.transaction() as cur:
        cur.execute(
            """
            DELETE FROM answer_attributions WHERE doc_id IN (
                SELECT doc_id FROM corpus_members WHERE corpus_id = %s
            )
            """,
            (corpus_id,),
        )
        # Takedowns are keyed by doc_id, not corpus, and admission now refuses
        # any document with a takedown on record — so leaving these behind would
        # make later runs mysteriously refuse documents.
        cur.execute(
            """
            DELETE FROM takedowns WHERE doc_id IN (
                SELECT doc_id FROM corpus_members WHERE corpus_id = %s
            )
            """,
            (corpus_id,),
        )
        cur.execute("DELETE FROM corpus_members WHERE corpus_id = %s", (corpus_id,))
        cur.execute("DELETE FROM build_gates WHERE corpus_id = %s", (corpus_id,))
        cur.execute("DELETE FROM answers WHERE corpus_id = %s", (corpus_id,))
        cur.execute("DELETE FROM corpora WHERE corpus_id = %s", (corpus_id,))


def _admit(corpus_id: str, suffix: str, license_raw: str | None) -> str:
    doc_id = f"test:{suffix}-{uuid.uuid4().hex[:8]}"
    ledger.admit_document(
        corpus_id=corpus_id,
        doc_id=doc_id,
        source_uri=f"https://example.invalid/{suffix}",
        source_system="test",
        content=f"content for {suffix}".encode("utf-8"),
        title=suffix,
        license_raw=license_raw,
        storage_key=f"test/{suffix}-{uuid.uuid4().hex[:8]}.txt",
    )
    return doc_id


class TestTimeTravel:
    def test_read_as_of_uses_the_mvcc_path(self, temp_corpus):
        """Regression: this raised ActiveSqlTransaction before the autocommit fix."""
        corpus_id, _ = temp_corpus
        _admit(corpus_id, "mvcc-doc", "MIT")

        membership = corpus.membership_as_of(corpus_id, "-5s")
        assert membership.source == "mvcc", (
            "expected the MVCC path; falling back to bitemporal here would hide "
            "a broken AS OF SYSTEM TIME"
        )

    def test_membership_grows_between_two_past_instants(self, temp_corpus):
        corpus_id, _ = temp_corpus

        with db.transaction() as cur:
            cur.execute("SELECT now() AS t")
            before = cur.fetchone()["t"]

        _admit(corpus_id, "later-doc", "Apache-2.0")

        with db.transaction() as cur:
            cur.execute("SELECT now() AS t")
            after = cur.fetchone()["t"]

        assert len(corpus.membership_as_of(corpus_id, before)) == 0
        assert len(corpus.membership_as_of(corpus_id, after)) == 1

    def test_instant_before_the_schema_is_reported_not_crashed(self):
        """MVCC rewinds the catalog too, so far enough back there is no database.

        The query must touch a real table. ``SELECT 1`` resolves no catalog
        entry, so it succeeds at any timestamp and proves nothing — which is how
        the first version of this test passed while the behaviour was untested.
        """
        long_ago = datetime.now(timezone.utc) - timedelta(days=365)
        with pytest.raises(
            (db.TimeTravelBeforeSchema, db.TimeTravelBeyondRetention)
        ):
            with db.read_as_of(long_ago) as cur:
                cur.execute("SELECT count(*) FROM corpus_members")

    def test_future_timestamp_is_refused(self):
        with pytest.raises(ValueError, match="future"):
            with db.read_as_of(datetime.now(timezone.utc) + timedelta(hours=1)):
                pass


class TestIntegrityCrossCheck:
    def test_paths_agree_after_admission(self, temp_corpus):
        """The project's central claim: neither source alone is evidence."""
        corpus_id, _ = temp_corpus
        _admit(corpus_id, "agree-a", "MIT")
        _admit(corpus_id, "agree-b", "CC-BY-4.0")

        with db.transaction() as cur:
            cur.execute("SELECT now() AS t")
            now = cur.fetchone()["t"]

        result = corpus.verify_integrity(corpus_id, now)
        assert result.conclusive
        assert result.consistent
        assert not result.mvcc_only
        assert not result.bitemporal_only

    def test_forced_bitemporal_matches_mvcc(self, temp_corpus):
        corpus_id, _ = temp_corpus
        _admit(corpus_id, "both-paths", "MIT")

        with db.transaction() as cur:
            cur.execute("SELECT now() AS t")
            now = cur.fetchone()["t"]

        via_mvcc = corpus.membership_as_of(corpus_id, now, prefer_mvcc=True)
        via_columns = corpus.membership_as_of(corpus_id, now, prefer_mvcc=False)
        assert via_mvcc.source == "mvcc"
        assert via_columns.source == "bitemporal"
        assert via_mvcc.doc_ids == via_columns.doc_ids


class TestLedgerMemory:
    def test_identical_licence_string_is_served_from_memory(self, temp_corpus):
        """The second occurrence must not be re-classified."""
        corpus_id, _ = temp_corpus
        unique = f"Bespoke Licence {uuid.uuid4().hex[:8]} v1"

        with db.transaction() as cur:
            first = ledger.classify_license(cur, unique)
        assert first.from_memory is False

        with db.transaction() as cur:
            second = ledger.classify_license(cur, unique)
        assert second.from_memory is True
        assert second.decided_by == "memory:exact"
        assert second.license_class == first.license_class

    def test_readmitting_identical_content_is_a_no_op(self, temp_corpus):
        corpus_id, _ = temp_corpus
        doc_id = f"test:idem-{uuid.uuid4().hex[:8]}"
        key = f"test/idem-{uuid.uuid4().hex[:8]}.txt"

        common = dict(
            corpus_id=corpus_id,
            doc_id=doc_id,
            source_uri="https://example.invalid/idem",
            source_system="test",
            content=b"stable bytes",
            license_raw="MIT",
            storage_key=key,
        )
        first = ledger.admit_document(**common)
        second = ledger.admit_document(**common)

        assert first.newly_admitted is True
        assert second.newly_admitted is False
        assert first.content_hash == second.content_hash


class TestGate:
    def test_unknown_licence_blocks_the_build(self, temp_corpus):
        corpus_id, _ = temp_corpus
        _admit(corpus_id, "no-licence", None)

        decision = gate.evaluate_build(corpus_id, attempted_by="pytest")
        assert decision.allowed is False
        assert len(decision.violations) == 1
        assert decision.violations[0].license_class == "UNKNOWN"
        assert decision.violations[0].clause.strip()

    def test_noncommercial_blocks_a_commercial_corpus(self, temp_corpus):
        corpus_id, _ = temp_corpus
        _admit(corpus_id, "nc-doc", "CC-BY-NC-4.0")

        decision = gate.evaluate_build(corpus_id, attempted_by="pytest")
        assert decision.allowed is False
        assert any(
            v.license_class == "NONCOMMERCIAL" for v in decision.violations
        )

    def test_permissive_only_corpus_is_allowed(self, temp_corpus):
        corpus_id, _ = temp_corpus
        _admit(corpus_id, "mit-doc", "MIT")
        _admit(corpus_id, "apache-doc", "Apache-2.0")

        decision = gate.evaluate_build(corpus_id, attempted_by="pytest")
        assert decision.allowed is True
        assert decision.violations == ()
        # Permissive in a commercial corpus carries a notice obligation.
        assert decision.obligations

    def test_every_attempt_is_recorded(self, temp_corpus):
        """A blocked build is the most valuable row in the database."""
        corpus_id, _ = temp_corpus
        _admit(corpus_id, "recorded", None)

        gate.evaluate_build(corpus_id, attempted_by="pytest")
        history = gate.gate_history(corpus_id)
        assert len(history) == 1
        assert history[0]["decision"] == "blocked"
        assert history[0]["violation_count"] == 1


class TestTakedown:
    def test_takedown_soft_deletes_and_reports_affected_answers(self, temp_corpus):
        corpus_id, _ = temp_corpus
        doc_id = _admit(corpus_id, "takedown-target", "MIT")

        answer_id = corpus.record_answer(
            corpus_id=corpus_id,
            question="what does this dataset contain?",
            answer_text="it contains things",
            retrieved=[(doc_id, 0.91)],
            model_version="test-model",
            asked_by="pytest",
        )

        affected = corpus.takedown_impact(doc_id)
        assert [a.answer_id for a in affected] == [answer_id]

        _, reported = corpus.record_takedown(
            doc_id=doc_id, requested_by="pytest", reason="test"
        )
        assert [a.answer_id for a in reported] == [answer_id]

        # Soft delete: gone from the corpus, still present in the ledger.
        assert doc_id not in corpus.current_members(corpus_id)
        with db.transaction() as cur:
            cur.execute(
                "SELECT removed_at, removal_reason FROM corpus_members "
                "WHERE corpus_id = %s AND doc_id = %s",
                (corpus_id, doc_id),
            )
            row = cur.fetchone()
        assert row is not None, "hard delete would destroy the record we keep"
        assert row["removed_at"] is not None
        assert row["removal_reason"] == "takedown"

    def test_past_answers_remain_attributable_after_takedown(self, temp_corpus):
        """The whole point: removal must not erase what it was used for."""
        corpus_id, _ = temp_corpus
        doc_id = _admit(corpus_id, "still-attributable", "MIT")
        corpus.record_answer(
            corpus_id=corpus_id,
            question="q",
            answer_text="a",
            retrieved=[(doc_id, 0.5)],
            model_version="test-model",
        )
        corpus.record_takedown(
            doc_id=doc_id, requested_by="pytest", reason="test"
        )
        assert len(corpus.takedown_impact(doc_id)) == 1


class TestCorpusGuards:
    def test_refuses_to_repurpose_an_existing_corpus(self, temp_corpus):
        """Silently changing declared_use would change what the gate enforces."""
        _, name = temp_corpus
        with pytest.raises(ValueError, match="refusing to change"):
            corpus.create_corpus(name=name, declared_use="research")

    def test_same_declared_use_is_idempotent(self, temp_corpus):
        corpus_id, name = temp_corpus
        assert corpus.create_corpus(name=name, declared_use="commercial") == corpus_id

    def test_invalid_declared_use_is_rejected(self):
        with pytest.raises(ValueError, match="declared_use"):
            corpus.create_corpus(name="never-created", declared_use="whatever")
