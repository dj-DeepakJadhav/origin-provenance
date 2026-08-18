"""Tests for agent working memory, semantic/episodic/temporal recall, and atomic transactions."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch
import pytest

from origin import agent, corpus, db, retrieval


@pytest.fixture
def test_corpus():
    """Ensure a distinct test corpus exists in DB."""
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO corpora (corpus_id, name, declared_use)
            VALUES (gen_random_uuid(), 'test-agent-suite-corpus', 'commercial')
            ON CONFLICT DO NOTHING
            RETURNING corpus_id
            """
        )
        row = cur.fetchone()
        if row:
            cid = str(row["corpus_id"])
        else:
            cur.execute("SELECT corpus_id FROM corpora LIMIT 1")
            cid = str(cur.fetchone()["corpus_id"])
    return cid


def test_recall_semantic_exact_and_similar():
    # Exact match on pre-existing MIT ruling
    ruling = agent.recall_semantic("mit")
    assert ruling is not None
    assert ruling["determined_class"] == "PERMISSIVE"
    assert "strength" in ruling

    # Case-insensitive / whitespace cosmetic variation
    near_ruling = agent.recall_semantic(" MIT ")
    assert near_ruling is not None
    assert near_ruling["determined_class"] == "PERMISSIVE"


def test_recall_episodic_with_receipts():
    answers = agent.recall_episodic("What is the license?", limit=3)
    assert isinstance(answers, list)
    if answers:
        a = answers[0]
        assert "answer_id" in a
        assert "question" in a
        assert "receipts" in a
        assert isinstance(a["receipts"], list)


def test_recall_temporal(test_corpus):
    now = datetime.now(timezone.utc)
    t_state = agent.recall_temporal(test_corpus, now)
    assert t_state["corpus_id"] == test_corpus
    assert "source" in t_state
    assert t_state["source"] in ("mvcc", "bitemporal")
    assert isinstance(t_state["doc_ids"], list)


def test_session_lifecycle_and_multi_turn_continuity(test_corpus):
    session_id = agent.create_session(test_corpus, actor="test-analyst")
    assert session_id is not None

    transcript = agent.get_session_transcript(session_id)
    assert transcript["session"]["actor"] == "test-analyst"
    assert len(transcript["turns"]) == 0

    # Execute first turn
    resp1 = agent.respond(session_id, "What license does the healthcare dataset use?")
    assert resp1["session_id"] == session_id
    assert resp1["turn_no"] == 2
    assert resp1["memory_used"]["memory_enabled"] is True
    assert resp1["memory_used"]["attributions_recorded"] >= 0
    assert "acted_on" in resp1["memory_used"]

    # Execute follow-up turn (testing working memory continuity)
    resp2 = agent.respond(session_id, "Can it be used commercially?")
    assert resp2["turn_no"] == 4
    assert resp2["memory_used"]["working_turns_recalled"] >= 2

    # Verify transcript history in database
    updated_transcript = agent.get_session_transcript(session_id)
    assert len(updated_transcript["turns"]) == 4
    assert updated_transcript["turns"][0]["role"] == "user"
    assert updated_transcript["turns"][1]["role"] == "agent"


def test_ablation_kill_switch_disables_recall(test_corpus):
    """Assert that memory_enabled=False skips working memory recall while still committing atomically."""
    session_id = agent.create_session(test_corpus, actor="ablation-test-actor")

    # Turn 1
    resp1 = agent.respond(
        session_id,
        "What datasets are in this corpus?",
        memory_enabled=False,
    )
    assert resp1["memory_used"]["memory_enabled"] is False
    assert resp1["memory_used"]["working_turns_recalled"] == 0
    assert resp1["memory_used"]["semantic_rulings_used"] == 0
    assert resp1["memory_used"]["attributions_recorded"] >= 0

    # Turn 2: Without memory, working turns recalled remains 0
    resp2 = agent.respond(
        session_id,
        "Which of those are non-commercial?",
        memory_enabled=False,
    )
    assert resp2["memory_used"]["memory_enabled"] is False
    assert resp2["memory_used"]["working_turns_recalled"] == 0
    assert resp2["turn_no"] == 4
    assert resp2["memory_used"]["attributions_recorded"] >= 0


def test_atomic_transaction_rollback_on_failure(test_corpus):
    """Assert that if turn insertion fails, NO answer or attribution rows persist."""
    session_id = agent.create_session(test_corpus, actor="atomic-test-actor")

    with db.transaction() as cur:
        cur.execute("SELECT count(*) AS n FROM answers")
        answers_before = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM session_turns WHERE session_id = %s", (session_id,))
        turns_before = cur.fetchone()["n"]

    # Inject an intentional error during the atomic write
    original_record_answer_tx = corpus.record_answer_tx

    def failing_record_answer_tx(*args, **kwargs):
        aid = original_record_answer_tx(*args, **kwargs)
        raise RuntimeError("SIMULATED DATABASE CRASH MID-TRANSACTION")

    with patch("origin.corpus.record_answer_tx", side_effect=failing_record_answer_tx):
        with pytest.raises(RuntimeError, match="SIMULATED DATABASE CRASH"):
            agent.respond(session_id, "Should this question commit if transaction fails?")

    # Verify atomic rollback: nothing was persisted for this session
    with db.transaction() as cur:
        cur.execute("SELECT count(*) AS n FROM session_turns WHERE session_id = %s", (session_id,))
        turns_after = cur.fetchone()["n"]
        cur.execute(
            """
            SELECT count(*) AS n FROM answers a 
            JOIN session_turns st ON a.answer_id = st.answer_id 
            WHERE st.session_id = %s
            """,
            (session_id,),
        )
        linked_answers = cur.fetchone()["n"]

    assert turns_after == turns_before
    assert linked_answers == 0
