"""Tests for agent task state persistence, step progression, and crash resumption."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from origin import agent, corpus, db
from origin.api.app import app


@pytest.fixture
def test_corpus():
    """Ensure a distinct test corpus exists in DB."""
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO corpora (corpus_id, name, declared_use)
            VALUES (gen_random_uuid(), 'test-agent-task-corpus', 'commercial')
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


def test_task_crud_lifecycle(test_corpus):
    session_id = agent.create_session(test_corpus, actor="task-tester")
    task_id = agent.create_task(session_id, kind="corpus_audit", total_steps=4, payload={"test": True})
    assert task_id is not None

    task = agent.get_task(task_id)
    assert task["task_id"] is not None
    assert task["session_id"] == agent.uuid.UUID(session_id) if hasattr(agent, "uuid") else str(task["session_id"]) == session_id
    assert task["state"] == "pending"
    assert task["step_no"] == 0

    # Update step state
    updated = agent.update_task_state(task_id, state="running", step_no=1, result={"inspected": 5})
    assert updated["state"] == "running"
    assert updated["step_no"] == 1
    assert updated["result"]["inspected"] == 5

    tasks = agent.list_tasks(session_id=session_id)
    assert len(tasks) >= 1
    assert any(str(t["task_id"]) == task_id for t in tasks)


def test_run_corpus_audit_task_to_completion(test_corpus):
    session_id = agent.create_session(test_corpus, actor="task-auditor")
    task = agent.run_corpus_audit_task(session_id, test_corpus)

    assert task["state"] == "done"
    assert task["step_no"] == 4
    assert "step_1_members" in task["result"]
    assert "step_2_gate" in task["result"]
    assert "step_3_integrity" in task["result"]
    assert "step_4_report" in task["result"]
    assert task["result"]["step_4_report"]["status"] == "COMPLETED"


def test_task_crash_and_resumption(test_corpus):
    session_id = agent.create_session(test_corpus, actor="crash-tester")
    task_id = agent.create_task(session_id, kind="corpus_audit", total_steps=4, payload={"corpus_id": test_corpus})

    # Simulate crash at step 2
    with pytest.raises(RuntimeError, match="SIMULATED AGENT CRASH AT STEP 2"):
        agent.run_corpus_audit_task(
            session_id,
            test_corpus,
            task_id=task_id,
            simulate_crash_at_step=2,
        )

    # Verify task state in database shows step 2 failure/blocked state with step 1 preserved
    crashed_task = agent.get_task(task_id)
    assert crashed_task["state"] == "blocked"
    assert crashed_task["step_no"] == 1
    assert "step_1_members" in crashed_task["result"]

    # Resume the task from persisted state
    resumed_task = agent.run_corpus_audit_task(
        session_id,
        test_corpus,
        task_id=task_id,
    )

    assert resumed_task["state"] == "done"
    assert resumed_task["step_no"] == 4
    assert "step_3_integrity" in resumed_task["result"]
    assert "step_4_report" in resumed_task["result"]


def test_task_api_endpoints(test_corpus):
    client = TestClient(app)
    session_id = agent.create_session(test_corpus, actor="api-task-tester")

    # 1. Trigger audit task via API
    resp = client.post(
        f"/api/v1/sessions/{session_id}/tasks",
        json={"kind": "corpus_audit", "corpus_id": test_corpus},
    )
    assert resp.status_code == 200
    task_data = resp.json()
    task_id = str(task_data["task_id"])
    assert task_data["state"] == "done"

    # 2. List tasks for session
    list_resp = client.get(f"/api/v1/sessions/{session_id}/tasks")
    assert list_resp.status_code == 200
    assert len(list_resp.json()["tasks"]) >= 1

    # 3. Get single task
    get_resp = client.get(f"/api/v1/tasks/{task_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["task_id"] == task_id
