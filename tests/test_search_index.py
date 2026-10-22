import uuid
import pytest
from origin import corpus, ledger, db
from origin.providers.local import LocalProvider


@pytest.mark.needs_cluster
def test_search_index_sync_and_drift_detection():
    # Use a unique doc_id each run to avoid stale-data collisions.
    unique = uuid.uuid4().hex[:8]
    doc_id = f"test:search-idx-{unique}"

    # Setup test corpus
    corpus_id = corpus.create_corpus(
        name=f"test-sync-corpus-{unique}",
        declared_use="research",
        description="Search index sync test corpus",
    )

    # Admit a document (inserts into documents, corpus_members, and corpus_search_index)
    provider = LocalProvider()
    content = b"Some test content for vector indexing"

    ledger.admit_document(
        corpus_id=corpus_id,
        doc_id=doc_id,
        source_uri="http://example.com/doc1",
        source_system="test",
        content=content,
        title="Test Doc 1",
        license_raw="Apache-2.0",
        provider=provider,
    )

    # 1. Verify it was added to corpus_search_index automatically
    verify_result = corpus.verify_search_index(corpus_id)
    assert verify_result.consistent is True
    assert len(verify_result.missing_from_index) == 0
    assert len(verify_result.orphaned_in_index) == 0

    # 2. Inject drift manually (delete from cache to simulate drift)
    with db.transaction() as cur:
        cur.execute(
            "DELETE FROM corpus_search_index WHERE doc_id = %s", (doc_id,)
        )

    # Verify drift is detected
    verify_result_drift = corpus.verify_search_index(corpus_id)
    assert verify_result_drift.consistent is False
    assert doc_id in verify_result_drift.missing_from_index

    # 3. Re-insert into corpus_search_index to repair drift
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO corpus_search_index (corpus_id, doc_id, embedding)
            SELECT %s, doc_id, embedding FROM documents WHERE doc_id = %s
            """,
            (corpus_id, doc_id),
        )

    # Verify it is consistent again
    verify_result_fixed = corpus.verify_search_index(corpus_id)
    assert verify_result_fixed.consistent is True

    # 4. Takedown removes from corpus_search_index
    corpus.record_takedown(
        doc_id=doc_id,
        requested_by="test-agent",
        reason="rights compliance",
    )

    # Verify it was removed from corpus_search_index and is consistent
    with db.transaction() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM corpus_search_index WHERE doc_id = %s",
            (doc_id,),
        )
        count = cur.fetchone()["n"]
        assert count == 0

    verify_result_takedown = corpus.verify_search_index(corpus_id)
    assert verify_result_takedown.consistent is True
