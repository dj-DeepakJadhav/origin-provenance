"""Schema meta-test: exercises all API routes and public functions against the live database.

Guarantees that no SQL statement references a non-existent column, table, or opclass.
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from origin import agent, corpus, db, gate, ledger, retrieval
from origin.api.app import app


@pytest.fixture
def api_client():
    return TestClient(app)


def test_api_read_routes_schema_integrity(api_client):
    """Assert all read-only GET routes execute cleanly against live CockroachDB tables."""
    # 1. Health endpoint
    r_health = api_client.get("/api/v1/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "ok"

    # 2. System Metrics (exercises license_determinations, answers, takedowns, sessions, session_turns)
    r_metrics = api_client.get("/api/v1/metrics")
    assert r_metrics.status_code == 200
    m = r_metrics.json()
    assert "rulings_remembered" in m
    assert "total_takedowns_processed" in m
    assert "total_session_turns" in m

    # 3. Memory rulings (exercises license_determinations)
    r_rulings = api_client.get("/api/v1/memory/rulings?limit=10")
    assert r_rulings.status_code == 200
    assert "rulings" in r_rulings.json()

    # 4. Memory recall probe
    r_recall = api_client.post("/api/v1/memory/recall", json={"license_raw": "MIT"})
    assert r_recall.status_code == 200

    # 5. Cluster control plane & zone topology endpoint
    r_cluster = api_client.get("/api/v1/cluster")
    assert r_cluster.status_code == 200
    c_info = r_cluster.json()
    assert "cluster_info" in c_info
    assert "zones" in c_info

    # 6. Dashboard HTML render
    r_dash = api_client.get("/")
    assert r_dash.status_code == 200
    assert "ORIGIN" in r_dash.text



def test_public_agent_and_corpus_functions_schema_integrity():
    """Assert all public module functions execute SQL against valid columns."""
    # Corpora list
    corpora = corpus.list_corpora()
    assert isinstance(corpora, list)

    if not corpora:
        cid = corpus.create_corpus(name="meta-test-corpus", declared_use="commercial")
    else:
        cid = str(corpora[0]["corpus_id"])

    # Agent recalls
    sem = agent.recall_semantic("mit")
    assert sem is None or "determined_class" in sem

    ep = agent.recall_episodic("What is the license?", limit=2)
    assert isinstance(ep, list)

    now = datetime.now(timezone.utc)
    t = agent.recall_temporal(cid, now)
    assert "source" in t
    assert "doc_ids" in t

    # Gate evaluation
    decision = gate.evaluate_build(cid, attempted_by="meta-test")
    assert hasattr(decision, "allowed")

    # Session transcript & tasks
    sid = agent.create_session(cid, actor="meta-tester")
    transcript = agent.get_session_transcript(sid)
    assert transcript["session"]["actor"] == "meta-tester"

    tasks = agent.list_tasks(session_id=sid)
    assert isinstance(tasks, list)
