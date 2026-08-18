"""Unit tests for the five-tier memory forgetting and compaction policy."""

from __future__ import annotations

import pytest

from origin import agent, db, memory_policy


@pytest.fixture
def test_corpus():
    """Ensure a distinct test corpus exists in DB."""
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO corpora (corpus_id, name, declared_use)
            VALUES (gen_random_uuid(), 'test-memory-policy-corpus', 'commercial')
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


@pytest.fixture
def test_session(test_corpus):
    session_id = agent.create_session(test_corpus, actor="policy-test-actor")
    # Insert 6 turns
    for i in range(1, 7):
        role = "user" if i % 2 != 0 else "agent"
        with db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO session_turns (session_id, turn_no, role, content)
                VALUES (%s, %s, %s, %s)
                """,
                (session_id, i, role, f"Test statement for turn {i}"),
            )
    return session_id


def test_compact_working_memory_preserves_history(test_session):
    res = memory_policy.compact_working_memory(test_session, keep_recent_turns=4)
    assert res["compacted"] is True
    assert res["turns_compacted"] == 2
    assert res["retained_recent_turns"] == 4

    # Verify all turns + summary turn exist in database (no destructive deletion)
    transcript = agent.get_session_transcript(test_session)
    assert len(transcript["turns"]) == 7
    roles = [t["role"] for t in transcript["turns"]]
    assert "summary_compaction" in roles


def test_decay_semantic_memory_human_confirmed_exempt():
    decay_report = memory_policy.decay_semantic_memory(min_strength_threshold=1.0, max_idle_days=30)
    assert decay_report["human_confirmed_exempt"] is True
    assert "eligible_for_decay" in decay_report
